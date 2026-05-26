"""Langflow component: Plan Synthesis Agent."""
from datetime import datetime

from backend.langflow_compat import Component, DataInput, MessageTextInput, Output, Data


class PlanSynthesisComponent(Component):
    display_name = "Plan Synthesis Agent"
    description = (
        "Synthesises all pipeline outputs into a comprehensive SitingPlan: "
        "region insights, Pareto-optimal sites, safety flags and executive summary."
    )
    icon = "file-text"

    inputs = [
        MessageTextInput(
            name="job_id",
            display_name="Job ID",
            info="Pipeline job identifier (UUID string)",
        ),
        DataInput(
            name="workload_data",
            display_name="Workload Data",
            info="Workload + regions (Data from Grid Intelligence Agent)",
        ),
        DataInput(
            name="libraries_data",
            display_name="Site Libraries",
            info='Wrapped libraries: {"libraries": [<SiteLibrary dicts>]}',
        ),
        DataInput(
            name="scoring_data",
            display_name="Scoring Results",
            info='Wrapped scoring: {"results_per_region": {iso_code: [<PlacementScore dicts>]}}',
        ),
        MessageTextInput(
            name="pipeline_start_time",
            display_name="Pipeline Start Time",
            info="ISO-format datetime string (e.g. '2024-01-01T00:00:00')",
        ),
    ]

    outputs = [
        Output(display_name="Siting Plan", name="plan", method="build_plan"),
    ]

    model: str | None = None
    # Orchestrator sets this so the agent's substep messages reach the live
    # log. See REPORTS_COHESION.md §11.
    progress_callback = None

    async def build_plan(self) -> Data:
        from backend.agents.plan_synthesis import PlanSynthesisAgent
        from backend.models.workload import Workload
        from backend.models.site import SiteLibrary
        from backend.models.report import PlacementScore

        agent = PlanSynthesisAgent(model=getattr(self, "model", None))
        workload = Workload.model_validate(self.workload_data.data)
        libraries = [
            SiteLibrary.model_validate(lib)
            for lib in self.libraries_data.data["libraries"]
        ]
        scoring_results_per_region = {
            iso: [PlacementScore.model_validate(r) for r in results]
            for iso, results in self.scoring_data.data["results_per_region"].items()
        }
        start_time = datetime.fromisoformat(self.pipeline_start_time)

        plan = await agent.synthesize(
            job_id=self.job_id,
            workload=workload,
            libraries=libraries,
            scoring_results_per_region=scoring_results_per_region,
            pipeline_start_time=start_time,
            progress_callback=getattr(self, "progress_callback", None),
        )
        return Data(data=plan.model_dump(mode="json"))
