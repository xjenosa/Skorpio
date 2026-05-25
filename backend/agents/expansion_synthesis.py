"""
Stage 5 of Expansion Planner — final ExpansionPlan with phased rollout
schedule, blended carbon, exec summary, methodology, limitations.
"""
from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.models.expansion import (
    DemandForecast,
    ExpansionOption,
    ExpansionPlan,
    ExpansionSpec,
    OperatorFootprint,
    PhasedRollout,
)
from backend.utils.reconciliation import reconcile


SYSTEM = """You are a senior datacenter portfolio planner writing the
executive summary of an expansion plan for the operator's leadership team.
Specific, numeric, confident. No bullet lists, flowing prose. Avoid em
dashes in the prose; use commas, periods, or parentheses.""" + GROUNDING_RULES


def _phase_rollout(funded: list[ExpansionOption], horizon: int) -> list[PhasedRollout]:
    """Spread funded options across the horizon by deployment_months."""
    if not funded:
        return [PhasedRollout(year=y) for y in range(1, horizon + 1)]

    # Earliest-completion-first scheduling. Simple monthly accumulator.
    sorted_funded = sorted(funded, key=lambda o: o.deployment_months)
    rollout: dict[int, PhasedRollout] = {y: PhasedRollout(year=y) for y in range(1, horizon + 1)}
    cumulative_mw = 0.0
    cumulative_cap = 0.0
    months_elapsed = 0
    for opt in sorted_funded:
        months_elapsed = max(months_elapsed, opt.deployment_months)
        commission_year = min(horizon, max(1, (months_elapsed + 11) // 12))
        cumulative_mw += opt.new_capacity_mw
        cumulative_cap += opt.capex_cad
        rollout[commission_year].options.append(opt.option_id)
        rollout[commission_year].cumulative_new_mw = round(cumulative_mw, 1)
        rollout[commission_year].cumulative_capex_cad = round(cumulative_cap, 0)

    # Forward-fill cumulative numbers across empty years.
    last_mw = 0.0
    last_cap = 0.0
    out: list[PhasedRollout] = []
    for y in range(1, horizon + 1):
        if rollout[y].cumulative_new_mw > 0:
            last_mw = rollout[y].cumulative_new_mw
            last_cap = rollout[y].cumulative_capex_cad
        else:
            rollout[y].cumulative_new_mw = last_mw
            rollout[y].cumulative_capex_cad = last_cap
        out.append(rollout[y])
    return out


def _blended_carbon(funded: list[ExpansionOption]) -> float:
    """MW-weighted carbon intensity of the funded portfolio."""
    total_mw = sum(o.new_capacity_mw for o in funded)
    if total_mw <= 0:
        return 0.0
    return round(sum(o.avg_carbon_g_kwh * o.new_capacity_mw for o in funded) / total_mw, 1)


class ExpansionSynthesisAgent(BaseAgent):
    async def synthesize(
        self,
        *,
        job_id: str,
        spec: ExpansionSpec,
        footprint: OperatorFootprint,
        demand: DemandForecast,
        options: list[ExpansionOption],
        funded: list[ExpansionOption],
        progress_callback=None,
    ) -> ExpansionPlan:
        if progress_callback:
            await progress_callback("Composing expansion plan...", 88)

        total_new_mw = sum(o.new_capacity_mw for o in funded)
        total_capex = sum(o.capex_cad for o in funded)
        coverage = (total_new_mw / max(1.0, spec.target_additional_mw)) * 100.0
        rollout = _phase_rollout(funded, spec.horizon_years)
        blended = _blended_carbon(funded)

        summary = await self._exec_summary(spec, footprint, demand, funded, total_new_mw, total_capex, coverage, blended)

        # Pattern 3 — reconcile Claude's exec summary against portfolio facts.
        # Drifted capacity or carbon intensity is rewritten with the computed value.
        recon_facts = {
            "capacity_mw": total_new_mw,
            "carbon_intensity_g_per_kwh": blended,
        }
        summary = reconcile(summary, recon_facts).corrected_text

        limitations = [
            "Permitting risk not explicitly modeled; schedule assumes typical municipal timelines.",
            "Grid interconnection queue position not factored. Operators should validate with the utility.",
            "Currency assumed CAD with no FX hedge consideration.",
            "Workload-mix CAGR is a market average. Individual operator pipelines may diverge.",
        ]
        if footprint.is_synthesized:
            limitations.append(
                f"Operator '{spec.operator}' wasn't in the calibrated catalog. Footprint synthesized from province defaults."
            )
        # If any Claude call (per-option rationales or exec summary) hit the
        # max_tokens cap on this agent, surface it. See base_agent._truncation_count.
        if self.had_truncation():
            limitations.append(
                f"{self._truncation_count} Claude response(s) hit the max_tokens "
                "cap, so executive summary or per-option rationale may be incomplete. "
                "Raise the cap in REPORTS_COHESION.md §8b and re-run."
            )

        plan = ExpansionPlan(
            job_id=job_id,
            spec=spec,
            footprint=footprint,
            demand_forecast=demand,
            options=options,
            funded_options=funded,
            phased_rollout=rollout,
            total_new_capacity_mw=round(total_new_mw, 1),
            total_capex_cad=round(total_capex, 0),
            blended_carbon_g_kwh=blended,
            coverage_pct=round(coverage, 1),
            executive_summary=summary,
            methodology_notes=(
                "Brownfield capacity per site capped at min(transformer headroom, "
                "5 MW/acre plot density). Capex per MW: $9.5M (air), $11M (hybrid), "
                "$13.5M (liquid), with +10% AI-training premium and +25% greenfield "
                "premium (anchored on JLL + Cushman 2024 Canadian DC build benchmarks). "
                "Demand growth assumed: traditional 12% / inference 25% / training 40% "
                "/ balanced 22% CAGR. Live ElectricityMaps reading enriches per-site "
                "carbon when the API key is set. Greedy scoring weighted "
                "grid 25% · sustainability 20% · speed 20% · cost 20% · risk 15%."
            ),
            safety_flags=self._safety_flags(funded, coverage, footprint, spec),
            limitations=limitations,
        )
        return plan

    def _safety_flags(
        self,
        funded: list[ExpansionOption],
        coverage: float,
        footprint: OperatorFootprint,
        spec: ExpansionSpec | None = None,
    ) -> list[str]:
        flags: list[str] = []
        # Routing disclosure: when the workload agent overrode the LLM's
        # operator pick (or had to leave an ambiguous city unpinned), surface
        # the decision so the operator can see *why* they're looking at the
        # operator/site they are. Empty when no city was named or routing was
        # a silent confirmation. §0 — routing transparency.
        if spec and spec.routing_note and "Overrode" in spec.routing_note:
            flags.append(spec.routing_note)
        if coverage < 90:
            flags.append(
                f"Plan covers only {coverage:.0f}% of target MW. Operator should escalate to "
                "second-wave greenfield or re-negotiate target."
            )
        if any(o.option_type == "greenfield" for o in funded) and footprint.province == "ON":
            flags.append(
                "Greenfield in Ontario carries OEB connection-queue exposure (currently 4+ year wait for new transmission service)."
            )
        high_carbon_funded = [o for o in funded if o.avg_carbon_g_kwh > 250]
        if high_carbon_funded:
            mw = sum(o.new_capacity_mw for o in high_carbon_funded)
            flags.append(
                f"{mw:.0f} MW of funded capacity sits on a grid with >250 g/kWh. "
                "Consider corporate PPAs to offset for ESG reporting."
            )
        return flags

    async def _exec_summary(
        self,
        spec: ExpansionSpec,
        footprint: OperatorFootprint,
        demand: DemandForecast,
        funded: list[ExpansionOption],
        total_new_mw: float,
        total_capex: float,
        coverage: float,
        blended_carbon: float,
    ) -> str:
        if not funded:
            return (
                f"No expansion option made the cut for {spec.operator}. Either the target "
                f"of +{spec.target_additional_mw:.0f} MW is unrealistic for the existing footprint "
                "or all candidate options scored below threshold."
            )
        top_titles = "; ".join(o.title for o in funded[:3])
        # Routing context block: when the workload agent resolved a city
        # (and possibly pinned a site / overrode the LLM's operator pick),
        # tell Claude so the exec summary grounds in that fact rather than
        # silently rationalizing a different campus. Empty when no city was
        # named — keeps the prompt identical to today for those runs.
        routing_block = ""
        if spec.city or spec.target_site_id or spec.routing_note:
            parts = []
            if spec.city:
                parts.append(f"User named city: {spec.city}")
            if spec.target_site_id:
                parts.append(f"Resolved to site: {spec.target_site_id}")
            if spec.routing_note:
                parts.append(f"Routing: {spec.routing_note}")
            routing_block = "\n".join(parts) + "\n\n"
        prompt = f"""Write a 4-5 paragraph executive summary for a datacenter
operator's leadership.

Format: open with `# Executive Summary: <one-line topic>`. Each paragraph
begins with `**<2-5 word bold title>**` on its own line, then a blank line,
then the prose. Separate paragraphs with blank lines only. Do NOT insert
`---` or any horizontal-rule dividers, and do NOT use markdown tables
(the renderer does not display them). Avoid em dashes anywhere in the
prose; use commas, periods, or parentheses.

{routing_block}Operator: {spec.operator} ({spec.province})
Target: +{spec.target_additional_mw:.0f} MW over {spec.horizon_years} years (year {spec.target_year})
Workload mix: {spec.workload_mix.replace('_', ' ')}

Funded options: {len(funded)} of {len(funded)}
Total new MW: {total_new_mw:.0f}
Total capex: ${total_capex/1e9:.2f}B
Coverage: {coverage:.0f}% of target
Blended grid carbon: {blended_carbon:.0f} g/kWh
Baseline contracted MW (today): {demand.baseline_mw:.0f}
Year-{spec.horizon_years} projected demand: {demand.target_mw_year_n:.0f} MW

Top three funded options:
{top_titles}

Paragraph 1: the verdict (target met? brownfield-only or greenfield needed?)
and headline numbers (new MW, capex, blended carbon). If the user named a
specific city or site (see Routing block above), open by acknowledging that
the plan is grounded at that location.
Paragraph 2: the 1-2 most important funded options and what makes them work.
Paragraph 3: shortfall or risk. What isn't funded and why, or where the
demand curve outpaces supply by year N.
Paragraph 4: caveats / limitations of the analysis. If routing overrode an
LLM operator pick, note that here in one sentence (e.g. "Operator routing
was corrected from X to Y because Y is the only catalog operator with a site
in the named city").
Paragraph 5: the strategic call for next budget cycle.

Tone: confident, expert, plain English. Each paragraph is 2-4 sentences."""
        try:
            return (await self.ask_claude(SYSTEM, prompt, max_tokens=900)).strip()
        except Exception as e:
            self.logger.warning(f"Exec summary failed: {e}")
            return (
                f"Funded {len(funded)} option(s) for {spec.operator}, adding "
                f"{total_new_mw:.0f} MW at ${total_capex/1e9:.2f}B (coverage {coverage:.0f}%). "
                f"Blended carbon {blended_carbon:.0f} g/kWh."
            )
