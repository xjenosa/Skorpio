"""
Stage 4 of Investment Optimizer — generate candidate hardening projects per
at-risk asset, then run a greedy ROI-ordered knapsack to fit them inside the
budget.

The candidate menu is generated deterministically (project templates ×
asset types × hazard exposure), but Claude is used to write the natural-
language rationale for each project so the output reads like a planner
wrote it.
"""
import asyncio
import uuid

from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.models.investment import (
    ClimateRiskProfile,
    FundedProject,
    GridAsset,
    InvestmentSpec,
    UpgradeProject,
)


# ── Project templates: per asset_type, per dominant hazard ───────────── #
#
# capex_factor = fraction of asset.replacement_cost_cad
# annual_relief_factor = fraction of asset.aggregate_annual_loss reduced
# protected_factor = fraction of asset.customers_served protected


_TEMPLATES: list[dict] = [
    # Transmission lines
    {"asset_type": "transmission_line", "hazards": ["ice_storm", "wind"],
     "category": "vegetation_mgmt", "title_prefix": "Aggressive right-of-way clearing on",
     "capex_factor": 0.04, "annual_relief_factor": 0.35, "protected_factor": 1.0,
     "deployment_months": 8, "opex_factor": 0.005,
     "rationale_seed": "Tree-fall is the dominant ice-storm cascade trigger; trimming + selective removal cuts dispatch-side outages."},
    {"asset_type": "transmission_line", "hazards": ["ice_storm", "wind"],
     "category": "switchgear",
     "title_prefix": "Replace OCBs with vacuum breakers on",
     "capex_factor": 0.10, "annual_relief_factor": 0.25, "protected_factor": 0.8,
     "deployment_months": 14, "opex_factor": 0.002,
     "rationale_seed": "Faster fault isolation limits cascade extent and reduces customer-hours lost during structural failures."},
    {"asset_type": "transmission_line", "hazards": ["wildfire"],
     "category": "undergrounding",
     "title_prefix": "Targeted undergrounding of high-WUI sections on",
     "capex_factor": 0.45, "annual_relief_factor": 0.90, "protected_factor": 1.0,
     "deployment_months": 36, "opex_factor": 0.003,
     "rationale_seed": "Removes the ignition vector entirely in the wildland-urban interface segments."},
    # Substations
    {"asset_type": "substation", "hazards": ["flood", "heat_wave"],
     "category": "reconductoring",
     "title_prefix": "Cooling + waterproofing retrofit at",
     "capex_factor": 0.08, "annual_relief_factor": 0.45, "protected_factor": 1.0,
     "deployment_months": 12, "opex_factor": 0.004,
     "rationale_seed": "Upgrade transformer cooling and seal foundations against riverine + stormwater inflow."},
    {"asset_type": "substation", "hazards": ["heat_wave"],
     "category": "transformer_upgrade",
     "title_prefix": "Replace aged power transformers at",
     "capex_factor": 0.25, "annual_relief_factor": 0.55, "protected_factor": 0.9,
     "deployment_months": 18, "opex_factor": 0.002,
     "rationale_seed": "Modern units carry higher thermal ratings and survive summer peak overload without forced outage."},
    {"asset_type": "substation", "hazards": ["ice_storm", "wind"],
     "category": "battery_storage",
     "title_prefix": "Co-locate 10 MW / 40 MWh battery at",
     "capex_factor": 0.15, "annual_relief_factor": 0.30, "protected_factor": 0.7,
     "deployment_months": 18, "opex_factor": 0.012,
     "rationale_seed": "Battery rides through transient line outages and provides black-start support after major storms."},
    # Feeders
    {"asset_type": "feeder", "hazards": ["ice_storm", "wind"],
     "category": "vegetation_mgmt",
     "title_prefix": "Cycle-cut ROW management on",
     "capex_factor": 0.06, "annual_relief_factor": 0.40, "protected_factor": 1.0,
     "deployment_months": 6, "opex_factor": 0.008,
     "rationale_seed": "Cycle clearing is the cheapest customer-hour avoided dollar in overhead distribution."},
    {"asset_type": "feeder", "hazards": ["ice_storm", "wind"],
     "category": "undergrounding",
     "title_prefix": "Selective undergrounding of",
     "capex_factor": 0.55, "annual_relief_factor": 0.85, "protected_factor": 0.9,
     "deployment_months": 30, "opex_factor": 0.001,
     "rationale_seed": "Permanently removes overhead exposure; ROI strongest where customer density is high."},
    {"asset_type": "feeder", "hazards": ["wildfire"],
     "category": "switchgear",
     "title_prefix": "Fast-trip protection + fire-safe reclosers on",
     "capex_factor": 0.12, "annual_relief_factor": 0.50, "protected_factor": 0.8,
     "deployment_months": 10, "opex_factor": 0.003,
     "rationale_seed": "Disables auto-reclose during red-flag conditions; matches BC Hydro fire-safe protection scheme."},
    # Transformers
    {"asset_type": "transformer", "hazards": ["heat_wave"],
     "category": "transformer_upgrade",
     "title_prefix": "Bulk replacement of past-life padmounts in",
     "capex_factor": 0.65, "annual_relief_factor": 0.80, "protected_factor": 1.0,
     "deployment_months": 12, "opex_factor": 0.002,
     "rationale_seed": "Aged units fail under summer thermal overload; bulk replacement amortizes truck-roll costs."},
    {"asset_type": "transformer", "hazards": ["flood"],
     "category": "switchgear",
     "title_prefix": "Elevate + waterproof padmount enclosures in",
     "capex_factor": 0.20, "annual_relief_factor": 0.45, "protected_factor": 0.9,
     "deployment_months": 9, "opex_factor": 0.001,
     "rationale_seed": "Raises pads above 100-year flood line and seals enclosures against ingress."},
]


def _dominant_hazard(profile: ClimateRiskProfile) -> str:
    if not profile.hazard_exposures:
        return "ice_storm"
    return max(profile.hazard_exposures, key=lambda h: h.annual_probability * h.expected_loss_cad).hazard


SYSTEM = """You are a utility planner writing a one-sentence justification
for a grid hardening project. Be specific, numeric, and confident.""" + GROUNDING_RULES


# Worst case: 20-50 assets × 2-3 templates = up to ~150 sequential Claude calls.
# Gathering them all at once would obliterate any rate limit, so we cap at 4
# in-flight to stay safe on Opus tier 1 while still getting a big speedup.
_RATIONALE_SEMAPHORE = asyncio.Semaphore(4)


class PortfolioOptimizationAgent(BaseAgent):
    async def build_and_select(
        self,
        spec: InvestmentSpec,
        assets: list[GridAsset],
        risk_profiles: list[ClimateRiskProfile],
        progress_callback=None,
        progress_offset_pct: int = 55,
    ) -> tuple[list[UpgradeProject], list[FundedProject], list[UpgradeProject]]:
        """Returns (full_candidate_menu, funded, unfunded) lists."""
        if progress_callback:
            await progress_callback("Generating candidate hardening projects...", progress_offset_pct)

        profile_by_id = {p.asset_id: p for p in risk_profiles}

        # Phase 1 — enumerate every (asset, template) pair synchronously plus
        # pre-compute numeric fields (capex, relief). No Claude in this loop.
        pending: list[tuple] = []  # (asset, tpl, prof, capex, annual_relief)
        for asset in assets:
            prof = profile_by_id.get(asset.asset_id)
            if prof is None:
                continue
            dom = _dominant_hazard(prof)
            applicable = [t for t in _TEMPLATES if t["asset_type"] == asset.asset_type and dom in t["hazards"]]
            if not applicable:
                applicable = [t for t in _TEMPLATES if t["asset_type"] == asset.asset_type][:1]
            for tpl in applicable:
                capex = asset.replacement_cost_cad * tpl["capex_factor"]
                annual_relief = prof.aggregate_annual_loss_cad * tpl["annual_relief_factor"]
                if capex <= 0 or annual_relief <= 0:
                    continue
                pending.append((asset, tpl, prof, capex, annual_relief))

        if progress_callback and pending:
            await progress_callback(
                f"Generating rationales for {len(pending)} candidate projects in parallel...",
                progress_offset_pct + 6,
            )

        # Phase 2 — gather rationale Claude calls under the global semaphore.
        async def _one_rationale(asset, tpl, prof, annual_relief) -> str:
            async with _RATIONALE_SEMAPHORE:
                return await self._rationale(asset, tpl, prof, annual_relief)

        rationales = await asyncio.gather(*(
            _one_rationale(asset, tpl, prof, annual_relief)
            for asset, tpl, prof, _capex, annual_relief in pending
        ))

        # Phase 3 — assemble the UpgradeProject objects.
        candidates: list[UpgradeProject] = []
        for (asset, tpl, _prof, capex, annual_relief), rationale in zip(pending, rationales):
            candidates.append(UpgradeProject(
                project_id=f"PRJ-{uuid.uuid4().hex[:8]}",
                title=f"{tpl['title_prefix']} {asset.name}",
                category=tpl["category"],
                target_assets=[asset.asset_id],
                capex_cad=round(capex, 0),
                annual_opex_cad=round(capex * tpl["opex_factor"], 0),
                risk_reduction_cad_per_year=round(annual_relief, 0),
                customers_protected=int(asset.customers_served * tpl["protected_factor"]),
                deployment_months=int(tpl["deployment_months"]),
                hazards_addressed=list(tpl["hazards"]),
                rationale=rationale,
            ))

        if progress_callback:
            await progress_callback(
                f"Ranking {len(candidates)} projects by lifetime ROI...",
                progress_offset_pct + 14,
            )

        # ── Greedy knapsack on ROI ──────────────────────────────────── #
        # ROI ratio = (annual_relief × horizon_years) / capex
        # Sort high → low; fund until budget exhausted; rest go to unfunded.
        #
        # One project per asset. Several templates can apply to the same
        # asset (e.g. on a feeder under ice-storm/wind exposure both
        # vegetation_mgmt @ 40% relief and undergrounding @ 85% relief
        # are eligible). Without dedup, both can fund and the downstream
        # totals claim 125% of the asset's annual loss avoided and count
        # the same customers twice. Utility capex committees don't
        # double-harden the same asset, so pick the highest-ROI project
        # per asset and move the alternates to unfunded.
        def roi(p: UpgradeProject) -> float:
            return (p.risk_reduction_cad_per_year * spec.horizon_years) / max(1.0, p.capex_cad)

        ranked = sorted(candidates, key=roi, reverse=True)
        funded: list[FundedProject] = []
        unfunded: list[UpgradeProject] = []
        spent = 0.0
        rank_idx = 1
        funded_assets: set[str] = set()
        for project in ranked:
            asset_key = project.target_assets[0] if project.target_assets else None
            if asset_key and asset_key in funded_assets:
                unfunded.append(project)
                continue
            if spent + project.capex_cad <= spec.budget_cad:
                spent += project.capex_cad
                funded.append(FundedProject(
                    project=project,
                    cumulative_capex_cad=round(spent, 0),
                    roi_ratio=round(roi(project), 2),
                    rank=rank_idx,
                ))
                rank_idx += 1
                if asset_key:
                    funded_assets.add(asset_key)
            else:
                unfunded.append(project)

        if progress_callback:
            await progress_callback(
                f"Selected {len(funded)} project(s) within ${spec.budget_cad/1e6:.0f}M budget",
                progress_offset_pct + 20,
            )
        return candidates, funded, unfunded

    async def _rationale(self, asset, tpl: dict, profile: ClimateRiskProfile, annual_relief: float) -> str:
        prompt = f"""Write a one-sentence justification for this hardening project:

Asset: {asset.name} ({asset.asset_type}, age {asset.age_years}y)
Project: {tpl['title_prefix']} {asset.name}
Category: {tpl['category']}
Dominant hazard: {profile.hazard_exposures[0].hazard if profile.hazard_exposures else 'mixed'}
Expected annual loss avoided: ${annual_relief/1e6:.1f}M
Seed: {tpl['rationale_seed']}

Be concrete and numeric. Plain text. One sentence."""
        try:
            return (await self.ask_claude(SYSTEM, prompt, max_tokens=140)).strip()
        except Exception as e:
            self.logger.warning(f"Project rationale failed: {e}")
            return tpl["rationale_seed"]
