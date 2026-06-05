"""
Stage 5 of Neighborhood Electrification Readiness — synthesize the final
ElectrificationPlan: per-FSA outcomes, recommended interventions, executive
summary, methodology, and limitations.
"""
from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.models.electrification import (
    AdoptionScenario,
    ElectrificationPlan,
    ElectrificationSpec,
    FSAOutcome,
    Intervention,
    NeighborhoodLoadImpact,
    NeighborhoodProfile,
    ReadinessScore,
)
from backend.models.report import CitationSource
from backend.utils.citations import synthesize_with_citations
from backend.utils.reconciliation import reconcile


SYSTEM = """You are a senior grid planner writing the executive summary of a
neighborhood electrification readiness study for a municipal council. Be
specific, numeric, and confident. No bullet lists, just flowing prose.""" + GROUNDING_RULES


def _verdict_for_summary(scores: list[ReadinessScore]) -> str:
    if not scores:
        return "INCONCLUSIVE"
    blocked = sum(1 for s in scores if s.verdict == "BLOCKED")
    constrained = sum(1 for s in scores if s.verdict == "CONSTRAINED")
    if blocked >= len(scores) / 2:
        return "BLOCKED"
    if constrained + blocked >= len(scores) / 2:
        return "CONSTRAINED"
    return "READY"


class ElectrificationSynthesisAgent(BaseAgent):
    async def synthesize(
        self,
        *,
        job_id: str,
        spec: ElectrificationSpec,
        profiles: list[NeighborhoodProfile],
        scenarios: list[AdoptionScenario],
        impacts: dict[tuple[str, str], NeighborhoodLoadImpact],
        scores: dict[tuple[str, str], ReadinessScore],
        progress_callback=None,
    ) -> ElectrificationPlan:
        if progress_callback:
            await progress_callback("Composing electrification readiness report...", 88)

        outcomes: list[FSAOutcome] = []
        for prof in profiles:
            for sc in scenarios:
                key = (prof.fsa, sc.name)
                if key not in impacts or key not in scores:
                    continue
                outcomes.append(FSAOutcome(
                    profile=prof,
                    scenario=sc,
                    load_impact=impacts[key],
                    readiness=scores[key],
                ))

        interventions = self._compose_interventions(profiles, scenarios, impacts, scores)

        summary, citation_sources = await self._exec_summary(spec, profiles, scenarios, scores, interventions)

        # Pattern 3 — reconcile Claude's exec summary against scenario facts.
        # Drifted adoption percentages and readiness scores are rewritten with
        # the values the spec/scoring stage actually computed.
        if scenarios:
            sc = scenarios[0]
            avg_overall = (
                sum(s.overall_score for s in scores.values()) / max(1, len(scores))
                if scores else 0.0
            )
            recon_facts = {
                "heat_pump_adoption_pct": sc.heat_pump_conversion_pct,
                "ev_adoption_pct": sc.ev_adoption_pct,
                "overall_score": avg_overall,
            }
            summary = reconcile(summary, recon_facts).corrected_text

        limitations = [
            "FSA topology is approximated from province-average transformer-to-household ratios.",
            "Behind-the-meter generation (rooftop PV) is not modeled.",
            "Panel age and gauge data are not available; the 18 kW trigger is a conservative proxy.",
            "Time-of-use price response (managed charging) is not modeled in the baseline.",
        ]
        # If any Claude call (per-FSA rationales or exec summary) hit the
        # max_tokens cap on this agent, surface it so the operator sees the
        # narrative may be clipped. See base_agent._truncation_count.
        if self.had_truncation():
            limitations.append(
                f"{self._truncation_count} Claude response(s) hit the max_tokens "
                "cap, so executive summary or per-FSA rationale may be incomplete. "
                "Raise the cap in REPORTS_COHESION.md §8b and re-run."
            )

        plan = ElectrificationPlan(
            job_id=job_id,
            spec=spec,
            neighborhoods=profiles,
            fsa_outcomes=outcomes,
            interventions=interventions,
            executive_summary=summary,
            citation_sources=citation_sources,
            methodology_notes=(
                "Per-FSA load impact built from a 24-hour winter peak day "
                "temperature curve scaled by ECCC HDD18 normals. Heat pump "
                "draws use NRCan ccASHP COP curves with backup engagement "
                "below -10 °C. EV charging follows IESO ResLoad evening "
                "L2 shape with cold-weather multipliers. Transformer "
                "overload heuristic: 75 kVA serving ~40 households, 0.95 PF. "
                "Panel upgrade trigger: continuous peak > 18 kW per home."
            ),
            safety_flags=self._safety_flags(scores),
            limitations=limitations,
        )
        return plan

    def _compose_interventions(
        self,
        profiles: list[NeighborhoodProfile],
        scenarios: list[AdoptionScenario],
        impacts: dict[tuple[str, str], NeighborhoodLoadImpact],
        scores: dict[tuple[str, str], ReadinessScore],
    ) -> list[Intervention]:
        out: list[Intervention] = []

        # Pick the most aggressive scenario for sizing — that's where the
        # binding constraints show up.
        target = max(scenarios, key=lambda s: s.heat_pump_conversion_pct + s.ev_adoption_pct, default=None)
        if target is None:
            return out

        # 1. Panel upgrade rebate program — sized on aggregate panel-upgrade need
        panel_total_hh = 0
        panel_fsas: list[str] = []
        for prof in profiles:
            impact = impacts.get((prof.fsa, target.name))
            if not impact:
                continue
            need = int(impact.panel_upgrade_household_pct * prof.households)
            if need > 0:
                panel_total_hh += need
                panel_fsas.append(prof.fsa)
        if panel_total_hh > 0:
            out.append(Intervention(
                intervention_id="panel_upgrade_rebate",
                title="Targeted panel-upgrade rebate program",
                category="rebate_program",
                targeted_fsas=panel_fsas,
                households_unlocked=panel_total_hh,
                estimated_cost_cad=panel_total_hh * 1_800.0,        # avg $1.8K rebate
                deployment_months=6,
                readiness_lift_pct=12.0,
                rationale=(
                    f"Roughly {panel_total_hh:,} homes need a 100A → 200A panel upgrade "
                    "to support full HP + EV electrification. A municipal-led rebate "
                    "stacked on the federal Greener Homes loan removes the bill-shock "
                    "barrier for low-income owners."
                ),
            ))

        # 2. Local transformer upgrade
        xfmr_total = 0
        xfmr_fsas: list[str] = []
        for prof in profiles:
            impact = impacts.get((prof.fsa, target.name))
            if impact and impact.transformer_overload_count > 0:
                xfmr_total += impact.transformer_overload_count
                xfmr_fsas.append(prof.fsa)
        if xfmr_total > 0:
            out.append(Intervention(
                intervention_id="transformer_upgrade",
                title=f"Upgrade {xfmr_total} local distribution transformers",
                category="transformer_upgrade",
                targeted_fsas=xfmr_fsas,
                households_unlocked=xfmr_total * 40,
                estimated_cost_cad=xfmr_total * 18_000.0,            # avg $18K per replacement
                deployment_months=12,
                readiness_lift_pct=18.0,
                rationale=(
                    f"At the {target.label.lower()} target, {xfmr_total} pad-mount "
                    "transformers are projected to exceed 75 kVA continuous loading. "
                    "Replacing with 100/167 kVA units in the first capital cycle is "
                    "cheaper than emergency replacement after a failure."
                ),
            ))

        # 3. Managed charging — cuts EV evening peak in half
        if any(s.ev_adoption_pct >= 0.20 for s in scenarios):
            ev_relief = sum(
                impacts.get((p.fsa, target.name)).incremental_peak_mw * 0.20
                for p in profiles if (p.fsa, target.name) in impacts
            )
            out.append(Intervention(
                intervention_id="managed_charging",
                title="Default-on managed EV charging tariff",
                category="managed_charging",
                targeted_fsas=[p.fsa for p in profiles],
                households_unlocked=int(sum(p.households * target.ev_adoption_pct for p in profiles)),
                estimated_cost_cad=350_000.0,                        # billing system + onboarding
                deployment_months=9,
                readiness_lift_pct=10.0,
                rationale=(
                    f"Shifting EV charge to overnight off-peak slots cuts the evening "
                    f"distribution peak by ~{ev_relief:.1f} MW across the studied FSAs "
                    "with no infrastructure spend. Opt-out tariff structure has the "
                    "best uptake in field trials (Hydro One TOU pilot)."
                ),
            ))

        # 4. Code change — mandatory rough-in for HP + EV in new builds
        out.append(Intervention(
            intervention_id="ev_hp_rough_in_code",
            title="Mandatory HP + EV rough-in in new builds (zoning bylaw)",
            category="code_change",
            targeted_fsas=[p.fsa for p in profiles],
            households_unlocked=0,
            estimated_cost_cad=80_000.0,                             # admin + comms
            deployment_months=4,
            readiness_lift_pct=4.0,
            rationale=(
                "Adds ~$1.5K to new-build cost but avoids 6× retrofit cost. Vancouver "
                "and Burnaby have demonstrated this is politically feasible at the "
                "municipal layer; it stacks on provincial step-code requirements."
            ),
        ))
        return out

    def _safety_flags(self, scores: dict[tuple[str, str], ReadinessScore]) -> list[str]:
        flags: list[str] = []
        blocked = [s for s in scores.values() if s.verdict == "BLOCKED"]
        if blocked:
            flags.append(
                f"{len(blocked)} (FSA × scenario) pairings are BLOCKED. Likely loss of "
                "service unless interventions are deployed before the target year."
            )
        if any(s.affordability_score < 0.30 for s in scores.values()):
            flags.append(
                "Severe affordability gap detected. Equity risk if rebate stack is not "
                "in place before mass HP retrofits."
            )
        return flags

    async def _exec_summary(
        self,
        spec: ElectrificationSpec,
        profiles: list[NeighborhoodProfile],
        scenarios: list[AdoptionScenario],
        scores: dict[tuple[str, str], ReadinessScore],
        interventions: list[Intervention],
    ) -> tuple[str, dict[str, CitationSource]]:
        n_blocked = sum(1 for s in scores.values() if s.verdict == "BLOCKED")
        n_constrained = sum(1 for s in scores.values() if s.verdict == "CONSTRAINED")
        n_ready = sum(1 for s in scores.values() if s.verdict == "READY")
        verdict = _verdict_for_summary(list(scores.values()))

        prompt = f"""Write a 4-5 paragraph executive summary for a municipal council.

Format: open with `# Executive Summary: <one-line topic>`. Each paragraph
begins with `**<2-5 word bold title>**` on its own line, then a blank line,
then the prose. Separate paragraphs with blank lines only. Do NOT insert
`---` or any horizontal-rule dividers, and do NOT use markdown tables
(the renderer does not display them). Avoid em dashes anywhere in the
prose; use commas, periods, or parentheses.

City: {spec.city} ({spec.province})
FSAs studied: {', '.join(p.fsa for p in profiles)}
Scenarios tested: {', '.join(s.label for s in scenarios)}

Pairings READY: {n_ready}
Pairings CONSTRAINED: {n_constrained}
Pairings BLOCKED: {n_blocked}
Headline verdict: {verdict}

Recommended interventions: {', '.join(i.title for i in interventions[:3])}

Paragraph 1: the verdict (READY / CONSTRAINED / BLOCKED) and the headline numbers.
Paragraph 2: the binding constraint (grid headroom, panel capacity, or affordability)
and which 1-2 specific FSAs drive the conclusion.
Paragraph 3: scenario sensitivity (which scenario(s) tip the city into trouble).
Paragraph 4: caveats / limitations of the modeling.
Paragraph 5: the most leveraged intervention the council should fund first.

Tone: confident, expert, plain English. Each paragraph is 2-4 sentences.

DATA SOURCES YOU CAN CITE (use these labels verbatim; do NOT invent source names):
- "Scenario inputs (user-defined)" — city, FSA, scenario penetration rates (status: frozen)
- "StatsCan postal FSA geometry" — for the FSA boundary (status: frozen)
- "Readiness-scoring stage (modeled)" — for verdict, pairing scorecard, transformer counts (status: modeled)
- "ECCC HDD18 winter normals + NRCan ccASHP COP curves" — for the load impact (status: frozen)
- "IESO ResLoad evening L2 EV charging shape" — for EV evening peak math (status: frozen)
- For any industry rule of thumb, regulatory framing, or recommendation
  framing, use status: llm with label e.g. "Industry rule of thumb · transformer load growth"."""

        try:
            text, sources = await synthesize_with_citations(
                self,
                system=SYSTEM,
                prompt=prompt,
                max_tokens=1800,
            )
            if text:
                return text.strip(), sources
            raise RuntimeError("synthesis returned empty text")
        except Exception as e:
            self.logger.warning(f"Exec summary failed: {e}")
            return (
                f"Across {len(profiles)} FSA(s) and {len(scenarios)} scenario(s), "
                f"{n_ready} pairings are READY, {n_constrained} CONSTRAINED, and "
                f"{n_blocked} BLOCKED. Headline: {verdict}."
            ), {}
