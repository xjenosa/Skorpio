"""
Stage 4 of Neighborhood Electrification Readiness — multi-dimensional score.

Scores each (FSA × scenario) pair on four axes:
  - Grid:           transformer headroom + new MW vs incremental capacity
  - Building:       housing stock suitability + panel upgrade burden
  - Affordability:  income vs estimated household upgrade cost
  - Policy:         provincial rebate + code support (province-level constant)
"""
import asyncio

from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.models.electrification import (
    AdoptionScenario,
    NeighborhoodLoadImpact,
    NeighborhoodProfile,
    ReadinessScore,
)


PROVINCE_POLICY_SCORE = {
    "QC": 0.85,    # Hydro-Québec rebates + ENERGY STAR Cool Smart program
    "BC": 0.80,    # CleanBC: rich rebates, mandatory step code path
    "ON": 0.55,    # Greener Homes mostly federal; provincial support thin
    "AB": 0.40,    # Limited provincial program; federal-only effectively
    "NS": 0.65,    # Efficiency Nova Scotia rebates
    "NB": 0.55,
    "MB": 0.50,
    "SK": 0.40,
    "PE": 0.65,
    "NL": 0.50,
}

UPGRADE_COST_BY_DWELLING_CAD = {
    "single_detached": 18_000.0,    # ccASHP + electrical service upgrade
    "semi_detached": 15_000.0,
    "row": 13_000.0,
    "apartment_low_rise": 9_000.0,
    "apartment_high_rise": 7_000.0,
    "other": 13_000.0,
}


def _avg_upgrade_cost(profile: NeighborhoodProfile) -> float:
    mix = profile.dwelling_mix
    return (
        mix.single_detached * UPGRADE_COST_BY_DWELLING_CAD["single_detached"]
        + mix.semi_detached * UPGRADE_COST_BY_DWELLING_CAD["semi_detached"]
        + mix.row * UPGRADE_COST_BY_DWELLING_CAD["row"]
        + mix.apartment_low_rise * UPGRADE_COST_BY_DWELLING_CAD["apartment_low_rise"]
        + mix.apartment_high_rise * UPGRADE_COST_BY_DWELLING_CAD["apartment_high_rise"]
        + mix.other * UPGRADE_COST_BY_DWELLING_CAD["other"]
    )


def _grid_score(impact: NeighborhoodLoadImpact, profile: NeighborhoodProfile) -> float:
    """1.0 = no transformer overloads. Drops as overload count grows."""
    n_xfmrs = max(1, profile.households // 40)
    overload_pct = impact.transformer_overload_count / n_xfmrs
    return max(0.0, 1.0 - overload_pct * 1.5)


def _building_score(impact: NeighborhoodLoadImpact, profile: NeighborhoodProfile) -> float:
    """High = low panel-upgrade burden + dwelling stock that suits HPs (more SFD)."""
    panel_penalty = impact.panel_upgrade_household_pct * 0.8
    sfd_share = profile.dwelling_mix.single_detached + profile.dwelling_mix.semi_detached
    suit_bonus = 0.20 * sfd_share
    base = 0.85 - panel_penalty + suit_bonus
    return max(0.0, min(1.0, base))


def _affordability_score(profile: NeighborhoodProfile, scenario: AdoptionScenario) -> float:
    avg_cost = _avg_upgrade_cost(profile) * max(scenario.heat_pump_conversion_pct, 0.0)
    if avg_cost <= 0:
        return 1.0
    cost_to_income = avg_cost / max(1.0, profile.median_household_income_cad)
    # 0.05 → 1.0, 0.20 → 0.4, 0.40 → 0.0
    return max(0.0, 1.0 - cost_to_income * 2.5)


def _policy_score(province: str) -> float:
    return PROVINCE_POLICY_SCORE.get(province, 0.50)


SYSTEM = """You are a grid planner explaining electrification readiness scores
to a municipal council. Be specific and numeric. Two short sentences max.""" + GROUNDING_RULES


# Cap on concurrent rationale Claude calls. 5 FSAs × 3 scenarios = 15 calls;
# this throttles them to 4 in-flight to stay under Opus output-TPM limits.
_RATIONALE_SEMAPHORE = asyncio.Semaphore(4)


class ReadinessScoringAgent(BaseAgent):
    async def score_all(
        self,
        profiles: list[NeighborhoodProfile],
        scenarios: list[AdoptionScenario],
        impacts: dict[tuple[str, str], NeighborhoodLoadImpact],
        progress_callback=None,
        progress_offset_pct: int = 60,
    ) -> dict[tuple[str, str], ReadinessScore]:
        """Score each (FSA × scenario) and rank within each scenario."""
        scores: dict[tuple[str, str], ReadinessScore] = {}

        # Phase 1 — compute numeric scores + verdicts + blockers synchronously.
        # These are pure functions, no Claude. Build a task list for phase 2.
        pending = []
        for prof in profiles:
            for sc in scenarios:
                impact = impacts.get((prof.fsa, sc.name))
                if impact is None:
                    continue
                grid = _grid_score(impact, prof)
                building = _building_score(impact, prof)
                affordability = _affordability_score(prof, sc)
                policy = _policy_score(prof.province)
                # Weight grid heaviest — it's the binding constraint at the
                # neighborhood scale.
                overall = grid * 0.40 + building * 0.25 + affordability * 0.20 + policy * 0.15

                blockers: list[str] = []
                if grid < 0.50:
                    blockers.append(f"{impact.transformer_overload_count} local transformers projected to overload")
                if building < 0.55:
                    pct = int(impact.panel_upgrade_household_pct * 100)
                    blockers.append(f"{pct}% of homes need panel upgrade (>100A service)")
                if affordability < 0.50:
                    blockers.append("Average household upgrade cost exceeds 20% of median income")
                if policy < 0.55:
                    blockers.append(f"Provincial rebate + code support is thin in {prof.province}")

                if overall >= 0.70:
                    verdict = "READY"
                elif overall >= 0.45:
                    verdict = "CONSTRAINED"
                else:
                    verdict = "BLOCKED"

                pending.append((prof, sc, impact, grid, building, affordability, policy, overall, verdict, blockers))

        if progress_callback and pending:
            await progress_callback(
                f"Generating rationales for {len(pending)} (FSA × scenario) pairs in parallel...",
                progress_offset_pct + 5,
            )

        # Phase 2 — gather rationale Claude calls under the global semaphore.
        async def _rationale(prof, sc, impact, overall, verdict, blockers):
            async with _RATIONALE_SEMAPHORE:
                return await self._explain(prof, sc, impact, overall, verdict, blockers)

        rationales = await asyncio.gather(*(
            _rationale(prof, sc, impact, overall, verdict, blockers)
            for prof, sc, impact, _, _, _, _, overall, verdict, blockers in pending
        ))

        # Phase 3 — assemble the ReadinessScore objects.
        for entry, rationale in zip(pending, rationales):
            prof, sc, _impact, grid, building, affordability, policy, overall, verdict, blockers = entry
            scores[(prof.fsa, sc.name)] = ReadinessScore(
                fsa=prof.fsa,
                scenario_name=sc.name,
                grid_score=round(grid, 3),
                building_score=round(building, 3),
                affordability_score=round(affordability, 3),
                policy_score=round(policy, 3),
                overall_score=round(overall, 3),
                verdict=verdict,
                blockers=blockers,
                rationale=rationale,
            )

        if progress_callback and pending:
            await progress_callback(
                f"Scored {len(pending)} (FSA × scenario) pairs",
                progress_offset_pct + 20,
            )

        # Rank within each scenario by overall_score desc
        for sc in scenarios:
            ranked = sorted(
                [s for k, s in scores.items() if k[1] == sc.name],
                key=lambda s: s.overall_score, reverse=True,
            )
            for r, s in enumerate(ranked, start=1):
                s.rank = r
        return scores

    async def _explain(
        self,
        profile: NeighborhoodProfile,
        scenario: AdoptionScenario,
        impact: NeighborhoodLoadImpact,
        overall: float,
        verdict: str,
        blockers: list[str],
    ) -> str:
        prompt = f"""Explain this electrification readiness verdict in two sentences:

FSA: {profile.label}
Scenario: {scenario.label}
Verdict: {verdict} ({overall:.2f}/1.0)
Incremental peak MW: {impact.incremental_peak_mw:.1f}
Local transformers projected to overload: {impact.transformer_overload_count}
Panel upgrades needed: {int(impact.panel_upgrade_household_pct * 100)}% of homes
Blockers: {'; '.join(blockers) if blockers else 'none'}

Be concrete and numeric. No markdown, just plain text."""
        try:
            return (await self.ask_claude(SYSTEM, prompt, max_tokens=180)).strip()
        except Exception as e:
            self.logger.warning(f"Readiness explain failed: {e}")
            return (
                f"{verdict}. Incremental peak {impact.incremental_peak_mw:.1f} MW; "
                f"{impact.transformer_overload_count} transformer(s) overload."
            )
