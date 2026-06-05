"""
Stage 5 of Investment Optimizer — final InvestmentPlan.
"""
from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.models.investment import (
    ClimateRiskProfile,
    FundedProject,
    GridAsset,
    InvestmentPlan,
    InvestmentSpec,
    UpgradeProject,
)
from backend.models.report import CitationSource
from backend.utils.citations import synthesize_with_citations
from backend.utils.reconciliation import reconcile


SYSTEM = """You are a senior utility planner writing the executive summary
of a climate-adapted capital investment plan for the utility's board. Be
specific, numeric, and confident. No bullet lists, flowing prose. Avoid
em dashes in the prose; use commas, periods, or parentheses.""" + GROUNDING_RULES


# Utility → representative Census Subdivision name used when calling
# ArcGIS GeoEnrichment for the Investment report's sources citation.
# Each entry is the most demographically representative single
# municipality for the utility's primary service territory. Add new
# rows as new utilities ship in the demo.
_UTILITY_PRIMARY_CITY = {
    "Hydro One":             "Toronto",
    "Toronto Hydro":         "Toronto",
    "Alectra":               "Mississauga",
    "Alectra Utilities":     "Mississauga",
    "Hydro Ottawa":          "Ottawa",
    "EPCOR":                 "Edmonton",
    "ENMAX":                 "Calgary",
    "BC Hydro":              "Vancouver",
    "Hydro-Québec":          "Montreal",
    "Hydro-Quebec":          "Montreal",
    "Manitoba Hydro":        "Winnipeg",
    "Nova Scotia Power":     "Halifax",
}


def _primary_city_for_utility(utility: str) -> str | None:
    """Best-fit single municipality for ArcGIS enrichment given a utility name."""
    if not utility:
        return None
    direct = _UTILITY_PRIMARY_CITY.get(utility.strip())
    if direct:
        return direct
    # Loose suffix match — "Hydro One Networks Inc" → "Hydro One".
    for key, city in _UTILITY_PRIMARY_CITY.items():
        if utility.strip().lower().startswith(key.lower()):
            return city
    return None


class InvestmentSynthesisAgent(BaseAgent):
    async def synthesize(
        self,
        *,
        job_id: str,
        spec: InvestmentSpec,
        assets: list[GridAsset],
        is_synthesized_catalog: bool,
        risk_profiles: list[ClimateRiskProfile],
        candidate_projects: list[UpgradeProject],
        funded: list[FundedProject],
        unfunded: list[UpgradeProject],
        hazard_sources: list[str] | None = None,
        progress_callback=None,
    ) -> InvestmentPlan:
        if progress_callback:
            await progress_callback("Composing investment plan...", 88)

        total_capex = sum(f.project.capex_cad for f in funded)
        total_annual_relief = sum(f.project.risk_reduction_cad_per_year for f in funded)
        portfolio_roi = (total_annual_relief * spec.horizon_years) / max(1.0, total_capex)
        customers_protected = sum(f.project.customers_protected for f in funded)

        summary, citation_sources = await self._exec_summary(spec, assets, funded, unfunded, total_capex, total_annual_relief)

        # Pattern 3 — reconcile Claude's exec summary against portfolio facts.
        # Drifted budget, customer count, and capex figures are rewritten to
        # match the actual computed values. The regex-based number rewriter
        # operates on text including inside [[sN|...]] markers, so any number
        # corrected here is also corrected within its citation wrapper.
        recon_facts = {
            "budget_cad": spec.budget_cad,
            "customers_protected": float(customers_protected),
            "total_capex_committed_cad": total_capex,
        }
        summary = reconcile(summary, recon_facts).corrected_text

        limitations = [
            "Climate hazard frequencies use provincial base rates; sub-provincial variation (urban heat island, micro-flooding) is not modeled.",
            "Asset replacement costs are estimates; real bids will vary ±25%.",
            "Optimizer is greedy on ROI only and does not enforce geographic balance or political constraints.",
            "Reliability metric is customer-hours-lost per event; does not weight medical or industrial criticality.",
        ]
        if is_synthesized_catalog:
            limitations.append(
                f"Asset catalog for {spec.utility} was synthesized from province-average templates because we don't have a calibrated registry for this utility."
            )
        # If any Claude call (per-project rationales or exec summary) hit the
        # max_tokens cap on this agent, surface it. See base_agent._truncation_count.
        if self.had_truncation():
            limitations.append(
                f"{self._truncation_count} Claude response(s) hit the max_tokens "
                "cap, so executive summary or per-project rationale may be incomplete. "
                "Raise the cap in REPORTS_COHESION.md §8b and re-run."
            )

        # ArcGIS enrichment — surface real Census Subdivision demographics
        # for the cities served by the top funded projects. Each unique
        # city resolved becomes one source citation, so the Investment
        # report's sources block explicitly shows the Esri pull when
        # credentials are configured. Asset.name encodes the city in
        # most templates (e.g. "Erin Mills MS substation" — Mississauga
        # area). Falls through silently when ArcGIS isn't configured.
        # Seeded with any hazard-layer citations the climate_risk
        # agent emitted (NRCan flood + wildfire layers, via Esri
        # Living Atlas).
        arcgis_sources: list[str] = list(hazard_sources or [])
        try:
            from backend.services.arcgis_enrichment import enrich_city, is_configured as _arcgis_ok
            if _arcgis_ok():
                # Pull a small set of demo cities relevant to the funded
                # projects. Best-effort: we lean on the spec.utility's
                # primary service area rather than reverse-geocoding each
                # asset (which would burn credits). Hydro One / Alectra /
                # Toronto Hydro all anchor to the GTA — Mississauga is a
                # representative CSD for the demo.
                primary_city = _primary_city_for_utility(spec.utility)
                if primary_city:
                    city_data = await enrich_city(primary_city)
                    if city_data:
                        arcgis_sources.append(
                            "ArcGIS GeoEnrichment (Esri Canada): "
                            f"{city_data.get('city_name', primary_city)}: "
                            f"{city_data.get('households', 0):,} households, "
                            f"population {city_data.get('population', 0):,}"
                        )
        except Exception as e:
            self.logger.debug(f"ArcGIS investment enrichment skipped: {e}")

        plan = InvestmentPlan(
            job_id=job_id,
            spec=spec,
            assets=assets,
            risk_profiles=risk_profiles,
            candidate_projects=candidate_projects,
            funded_projects=funded,
            unfunded_projects=unfunded,
            total_capex_committed_cad=round(total_capex, 0),
            total_annual_loss_avoided_cad=round(total_annual_relief, 0),
            portfolio_roi_ratio=round(portfolio_roi, 2),
            customers_protected=int(customers_protected),
            executive_summary=summary,
            citation_sources=citation_sources,
            sources=arcgis_sources,
            methodology_notes=(
                "Per-asset climate risk uses provincial hazard base rates from ECCC CCCS "
                "scaled by IBC/CatIQ insurance loss share and asset-type susceptibility. "
                "Climate scaling: 1.0× by 2025, 1.15× by 2030, 1.30× by 2035, 1.60× by 2050. "
                "Asset age multiplier: 0.7× (<20y) → 1.6× (>60y). Project menu generated "
                "from 11 hardening templates × asset type × dominant hazard. Selection "
                "is a greedy ROI-ordered knapsack with horizon = "
                f"{spec.horizon_years}y."
            ),
            safety_flags=self._safety_flags(risk_profiles, funded, unfunded),
            limitations=limitations,
        )
        return plan

    def _safety_flags(
        self,
        profiles: list[ClimateRiskProfile],
        funded: list[FundedProject],
        unfunded: list[UpgradeProject],
    ) -> list[str]:
        flags: list[str] = []
        critical = [p for p in profiles if p.risk_tier == "critical"]
        if critical:
            unfunded_critical = {p.target_assets[0] for p in unfunded if p.target_assets}
            crit_unfunded = [p for p in critical if p.asset_id in unfunded_critical]
            if crit_unfunded:
                flags.append(
                    f"{len(crit_unfunded)} critical-tier asset(s) have no hardening project funded. "
                    "Budget shortfall, or no high-ROI candidate was available."
                )
        if not funded:
            flags.append("Budget is too small to fund any project at projected ROI; consider raising the floor or extending the horizon.")
        return flags

    async def _exec_summary(
        self,
        spec: InvestmentSpec,
        assets: list[GridAsset],
        funded: list[FundedProject],
        unfunded: list[UpgradeProject],
        total_capex: float,
        total_annual_relief: float,
    ) -> tuple[str, dict[str, CitationSource]]:
        if not funded:
            return (
                f"No projects met the ROI threshold within ${spec.budget_cad/1e6:.0f}M for {spec.utility}. "
                "Either the budget is too small or the candidate menu needs deeper exposure modeling."
            ), {}
        top_titles = "; ".join(f.project.title for f in funded[:3])
        prompt = f"""Write a 4-5 paragraph executive summary for a utility board.

Format: open with `# Executive Summary: <one-line topic>`. Each paragraph
begins with `**<2-5 word bold title>**` on its own line, then a blank line,
then the prose. Separate paragraphs with blank lines only. Do NOT insert
`---` or any horizontal-rule dividers, and do NOT use markdown tables
(the renderer does not display them). Avoid em dashes anywhere in the
prose; use commas, periods, or parentheses.

Utility: {spec.utility} ({spec.province})
Budget: ${spec.budget_cad/1e6:.0f}M over {spec.horizon_years} years
Target year: {spec.target_year}

Funded projects: {len(funded)}
Unfunded but recommended: {len(unfunded)}
Capex committed: ${total_capex/1e6:.0f}M
Avoided annual loss: ${total_annual_relief/1e6:.1f}M/yr
Lifetime ROI: {(total_annual_relief * spec.horizon_years) / max(1.0, total_capex):.2f}×

Top three funded:
{top_titles}

Paragraph 1: the verdict (does the budget cover the critical risk?) and the
headline numbers.
Paragraph 2: which specific funded projects matter most and why.
Paragraph 3: what's still unprotected (biggest unfunded asset / hazard) and
how that translates to residual customer-hours-lost.
Paragraph 4: caveats / limitations of the analysis.
Paragraph 5: the one strategic move the board should make in the next
budget cycle.

Tone: confident, expert, plain English. Write for an executive who will skim.
Each paragraph is 2-4 sentences.

DATA SOURCES YOU CAN CITE (use these labels verbatim in citation_sources;
do NOT invent source names):
- "Scenario inputs (user-defined)" — for the budget, horizon, target year (status: frozen)
- "Hand-curated asset catalog · {{utility}}" — for asset names, ratings, ages (status: frozen)
- "Per-asset NPV optimizer (modeled)" — for funded selection, ROI, avoided loss (status: modeled)
- "Climate hazard model (modeled)" — for per-asset loss probabilities (status: modeled)
- "ECCC CCCS hazard base rates" — for provincial flood/fire/storm frequencies (status: frozen)
- "IBC/CatIQ insurance loss share" — for hazard loss multipliers (status: frozen)
- For any industry pattern or rule of thumb you mention, status: llm,
  label e.g. "Industry pattern · vegetation outages"."""
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
                f"Funded {len(funded)} of {len(funded) + len(unfunded)} candidate projects "
                f"with ${total_capex/1e6:.0f}M of ${spec.budget_cad/1e6:.0f}M budget. "
                f"Avoided loss: ${total_annual_relief/1e6:.1f}M/year."
            ), {}
