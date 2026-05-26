"""Langflow component: Grid Intelligence Agent."""
from backend.langflow_compat import Component, IntInput, MessageTextInput, Output, Data


class GridIntelligenceComponent(Component):
    display_name = "Grid Intelligence Agent"
    description = (
        "Maps a compute-workload placement query to validated, operationally-"
        "feasible ISO regions using Claude AI, EIA, OpenEI and ISO LMP feeds."
    )
    icon = "zap"

    inputs = [
        MessageTextInput(
            name="workload_query",
            display_name="Workload Query",
            info="Natural-language workload spec (e.g. 'training cluster Q3, 42 MW, < 35ms')",
        ),
        IntInput(
            name="max_regions",
            display_name="Max Regions",
            value=3,
            info="Maximum number of ISO regions to identify (1–5)",
        ),
    ]

    outputs = [
        Output(display_name="Workload Data", name="workload_data", method="build_workload_data"),
    ]

    # Set by the orchestrator before run; falls back to env default in BaseAgent.
    model: str | None = None
    # Set by the orchestrator before run to forward agent-internal substep
    # progress lines into the same live SSE stream the other 4 pipelines use.
    # See REPORTS_COHESION.md §11 — without this, agent progress_callback()
    # calls are dead code for the Siting pipeline.
    progress_callback = None

    async def build_workload_data(self) -> Data:
        from backend.agents.grid_intelligence import GridIntelligenceAgent

        agent = GridIntelligenceAgent(model=getattr(self, "model", None))
        workload = await agent.discover_regions(
            workload_query=self.workload_query,
            progress_callback=getattr(self, "progress_callback", None),
        )
        return Data(data=workload.model_dump(mode="json"))
