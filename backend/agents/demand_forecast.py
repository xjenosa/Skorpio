"""
Stage 3 of Expansion Planner — annual demand growth projection.
Pure compute (no Claude calls).
"""
from backend.agents.base_agent import BaseAgent
from backend.grid.expansion_modeling import forecast_demand
from backend.models.expansion import DemandForecast, ExpansionSpec, OperatorFootprint


class DemandForecastAgent(BaseAgent):
    async def forecast(
        self,
        spec: ExpansionSpec,
        footprint: OperatorFootprint,
        progress_callback=None,
    ) -> DemandForecast:
        if progress_callback:
            await progress_callback(
                f"Projecting demand under {spec.workload_mix.replace('_', ' ')} workload mix...",
                32,
            )
        f = forecast_demand(spec, footprint)
        if progress_callback:
            await progress_callback(
                f"Year-{spec.horizon_years} demand: {f.target_mw_year_n:.0f} MW "
                f"(+{f.target_mw_year_n - f.baseline_mw:.0f} MW vs baseline @ {f.annual_growth_rate*100:.0f}% CAGR)",
                42,
            )
        return f
