"""Langflow component: Site Generation Agent."""
from backend.langflow_compat import Component, DataInput, IntInput, Output, Data


class SiteGenerationComponent(Component):
    display_name = "Site Generation Agent"
    description = (
        "Generates feasible candidate sites for a given ISO region using the "
        "FERC interconnect queue, POI expansion, and Claude-designed parcels."
    )
    icon = "map-pin"

    inputs = [
        DataInput(
            name="region_data",
            display_name="Region",
            info="Region data (Data object from Grid Intelligence Agent)",
        ),
        DataInput(
            name="workload_data",
            display_name="Workload",
            info="Workload data (Data object from Grid Intelligence Agent)",
        ),
        IntInput(
            name="n_sites",
            display_name="Site Count",
            value=24,
            info="Number of candidate sites to generate per region",
        ),
    ]

    outputs = [
        Output(display_name="Site Library", name="site_library", method="build_site_library"),
    ]

    model: str | None = None
    # Orchestrator sets this so the agent's substep messages reach the live
    # log. See REPORTS_COHESION.md §11.
    progress_callback = None

    async def build_site_library(self) -> Data:
        from backend.agents.site_generation import SiteGenerationAgent
        from backend.models.workload import Region, Workload

        agent = SiteGenerationAgent(model=getattr(self, "model", None))
        region = Region.model_validate(self.region_data.data)
        workload = Workload.model_validate(self.workload_data.data)
        library = await agent.generate_candidates(
            region=region,
            workload=workload,
            n_sites=self.n_sites,
            progress_callback=getattr(self, "progress_callback", None),
        )
        return Data(data=library.model_dump(mode="json"))
