"""
Stage 3 of Neighborhood Electrification Readiness — model the per-FSA load
impact of each adoption scenario. Pure simulation, no Claude calls.
"""
from backend.agents.base_agent import BaseAgent
from backend.grid.electrification_modeling import model_load_impact
from backend.models.electrification import (
    AdoptionScenario,
    NeighborhoodLoadImpact,
    NeighborhoodProfile,
)


class AdoptionModelingAgent(BaseAgent):
    async def model_all(
        self,
        profiles: list[NeighborhoodProfile],
        scenarios: list[AdoptionScenario],
        progress_callback=None,
        progress_offset_pct: int = 30,
    ) -> dict[tuple[str, str], NeighborhoodLoadImpact]:
        """
        Returns a dict keyed by (fsa, scenario_name) → NeighborhoodLoadImpact.
        """
        out: dict[tuple[str, str], NeighborhoodLoadImpact] = {}
        n = max(1, len(profiles) * len(scenarios))
        i = 0
        for prof in profiles:
            for sc in scenarios:
                impact = model_load_impact(prof, sc)
                out[(prof.fsa, sc.name)] = impact
                i += 1
                if progress_callback:
                    pct = progress_offset_pct + int((i / n) * 25)
                    await progress_callback(
                        f"Modeled {prof.fsa} · {sc.label} → +{impact.incremental_peak_mw:.1f} MW peak",
                        pct,
                    )
        return out
