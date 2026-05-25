"""
Feeder Risk Scoring Agent — Stage 4 of the Winter Peak pipeline.

Scores per-feeder and per-substation risk under each simulated scenario.
Risk math is deterministic (capacity utilization, voltage sag heuristics);
Claude generates the per-feeder rationale strings ("why this feeder breaks
first") for the report.
"""
from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.grid.winter_simulator import per_feeder_peak_load
from backend.models.winter_peak import (
    ColdEvent,
    DistributionNetwork,
    Feeder,
    FeederRisk,
    ScenarioPreset,
    SubstationRisk,
)


SYSTEM_FEEDER_RISK = """You are a distribution-network risk analyst.
You explain in plain English why a particular feeder fails first under
a winter peak event. Reference the feeder's specific characteristics
(age, heating mix, EV penetration, customer count) when relevant. Be
concise — one sentence per feeder. No markdown.""" + GROUNDING_RULES


class FeederRiskAgent(BaseAgent):
    """Stage 4: per-scenario load profile → ranked feeder/substation risk."""

    async def score_scenario(
        self,
        network: DistributionNetwork,
        cold_event: ColdEvent,
        scenario: ScenarioPreset,
        progress_callback=None,
        progress_offset_pct: int = 60,
    ) -> tuple[list[FeederRisk], list[SubstationRisk]]:
        """
        Score every feeder and substation for one scenario. Returns
        (feeder_risks, substation_risks) sorted by descending risk.
        """
        if progress_callback:
            await progress_callback(
                f"Scoring feeder risks for {scenario.label}...",
                progress_offset_pct,
            )

        # Deterministic peak load lookup per feeder
        peak_loads_mva = per_feeder_peak_load(network, cold_event, scenario)
        feeders_by_id = {f.feeder_id: f for f in network.feeders}

        feeder_risks: list[FeederRisk] = []
        for fid, peak_mva in peak_loads_mva.items():
            feeder = feeders_by_id[fid]
            risk = self._score_feeder(feeder, peak_mva, scenario)
            feeder_risks.append(risk)

        # Sort by risk descending
        feeder_risks.sort(key=lambda r: r.overload_risk, reverse=True)
        for i, fr in enumerate(feeder_risks):
            fr.rank = i + 1

        # Add Claude rationales for the top-N riskiest feeders only (cost control)
        top_n = min(10, len(feeder_risks))
        await self._add_rationales(feeder_risks[:top_n], feeders_by_id, scenario)

        # Aggregate to substations
        substation_risks = self._aggregate_substations(network, feeder_risks, scenario)

        return feeder_risks, substation_risks

    def _score_feeder(
        self,
        feeder: Feeder,
        peak_mva: float,
        scenario: ScenarioPreset,
    ) -> FeederRisk:
        """Deterministic risk scoring from capacity utilization."""
        utilization_pct = (peak_mva / max(0.01, feeder.rated_capacity_mva)) * 100.0

        # Overload risk: smooth ramp from 0 (≤80% util) to 1 (≥120% util)
        if utilization_pct <= 80:
            overload_risk = 0.0
        elif utilization_pct >= 120:
            overload_risk = 1.0
        else:
            overload_risk = (utilization_pct - 80) / 40.0

        # Voltage sag risk amplified by feeder age, dampened by recent upgrade
        age_factor = min(1.0, feeder.age_years / 50.0)
        upgrade_dampener = 0.7 if feeder.has_recent_upgrade else 1.0
        voltage_sag_risk = min(1.0, overload_risk * 0.7 + age_factor * 0.3) * upgrade_dampener

        # Time to thermal failure: rough estimate from severity of overload
        if utilization_pct < 100:
            ttf = None
        else:
            # Rough: 100% util → 24h to thermal limit, 130% → 2h, 150% → ~30 min
            severity = (utilization_pct - 100) / 50.0  # 0..1+
            ttf = max(0.5, 24.0 * (1.0 - min(0.95, severity)))

        # Failure mode classification
        if overload_risk >= 0.8:
            failure_mode = "thermal_overload"
        elif voltage_sag_risk >= 0.6 and overload_risk < 0.5:
            failure_mode = "voltage_collapse"
        else:
            failure_mode = "none"

        return FeederRisk(
            feeder_id=feeder.feeder_id,
            feeder_name=feeder.name,
            parent_substation_id=feeder.parent_substation_id,
            scenario_name=scenario.name,
            overload_risk=round(overload_risk, 3),
            voltage_sag_risk=round(voltage_sag_risk, 3),
            time_to_failure_hours=round(ttf, 1) if ttf is not None else None,
            peak_load_mva=round(peak_mva, 2),
            capacity_utilization_pct=round(utilization_pct, 1),
            failure_mode=failure_mode,
            rationale="",
        )

    async def _add_rationales(
        self,
        top_risks: list[FeederRisk],
        feeders_by_id: dict[str, Feeder],
        scenario: ScenarioPreset,
    ) -> None:
        """Generate one-line Claude rationale for the top-N risky feeders."""
        if not top_risks:
            return

        # Build a compact summary table for Claude
        rows = []
        for r in top_risks:
            f = feeders_by_id.get(r.feeder_id)
            if f is None:
                continue
            heating_summary = ", ".join(
                f"{k} {v*100:.0f}%" for k, v in f.primary_heating_mix.items() if v > 0.05
            )
            rows.append({
                "feeder_id": r.feeder_id,
                "feeder_name": r.feeder_name,
                "customers": f.customer_count,
                "rated_mva": f.rated_capacity_mva,
                "peak_mva": r.peak_load_mva,
                "utilization_pct": r.capacity_utilization_pct,
                "overload_risk": r.overload_risk,
                "age_years": f.age_years,
                "had_upgrade": f.has_recent_upgrade,
                "heating_mix": heating_summary,
                "ev_pct": f.ev_penetration_pct,
                "failure_mode": r.failure_mode,
            })

        prompt = f"""For each feeder below, write one short sentence explaining
why it's at risk under the "{scenario.label}" scenario. Reference its
specific weaknesses (age, heating mix, EV penetration). Output JSON:

{{
  "rationales": {{
    "<feeder_id>": "<one sentence>",
    ...
  }}
}}

Feeders:
{rows}"""

        try:
            response = await self.ask_claude_json(SYSTEM_FEEDER_RISK, prompt, max_tokens=2048)
            rationales = response.get("rationales", {})
            for r in top_risks:
                rationale = rationales.get(r.feeder_id, "")
                if rationale:
                    r.rationale = rationale
        except Exception as e:
            self.logger.warning(f"Feeder rationale generation failed: {e}")
            # Fill with deterministic fallback
            for r in top_risks:
                r.rationale = (
                    f"{r.failure_mode.replace('_', ' ').capitalize()}; "
                    f"peak utilization {r.capacity_utilization_pct}% of rated capacity."
                )

    def _aggregate_substations(
        self,
        network: DistributionNetwork,
        feeder_risks: list[FeederRisk],
        scenario: ScenarioPreset,
    ) -> list[SubstationRisk]:
        """Roll feeder risks up to substation-level aggregates."""
        risks_by_sub: dict[str, list[FeederRisk]] = {}
        for fr in feeder_risks:
            risks_by_sub.setdefault(fr.parent_substation_id, []).append(fr)

        subs_by_id = {s.substation_id: s for s in network.substations}
        sub_risks: list[SubstationRisk] = []
        for sub_id, frs in risks_by_sub.items():
            sub = subs_by_id.get(sub_id)
            if sub is None:
                continue
            agg_risk = max((fr.overload_risk for fr in frs), default=0.0)
            agg_peak_mva = sum(fr.peak_load_mva for fr in frs)
            agg_util = (agg_peak_mva / max(0.01, sub.nameplate_mva)) * 100.0
            at_risk_count = sum(1 for fr in frs if fr.overload_risk >= 0.5)

            sub_risks.append(SubstationRisk(
                substation_id=sub_id,
                substation_name=sub.name,
                scenario_name=scenario.name,
                aggregate_risk=round(agg_risk, 3),
                peak_load_mva=round(agg_peak_mva, 2),
                peak_utilization_pct=round(agg_util, 1),
                at_risk_feeder_count=at_risk_count,
                rationale=(
                    f"{at_risk_count}/{len(frs)} feeders at risk; "
                    f"aggregate utilization {agg_util:.0f}%."
                ),
            ))

        sub_risks.sort(key=lambda s: s.aggregate_risk, reverse=True)
        return sub_risks
