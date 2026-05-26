"""Langflow component: Placement Scoring Agent."""
from backend.langflow_compat import Component, DataInput, IntInput, Output, Data


class PlacementScoringComponent(Component):
    display_name = "Placement Scoring Agent"
    description = (
        "Scores each candidate site against the workload + region grid state. "
        "Produces LCOE, uptime band and a GeoJSON plan for each site."
    )
    icon = "bar-chart-3"
    # Langflow compat stubs do not hydrate input defaults onto instance attrs.
    top_n = 20
    model: str | None = None
    # Orchestrator sets this so the agent's substep messages reach the live
    # log. See REPORTS_COHESION.md §11.
    progress_callback = None

    inputs = [
        DataInput(
            name="region_data",
            display_name="Region",
            info="Region data (Data object from Grid Intelligence Agent)",
        ),
        DataInput(
            name="site_library",
            display_name="Site Library",
            info="Site library (Data object from Site Generation Agent)",
        ),
        DataInput(
            name="workload_data",
            display_name="Workload",
            info="Workload data (Data object from Grid Intelligence Agent)",
        ),
        IntInput(
            name="top_n",
            display_name="Top N Results",
            value=20,
            info="Number of top-ranked sites to keep",
        ),
    ]

    outputs = [
        Output(display_name="Placement Scores", name="placement_scores", method="build_placement_scores"),
    ]

    async def build_placement_scores(self) -> Data:
        from backend.agents.placement_scoring import PlacementScoringAgent
        from backend.models.workload import Region, Workload
        from backend.models.site import SiteLibrary

        agent = PlacementScoringAgent(model=getattr(self, "model", None))
        region = Region.model_validate(self.region_data.data)
        library = SiteLibrary.model_validate(self.site_library.data)
        workload = Workload.model_validate(self.workload_data.data)
        top_n = max(1, int(getattr(self, "top_n", 20) or 20))
        results = await agent.score_sites(
            region=region,
            library=library,
            workload=workload,
            top_n=top_n,
            progress_callback=getattr(self, "progress_callback", None),
        )
        return Data(data={
            "region_iso": region.iso_code,
            "results": [r.model_dump(mode="json") for r in results],
        })
