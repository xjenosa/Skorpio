"""
Chat endpoint for grounded follow-ups on a completed report.

For each pipeline a curated "context builder" pulls the most-asked-about
fields out of the persisted plan and formats them as structured text the
operator can recognise at a glance. That curated block becomes Claude's
system prompt. The endpoint streams Claude's reply via SSE, with an
inner tool-loop that lets the model call counterfactual recompute tools
(see ``backend/chat_tools.py``) before answering, and a post-stream
``reconcile()`` pass that catches any numbers Claude drifted on.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import anthropic as ant

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.chat_tools import (
    get_tools_for_pipeline,
    handle_tool_call,
    tool_result_to_facts,
)
from backend.config import settings
from backend.db import crud
from backend.db.session import get_db
from backend.models.report import SitingPlan
from backend.runtime import ALLOWED_MODELS, ChatRequest
from backend.utils.logger import get_logger
from backend.utils.reconciliation import reconcile

logger = get_logger(__name__)
router = APIRouter(tags=["chat"])


# ── Formatting helpers ────────────────────────────────────────────────── #


def _fmt(val: Any, fmt: str = ".1f", fallback: str = "N/A") -> str:
    if val is None:
        return fallback
    try:
        return format(val, fmt)
    except (TypeError, ValueError):
        return fallback


def _fmt_money_cad(v: Any) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "n/a"
    if abs(n) >= 1e9:
        return f"${n/1e9:.2f}B"
    if abs(n) >= 1e6:
        return f"${n/1e6:.1f}M"
    if abs(n) >= 1e3:
        return f"${n/1e3:.0f}K"
    return f"${n:,.0f}"


# ── Shared answer-style guidance pasted into every system prompt ───────── #


_CHAT_ANSWER_GUIDANCE = """
COUNTERFACTUAL TOOLS, read this FIRST every turn.

If the user is asking a counterfactual on a numeric parameter exposed by
a tool (HP/EV adoption %, target MW, budget $, region/LCOE constraint,
etc.), you MUST call the matching `recompute_*` / `reoptimize_*` /
`filter_*` tool BEFORE composing your reply. The tool runs real
component-level math against the report's persisted data, and that
result is the new ground truth for the turn. Estimating the new peak,
score, portfolio, or candidate in your head when a tool exists is a
critical failure mode: it produces numbers that look authoritative but
are wrong, and the post-stream reconciler will silently rewrite them.

Decision rule: if the question contains a NEW value for a parameter the
tool accepts (a new %, a new MW figure, a new $ budget, a new region or
ceiling), CALL THE TOOL. If the user is just asking about what's already
in the report (the existing peak, existing top candidates, existing
funded set, methodology, definitions, etc.), answer from the report.

ANSWERING MODES. Pick the first one that applies, silently. Never narrate
your mode choice to the user (no "Switching to Mode 3", no "I'll use
domain knowledge here"). Just answer.

1. GROUNDED. When the answer is in the report JSON, read the exact value
   from that JSON and use it.

2. TOOL-COMPUTED. When you called a counterfactual tool this turn, use
   the tool's output values directly. They are the new ground truth for
   the answer; do not blend them with the report's anchor values or
   second-guess the math.

   If the tool result includes a `narration` field, copy it verbatim as
   sentence 1. Do not paraphrase, do not re-extract numbers from other
   tool fields to rebuild it, since the narration is pre-formatted in
   the correct shape because past attempts to rebuild it from
   individual fields swapped peak and headroom values. Sentence 2 can
   add one supporting fact (which feeders bear the load, how it
   compares to the anchor scenario, etc.) and end with the
   parenthetical hedge "(first-order, linear-scaled from the X% anchor)".

3. EXTRAPOLATED. When the question asks "what if X" or "what's the impact
   of Y" but no tool covers the parameter, extrapolate using the report's
   actual figures plus first-order physics or domain heuristics. Use a
   hedge inline like "~" or "first-order estimate". DO NOT refuse.

4. DOMAIN KNOWLEDGE. When the report has no relevant data (cost of a
   project the report didn't model, etc.), give a confident industry
   rule-of-thumb with an explicit hedge ("industry typical ~", "rule of
   thumb ~"). For Canadian utilities use CAD and reference regional norms.

CRITICAL. NEVER REUSE THE NUMBERS IN THESE INSTRUCTIONS. Any value you
emit in modes 1 and 2 MUST be read from the REPORT section below.
Inventing or copying numbers from this prompt is a critical failure.

NEVER refuse with "this cannot be answered from the report." Give an
actionable answer. If you must extrapolate or use domain knowledge, do
so confidently and flag the assumption inline.

═════════════════════════════════════════════════════════════════════
FORMAT, operator chat, not a memo. These rules are HARD.

  • PLAIN TEXT ONLY. No markdown. That means: NO tables, NO headers, NO
    bold (**…**), NO italics (*…*), NO bullet lists, NO numbered lists,
    NO horizontal rules (---), NO code fences.
  • NO EM DASHES anywhere in the answer. Em dashes read as AI-generated
    prose. Use commas, periods, or parentheses instead. "X, about $500K,
    does Y" beats "X (~$500K) does Y" beats "X (about $500K) does Y"
    only when the aside is short; otherwise split into two sentences.
  • EXACTLY 2 SENTENCES. Sentence 1: the verdict or the number. Sentence
    2: the one-clause reason. Connect a qualifier with a comma, or wrap
    it in parentheses. No third sentence. No preamble.
    • When you called a counterfactual tool this turn, you MAY append a
      single parenthetical hedge at the end of sentence 2, for example
      "(first-order, linear-scaled from the 30% anchor)". This is the
      ONLY case where extra text after sentence 2 is allowed.
  • IMPLICIT COMPARISONS. When comparing options, name the alternative
    in one clause ("beats X on $/Y by ~10×"). Do not list both options
    in parallel structure.
  • NEVER offer to "recompute" or "rerun" or "want me to…?" at the end.
  • NO throat-clearing ("Great question…", "Interesting result…").
    Get to the answer.

═════════════════════════════════════════════════════════════════════
VOICE: confident, numerical, no hedging.

Every sentence should carry at least one figure. Do not soften with
"might", "could", "potentially", "in some cases". Do not bundle trailing
caveats. Drop adverbs that do not change the meaning.

═════════════════════════════════════════════════════════════════════
AUDIENCE: plain English, not engineering jargon.

The reader is a planner or executive who understands grid investment
but not power-systems vocabulary. Translate engineering terms inline.
The TIGHTNESS of the preferred voice is non-negotiable; the JARGON is.

  Jargon to plain-English replacement:
    "N-1 failure"          becomes "loses backup margin" or "one trip causes outage"
    "transformer procurement" becomes "new transformers (~3-year wait)"
    "feeder sectionalizing" becomes "automatic switching gear"
    "POI headroom"         becomes "spare grid-connection capacity"
    "HP COP"               becomes "heat pump efficiency"
    "auxiliary resistance heat" becomes "backup electric strip heating"
    "$/resilience"         becomes "resilience per dollar"
    "polar vortex nadir"   becomes "coldest hour of the cold snap"
    "saturate feeders"     becomes "overload local lines"

Numbers stay. "1,425 MW" or "$500K" reads fine. Only the connecting
tissue translates.

═════════════════════════════════════════════════════════════════════
EXAMPLES, match this shape, density, and connector style exactly.

  Q: "What if heat pump adoption hits 50%?"
  [model calls recompute_winter_peak(hp_pct=0.5, ev_pct=<same as report>);
   tool returns narration="At 50% HP / 30% EV the network peaks at 3,780
   MW, leaving 1,425 MW of headroom (27.4% of nameplate), still a pass"]
  A: "At 50% HP / 30% EV the network peaks at 3,780 MW, leaving 1,425 MW
      of headroom (27.4% of nameplate), still a pass. The bulk of the
      new load lands on the aged MIS-01 feeders that already sit at
      30-46% utilization (first-order, linear-scaled from the 30% anchor)."

  Q: "Which upgrade gives us the most resilience per dollar?"
  A: "Fan cooling plus automatic switching gear runs about $500K per
      substation and restores backup margin without the 3-year wait for
      new transformers. Roughly 10× the resilience per dollar versus
      full transformer replacement."

═════════════════════════════════════════════════════════════════════
TONE: direct, plain English, numerical, confident. Two sentences.
"""


# ── Curated context builders, one per pipeline ────────────────────────── #
#
# Each function takes either a typed plan (siting) or a result dict
# (others) and returns the system prompt Claude sees. Layout differs per
# pipeline because the most-asked-about figures differ — Winter Peak chat
# wants the worst-scenario peak load, Investment wants total capex
# committed, etc.


def _build_siting_chat_context(plan: SitingPlan) -> str:
    region_blocks: list[str] = []
    for ins in plan.region_insights:
        best = ins.top_sites[0] if ins.top_sites else None
        best_line = ""
        if best is not None:
            best_line = (
                f"\n  Best site: {best.site.name} | "
                f"LCOE=${_fmt(best.levelized_cost_usd_mwh)}/MWh | "
                f"method={best.scoring_method}"
            )
        region_blocks.append(
            f"REGION: {ins.region_iso}\n"
            f"  Market outlook:         {ins.market_outlook}\n"
            f"  Transmission notes:     {ins.transmission_constraints}\n"
            f"  Regulatory context:     {ins.regulatory_context}{best_line}"
        )

    candidate_blocks: list[str] = []
    for c in plan.top_candidates[:7]:
        profile = c.site.profile
        interactions_text = "; ".join(
            f"{i.facility} {i.interaction_type}"
            + (f" {_fmt(i.distance_km)} km" if i.distance_km else "")
            for i in c.interactions[:4]
        ) or "not analyzed"
        candidate_blocks.append(
            f"Rank {c.rank} | Region: {c.region_iso} | "
            f"LCOE=${_fmt(c.levelized_cost_usd_mwh)}/MWh | "
            f"method={c.scoring_method}\n"
            f"  Site: {c.site.name} ({c.site.latitude:.3f}, {c.site.longitude:.3f})\n"
            f"  Profile: Capacity={_fmt(profile.capacity_mw, '.1f')} MW | "
            f"PUE={_fmt(profile.pue, '.2f')} | "
            f"Latency={_fmt(profile.fiber_latency_ms, '.1f')} ms | "
            f"Headroom={_fmt(profile.transmission_headroom_mw, '.1f')} MW | "
            f"Deploy={_fmt(profile.deployment_months, '.0f')} mo\n"
            f"  Interactions: {interactions_text}\n"
            f"  Explanation: {c.explanation[:400]}"
        )

    safety_text = "\n".join(f"- {f}" for f in plan.safety_flags) or "None reported"
    limitations_text = "\n".join(f"- {l}" for l in plan.limitations) or "None reported"

    return (
        "You are a senior siting analyst sitting next to the operator who just\n"
        "ran this datacenter-placement campaign. The full curated plan data is below.\n"
        f"{_CHAT_ANSWER_GUIDANCE}\n"
        "══ WORKLOAD ══════════════════════════════════════════════════════\n"
        f"Name:        {plan.workload_name}\n"
        f"Description: {plan.workload_description}\n"
        f"Capacity:    {plan.target_capacity_mw} MW\n"
        f"Latency:     {plan.target_latency_ms} ms\n\n"
        "══ PIPELINE STATISTICS ══════════════════════════════════════════\n"
        f"Regions analyzed:      {plan.regions_analyzed}\n"
        f"Sites generated:       {plan.sites_generated}\n"
        f"Sites scored:          {plan.sites_scored}\n"
        f"Top candidates ranked: {len(plan.top_candidates)}\n\n"
        "══ REGION INSIGHTS ══════════════════════════════════════════════\n"
        + "\n".join(region_blocks)
        + "\n\n══ TOP SITING CANDIDATES ════════════════════════════════════════\n"
        + "\n".join(candidate_blocks)
        + "\n\n══ SAFETY FLAGS ═════════════════════════════════════════════════\n"
        + safety_text
        + "\n\n══ LIMITATIONS ══════════════════════════════════════════════════\n"
        + limitations_text
        + "\n\n══ EXECUTIVE SUMMARY ════════════════════════════════════════════\n"
        + plan.executive_summary
        + "\n\n══ METHODOLOGY ══════════════════════════════════════════════════\n"
        + plan.methodology_notes
    )


def _build_winter_chat_context(result: dict) -> str:
    spec = result.get("spec") or {}
    network = result.get("network") or {}
    cold = result.get("cold_event") or {}
    scenarios = result.get("scenarios") or []
    mitigations = result.get("mitigations") or []

    scenario_blocks: list[str] = []
    for s in scenarios:
        sc = s.get("scenario") or {}
        lp = s.get("load_profile") or {}
        notable = "; ".join((s.get("notable_failures") or [])[:3]) or "none"
        scenario_blocks.append(
            f"  {sc.get('name', '?')} ({sc.get('label', '')})\n"
            f"    verdict={s.get('summary_verdict', '?')} | "
            f"peak={_fmt(lp.get('peak_load_mw'), '.0f')} MW "
            f"at hr {lp.get('peak_hour_offset', '?')} | "
            f"headroom={_fmt(lp.get('headroom_at_peak_mw'), '.0f')} MW "
            f"({_fmt(lp.get('headroom_pct_at_peak'), '.1f')}%)\n"
            f"    notable: {notable}\n"
            f"    headline: {s.get('headline', '')}"
        )

    feeder_lines: list[str] = []
    for s in scenarios:
        scenario_name = (s.get("scenario") or {}).get("name", "?")
        for fr in (s.get("feeder_risks") or [])[:5]:
            feeder_lines.append(
                f"  [{scenario_name}] "
                f"{fr.get('feeder_name', '?')} ({fr.get('feeder_id', '?')}): "
                f"overload={_fmt(fr.get('overload_risk'), '.2f')} | "
                f"util={_fmt(fr.get('capacity_utilization_pct'), '.0f')}% | "
                f"mode={fr.get('failure_mode', '?')}"
            )

    mit_lines: list[str] = []
    for m in mitigations[:6]:
        mit_lines.append(
            f"  {m.get('title', '?')} ({m.get('category', '?')}): "
            f"relief={_fmt(m.get('estimated_load_relief_mw'), '.0f')} MW | "
            f"cost={_fmt_money_cad(m.get('estimated_cost_cad'))} | "
            f"deploy={m.get('deployment_months', '?')} mo | "
            f"risk-reduction={_fmt(m.get('risk_reduction_pct'), '.0f')}%"
        )

    safety_text = "\n".join(f"- {f}" for f in (result.get("safety_flags") or [])) or "None reported"
    lim_text = "\n".join(f"- {l}" for l in (result.get("limitations") or [])) or "None reported"

    return (
        "You are a senior grid resilience analyst sitting next to the operator\n"
        "who just ran this Winter Peak Stress Tester report. The curated plan\n"
        "data is below.\n"
        f"{_CHAT_ANSWER_GUIDANCE}\n"
        "══ TEST SETUP ═══════════════════════════════════════════════════\n"
        f"City:        {spec.get('city', '?')} ({spec.get('province', '?')})\n"
        f"Utility:     {spec.get('utility', '?')}\n"
        f"Cold event:  {cold.get('name', '?')} ({cold.get('event_id', '?')})\n"
        f"  min temp:  {_fmt(cold.get('min_temp_c'), '.1f')} °C | "
        f"duration: {cold.get('duration_hours', '?')} hr\n"
        f"Horizon:     {spec.get('horizon_year', '?')}\n\n"
        "══ NETWORK ══════════════════════════════════════════════════════\n"
        f"Substations:           {len(network.get('substations') or [])}\n"
        f"Feeders:               {len(network.get('feeders') or [])}\n"
        f"Baseline winter peak:  {_fmt(network.get('baseline_winter_peak_mw'), '.0f')} MW "
        f"(year {network.get('baseline_year', '?')})\n\n"
        "══ SCENARIOS ════════════════════════════════════════════════════\n"
        + ("\n".join(scenario_blocks) or "  (no scenarios)")
        + "\n\n══ TOP FEEDERS AT RISK (worst 5 per scenario) ══════════════════\n"
        + ("\n".join(feeder_lines) or "  (no feeder risks recorded)")
        + "\n\n══ MITIGATIONS ══════════════════════════════════════════════════\n"
        + ("\n".join(mit_lines) or "  (no mitigations recorded)")
        + "\n\n══ SAFETY FLAGS ═════════════════════════════════════════════════\n"
        + safety_text
        + "\n\n══ LIMITATIONS ══════════════════════════════════════════════════\n"
        + lim_text
        + "\n\n══ EXECUTIVE SUMMARY ════════════════════════════════════════════\n"
        + (result.get("executive_summary") or "")
        + "\n\n══ METHODOLOGY ══════════════════════════════════════════════════\n"
        + (result.get("methodology_notes") or "")
    )


def _build_electrification_chat_context(result: dict) -> str:
    spec = result.get("spec") or {}
    fsa_outcomes = result.get("fsa_outcomes") or []
    interventions = result.get("interventions") or []

    outcome_blocks: list[str] = []
    for fo in fsa_outcomes[:12]:
        prof = fo.get("profile") or {}
        sc = fo.get("scenario") or {}
        rd = fo.get("readiness") or {}
        li = fo.get("load_impact") or {}
        blockers = "; ".join((rd.get("blockers") or [])[:3]) or "none"
        outcome_blocks.append(
            f"  {prof.get('fsa', '?')} ({prof.get('label', '?')[:40]}) × {sc.get('name', '?')}\n"
            f"    verdict={rd.get('verdict', '?')} | "
            f"overall={_fmt(rd.get('overall_score'), '.2f')} "
            f"| grid={_fmt(rd.get('grid_score'), '.2f')} "
            f"bldg={_fmt(rd.get('building_score'), '.2f')} "
            f"afford={_fmt(rd.get('affordability_score'), '.2f')} "
            f"policy={_fmt(rd.get('policy_score'), '.2f')}\n"
            f"    incremental peak: +{_fmt(li.get('incremental_peak_mw'), '.1f')} MW | "
            f"tx-overloads={li.get('transformer_overload_count', 0)} | "
            f"panel-upgrades={_fmt(li.get('panel_upgrade_household_pct'), '.0f')}% of homes\n"
            f"    blockers: {blockers}"
        )

    int_block: list[str] = []
    for i in interventions[:6]:
        int_block.append(
            f"  {i.get('title', '?')} ({i.get('category', '?')}): "
            f"households={i.get('households_unlocked', 0):,} | "
            f"cost={_fmt_money_cad(i.get('estimated_cost_cad'))} | "
            f"deploy={i.get('deployment_months', '?')} mo | "
            f"lift={_fmt(i.get('readiness_lift_pct'), '.0f')} pts"
        )

    safety_text = "\n".join(f"- {f}" for f in (result.get("safety_flags") or [])) or "None reported"
    lim_text = "\n".join(f"- {l}" for l in (result.get("limitations") or [])) or "None reported"

    return (
        "You are a senior distribution-planning analyst sitting next to the\n"
        "operator who just ran this Electrification Readiness report. The\n"
        "curated plan data is below.\n"
        f"{_CHAT_ANSWER_GUIDANCE}\n"
        "══ STUDY SETUP ══════════════════════════════════════════════════\n"
        f"City:        {spec.get('city', '?')} ({spec.get('province', '?')})\n"
        f"FSAs:        {', '.join(spec.get('fsas') or []) or 'whole-city sample'}\n"
        f"Scope:       {spec.get('scope', '?')}\n"
        f"Horizon:     {spec.get('horizon_year', '?')}\n\n"
        "══ FSA × SCENARIO OUTCOMES (top 12) ═════════════════════════════\n"
        + ("\n".join(outcome_blocks) or "  (no outcomes)")
        + "\n\n══ INTERVENTIONS ════════════════════════════════════════════════\n"
        + ("\n".join(int_block) or "  (no interventions recommended)")
        + "\n\n══ SAFETY FLAGS ═════════════════════════════════════════════════\n"
        + safety_text
        + "\n\n══ LIMITATIONS ══════════════════════════════════════════════════\n"
        + lim_text
        + "\n\n══ EXECUTIVE SUMMARY ════════════════════════════════════════════\n"
        + (result.get("executive_summary") or "")
        + "\n\n══ METHODOLOGY ══════════════════════════════════════════════════\n"
        + (result.get("methodology_notes") or "")
    )


def _build_investment_chat_context(result: dict) -> str:
    spec = result.get("spec") or {}
    funded = result.get("funded_projects") or []
    unfunded = result.get("unfunded_projects") or []

    funded_block: list[str] = []
    for fp in funded[:8]:
        p = fp.get("project") or {}
        funded_block.append(
            f"  #{fp.get('rank', '?')} {p.get('title', '?')} ({p.get('category', '?')})\n"
            f"    capex={_fmt_money_cad(p.get('capex_cad'))} | "
            f"customers={p.get('customers_protected', 0):,} | "
            f"deploy={p.get('deployment_months', '?')} mo | "
            f"ROI={_fmt(fp.get('roi_ratio'), '.2f')}x | "
            f"cumulative={_fmt_money_cad(fp.get('cumulative_capex_cad'))}\n"
            f"    hazards: {', '.join(p.get('hazards_addressed') or []) or '—'}"
        )

    unfunded_block: list[str] = []
    for p in unfunded[:5]:
        unfunded_block.append(
            f"  {p.get('title', '?')} ({p.get('category', '?')}): "
            f"capex={_fmt_money_cad(p.get('capex_cad'))} | "
            f"customers={p.get('customers_protected', 0):,} | "
            f"deploy={p.get('deployment_months', '?')} mo"
        )

    safety_text = "\n".join(f"- {f}" for f in (result.get("safety_flags") or [])) or "None reported"
    lim_text = "\n".join(f"- {l}" for l in (result.get("limitations") or [])) or "None reported"

    return (
        "You are a senior grid investment strategist sitting next to the\n"
        "operator who just ran this Climate-Adapted Grid Investment Optimizer\n"
        "report. The curated plan data is below.\n"
        f"{_CHAT_ANSWER_GUIDANCE}\n"
        "══ INVESTMENT SETUP ═════════════════════════════════════════════\n"
        f"Utility:       {spec.get('utility', '?')} ({spec.get('province', '?')})\n"
        f"Budget:        {_fmt_money_cad(spec.get('budget_cad'))} over "
        f"{spec.get('horizon_years', '?')} years\n"
        f"Target year:   {spec.get('target_year', '?')}\n"
        f"Priority hazards: {', '.join(spec.get('priority_hazards') or []) or '—'}\n\n"
        "══ PORTFOLIO TOTALS ═════════════════════════════════════════════\n"
        f"Capex committed:       {_fmt_money_cad(result.get('total_capex_committed_cad'))}\n"
        f"Annual loss avoided:   {_fmt_money_cad(result.get('total_annual_loss_avoided_cad'))}\n"
        f"Portfolio ROI:         {_fmt(result.get('portfolio_roi_ratio'), '.2f')}x\n"
        f"Customers protected:   {result.get('customers_protected', 0):,}\n"
        f"Funded projects:       {len(funded)} / candidates: "
        f"{len(result.get('candidate_projects') or [])}\n\n"
        "══ FUNDED PROJECTS (top 8 by rank) ══════════════════════════════\n"
        + ("\n".join(funded_block) or "  (none funded)")
        + "\n\n══ TOP UNFUNDED — would fit a bigger budget ═══════════════════\n"
        + ("\n".join(unfunded_block) or "  (none unfunded)")
        + "\n\n══ SAFETY FLAGS ═════════════════════════════════════════════════\n"
        + safety_text
        + "\n\n══ LIMITATIONS ══════════════════════════════════════════════════\n"
        + lim_text
        + "\n\n══ EXECUTIVE SUMMARY ════════════════════════════════════════════\n"
        + (result.get("executive_summary") or "")
        + "\n\n══ METHODOLOGY ══════════════════════════════════════════════════\n"
        + (result.get("methodology_notes") or "")
    )


def _build_expansion_chat_context(result: dict) -> str:
    spec = result.get("spec") or {}
    footprint = result.get("footprint") or {}
    forecast = result.get("demand_forecast") or {}
    funded = result.get("funded_options") or []
    rollout = result.get("phased_rollout") or []

    funded_block: list[str] = []
    for opt in funded[:6]:
        blockers = "; ".join((opt.get("blockers") or [])[:2]) or "none"
        funded_block.append(
            f"  #{opt.get('rank', '?')} {opt.get('title', '?')} [{opt.get('option_type', '?')}]\n"
            f"    new={_fmt(opt.get('new_capacity_mw'), '.1f')} MW | "
            f"capex={_fmt_money_cad(opt.get('capex_cad'))} "
            f"(${_fmt(opt.get('capex_per_mw_cad'), '.0f')}/MW) | "
            f"deploy={opt.get('deployment_months', '?')} mo | "
            f"carbon={_fmt(opt.get('avg_carbon_g_kwh'), '.0f')} g/kWh\n"
            f"    scores: overall={_fmt(opt.get('overall_score'), '.2f')} "
            f"grid={_fmt(opt.get('grid_score'), '.2f')} "
            f"sustainability={_fmt(opt.get('sustainability_score'), '.2f')} "
            f"speed={_fmt(opt.get('speed_score'), '.2f')} "
            f"cost={_fmt(opt.get('cost_score'), '.2f')}\n"
            f"    blockers: {blockers}"
        )

    rollout_block: list[str] = []
    for r in rollout[:6]:
        rollout_block.append(
            f"  {r.get('year', '?')}: +{_fmt(r.get('cumulative_new_mw'), '.0f')} MW cumulative | "
            f"capex={_fmt_money_cad(r.get('cumulative_capex_cad'))} | "
            f"options: {', '.join(r.get('options') or []) or '—'}"
        )

    safety_text = "\n".join(f"- {f}" for f in (result.get("safety_flags") or [])) or "None reported"
    lim_text = "\n".join(f"- {l}" for l in (result.get("limitations") or [])) or "None reported"

    return (
        "You are a senior expansion-planning analyst sitting next to the\n"
        "operator who just ran this Datacenter Expansion Planner report. The\n"
        "curated plan data is below.\n"
        f"{_CHAT_ANSWER_GUIDANCE}\n"
        "══ EXPANSION SETUP ══════════════════════════════════════════════\n"
        f"Operator:      {spec.get('operator', '?')} ({spec.get('province', '?')})\n"
        f"City:          {spec.get('city', '—')} | target site: {spec.get('target_site_id', '—')}\n"
        f"Target add:    {spec.get('target_additional_mw', '?')} MW over "
        f"{spec.get('horizon_years', '?')} years\n"
        f"Workload mix:  {spec.get('workload_mix', '?')} | "
        f"prefer-brownfield: {spec.get('prefer_brownfield', '?')}\n"
        f"Routing note:  {spec.get('routing_note', '') or '—'}\n\n"
        "══ EXISTING FOOTPRINT ═══════════════════════════════════════════\n"
        f"Operator total: {_fmt(footprint.get('total_current_capacity_mw'), '.0f')} MW\n"
        f"Sites:          {len(footprint.get('sites') or [])}\n\n"
        "══ DEMAND FORECAST ══════════════════════════════════════════════\n"
        f"Baseline:      {_fmt(forecast.get('baseline_mw'), '.0f')} MW\n"
        f"Annual growth: {_fmt(forecast.get('annual_growth_rate'), '.1%')}\n"
        f"Year-N target: {_fmt(forecast.get('target_mw_year_n'), '.0f')} MW\n"
        f"Drivers:       {'; '.join(forecast.get('drivers') or []) or '—'}\n\n"
        "══ FUNDED OPTIONS (top 6) ══════════════════════════════════════\n"
        + ("\n".join(funded_block) or "  (none funded)")
        + "\n\n══ PHASED ROLLOUT ═══════════════════════════════════════════════\n"
        + ("\n".join(rollout_block) or "  (no rollout)")
        + "\n\n══ PLAN TOTALS ══════════════════════════════════════════════════\n"
        + f"New capacity:      {_fmt(result.get('total_new_capacity_mw'), '.0f')} MW\n"
        + f"Total capex:       {_fmt_money_cad(result.get('total_capex_cad'))}\n"
        + f"Blended carbon:    {_fmt(result.get('blended_carbon_g_kwh'), '.0f')} g/kWh\n"
        + f"Coverage of goal:  {_fmt(result.get('coverage_pct'), '.0f')}%\n\n"
        + "══ SAFETY FLAGS ═════════════════════════════════════════════════\n"
        + safety_text
        + "\n\n══ LIMITATIONS ══════════════════════════════════════════════════\n"
        + lim_text
        + "\n\n══ EXECUTIVE SUMMARY ════════════════════════════════════════════\n"
        + (result.get("executive_summary") or "")
        + "\n\n══ METHODOLOGY ══════════════════════════════════════════════════\n"
        + (result.get("methodology_notes") or "")
    )


def _build_generic_chat_context(pipeline_id: str | None, result: dict) -> str:
    """Last-resort fallback used when the pipeline-specific curated builder
    raises an exception or the pipeline id is unrecognised."""
    pipeline_label = {
        "winter-peak-stress": "Winter Peak Stress Tester",
        "electrification-readiness": "Neighborhood Electrification Readiness",
        "grid-investment-optimizer": "Climate-Adapted Grid Investment Optimizer",
        "datacenter-expansion": "Datacenter Expansion Planner",
        "datacenter-siting": "Datacenter Siting",
    }.get(pipeline_id or "", "Skorpio")

    blob = json.dumps(result, default=str, ensure_ascii=False, indent=2)
    if len(blob) > 32_000:
        blob = blob[:32_000] + "\n... (truncated)"

    return (
        f"You are a senior grid analyst sitting next to the operator who just\n"
        f"ran a {pipeline_label} report. The full report JSON is below.\n"
        f"{_CHAT_ANSWER_GUIDANCE}\n"
        "══ REPORT JSON ═══════════════════════════════════════════════════\n"
        f"{blob}"
    )


# Pipeline-specific builders keyed by pipeline_id. ``datacenter-siting``
# accepts a typed plan; the others read dict-shaped results. The
# dispatcher below handles the type difference.
_CURATED_BUILDERS: dict[str, Callable[..., str]] = {
    "datacenter-siting": _build_siting_chat_context,
    "winter-peak-stress": _build_winter_chat_context,
    "electrification-readiness": _build_electrification_chat_context,
    "grid-investment-optimizer": _build_investment_chat_context,
    "datacenter-expansion": _build_expansion_chat_context,
}


def _build_system_prompt(pipeline_id: str, result: dict) -> str:
    """Pick the right curated builder and call it. Falls back to the
    generic JSON-dump context when the curated builder raises (e.g. a
    legacy result row that doesn't match the current Pydantic shape)."""
    try:
        if pipeline_id == "datacenter-siting":
            plan = SitingPlan.model_validate(result)
            return _build_siting_chat_context(plan)
        builder = _CURATED_BUILDERS.get(pipeline_id)
        if builder is not None:
            return builder(result)
    except Exception:
        logger.exception(
            "Curated chat context build failed for pipeline=%s; "
            "falling back to generic JSON-dump context.", pipeline_id,
        )
    return _build_generic_chat_context(pipeline_id, result)


# ── Reconciliation-fact extraction ────────────────────────────────────── #


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_chat_facts(pipeline_id: str | None, result: dict) -> dict[str, float]:
    """Pull the most-asked-about numbers out of the plan so post-stream
    ``reconcile()`` can compare what Claude wrote against ground truth.
    Keys MUST match those recognised by ``_DEFAULT_CONTEXT_HINTS`` in
    ``reconciliation.py``. Missing fields are simply omitted —
    ``reconcile()`` only flags drift on facts it actually receives."""
    if not isinstance(result, dict):
        return {}

    facts: dict[str, float] = {}

    if pipeline_id == "datacenter-siting":
        top_list = result.get("top_candidates") or []
        if top_list:
            lcoe = _f(top_list[0].get("levelized_cost_usd_mwh"))
            if lcoe is not None:
                facts["lcoe_usd_mwh"] = lcoe
        cap = _f(result.get("target_capacity_mw"))
        if cap is not None:
            facts["capacity_mw"] = cap

    elif pipeline_id == "winter-peak-stress":
        # Worst-case scenario peak — anchored on "peak", not "capacity".
        worst_peak: float | None = None
        for s in result.get("scenarios") or []:
            lp = (s or {}).get("load_profile") or {}
            peak = _f(lp.get("peak_load_mw"))
            if peak is None:
                continue
            if worst_peak is None or peak > worst_peak:
                worst_peak = peak
        if worst_peak is not None:
            facts["peak_load_mw"] = worst_peak
            facts["demand_gw"] = worst_peak / 1000.0
        if "peak_load_mw" not in facts:
            baseline = _f((result.get("network") or {}).get("baseline_winter_peak_mw"))
            if baseline is not None:
                facts["peak_load_mw"] = baseline

    elif pipeline_id == "electrification-readiness":
        outcomes = result.get("fsa_outcomes") or []
        if outcomes:
            score = _f(outcomes[0].get("overall_score"))
            if score is not None:
                facts["overall_score"] = score
        spec = result.get("spec") or {}
        hp = _f(spec.get("heat_pump_adoption_pct"))
        if hp is not None:
            facts["heat_pump_adoption_pct"] = hp
        ev = _f(spec.get("ev_adoption_pct"))
        if ev is not None:
            facts["ev_adoption_pct"] = ev

    elif pipeline_id == "grid-investment-optimizer":
        spec = result.get("spec") or {}
        budget = _f(spec.get("budget_cad"))
        if budget is not None:
            facts["budget_cad"] = budget
        committed = _f(result.get("total_capex_committed_cad"))
        if committed is not None:
            facts["total_capex_committed_cad"] = committed
        protected = _f(result.get("total_customers_protected"))
        if protected is not None:
            facts["customers_protected"] = protected

    elif pipeline_id == "datacenter-expansion":
        cap = _f(result.get("total_new_capacity_mw"))
        if cap is not None:
            facts["capacity_mw"] = cap
        carbon = _f(result.get("blended_carbon_g_kwh"))
        if carbon is not None:
            facts["carbon_intensity_g_per_kwh"] = carbon

    return facts


# ── The endpoint ──────────────────────────────────────────────────────── #


@router.post("/api/chat/{job_id}")
async def chat_with_plan(
    job_id: str,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Stream a Claude response grounded in the completed report."""
    job = await crud.get_job(db, job_id)
    if not job or not job.result:
        raise HTTPException(status_code=404, detail="Plan not found or pipeline not complete")

    if request.model is not None and request.model not in ALLOWED_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model '{request.model}'. Allowed: {sorted(ALLOWED_MODELS)}",
        )

    model_id = request.model or settings.anthropic_model
    pipeline_id = job.pipeline_id or "datacenter-siting"
    system = _build_system_prompt(pipeline_id, job.result or {})
    chat_facts = _extract_chat_facts(pipeline_id, job.result or {})
    tools = get_tools_for_pipeline(pipeline_id)
    frozen_result: dict = job.result or {}

    client = ant.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def stream_response():
        # Buffer ALL streamed text across tool rounds so the final
        # reconcile() pass sees the complete user-visible answer.
        buffered: list[str] = []
        # Tool-fact accumulator. When a counterfactual tool fires, its
        # output is the new ground truth for THIS turn — the frozen-report
        # peak/score/budget is no longer the value the model should be
        # reconciled against. Last-write-wins across rounds matches the
        # user's most recent counterfactual.
        tool_facts: dict[str, float] = {}
        messages: list[dict] = [
            {"role": m.role, "content": m.content} for m in request.messages
        ]
        # Hard cap on tool-use rounds. With tool_choice:auto Claude
        # converges in 1 round for the counterfactual prompts we expose;
        # the cap is a safety net against pathological loops.
        max_rounds = 4
        cached_system = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
        ]
        try:
            for _round in range(max_rounds):
                stream_kwargs: dict[str, Any] = {
                    "model": model_id,
                    "max_tokens": 1024,
                    "system": cached_system,
                    "messages": messages,
                }
                if tools:
                    stream_kwargs["tools"] = tools

                async with client.messages.stream(**stream_kwargs) as stream:
                    async for text in stream.text_stream:
                        buffered.append(text)
                        yield f"data: {json.dumps({'text': text})}\n\n"
                    final_msg = await stream.get_final_message()

                tool_uses = [
                    blk for blk in (final_msg.content or [])
                    if getattr(blk, "type", None) == "tool_use"
                ]
                if not tool_uses:
                    break

                messages.append({
                    "role": "assistant",
                    "content": [blk.model_dump(exclude_none=True) for blk in final_msg.content],
                })

                tool_results: list[dict] = []
                for tu in tool_uses:
                    output = handle_tool_call(tu.name, tu.input or {}, frozen_result)
                    logger.info(
                        "Chat tool call: job=%s pipeline=%s tool=%s args=%s",
                        job_id, pipeline_id, tu.name, tu.input,
                    )
                    # Capture the tool's output as the new ground truth
                    # for reconciliation. Later tool calls in the same
                    # turn (e.g. user asks two counterfactuals back-to-back)
                    # overwrite earlier ones — last-write-wins.
                    tool_facts.update(tool_result_to_facts(tu.name, output))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps(output, default=str),
                    })
                messages.append({"role": "user", "content": tool_results})
            else:
                logger.warning(
                    "Chat tool loop hit %d-round cap (job=%s, pipeline=%s)",
                    max_rounds, job_id, pipeline_id,
                )

            # Reconciliation strategy:
            #   - No tool called this turn → run reconcile() against the
            #     frozen-report facts, catching any hallucinated digits.
            #   - A tool was called → SKIP reconcile() entirely. The tool's
            #     `narration` string is the authoritative answer and the
            #     model copies it verbatim. The keyword-window reconciler
            #     can't distinguish "peaks at X MW" from "leaving Y MW"
            #     when both numbers sit inside the 50-char hint window,
            #     so it false-positive-rewrites the headroom value to
            #     match the peak (or vice versa) and breaks the answer.
            if tool_facts:
                logger.info(
                    "Chat tool ran for job %s (pipeline=%s) — skipping "
                    "reconcile() because the tool narration is the "
                    "authoritative answer for this turn.",
                    job_id, pipeline_id,
                )
            elif chat_facts:
                full_text = "".join(buffered)
                # 5% tolerance — strict enough to catch hallucinated digits,
                # loose enough for legitimate rounding (4,520 → "~4,500 MW").
                report = reconcile(full_text, chat_facts, tolerance_pct=5.0)
                if report.has_drift and report.corrected_text != full_text:
                    logger.warning(
                        "Chat reconciliation rewrote %d number(s) for job %s "
                        "(pipeline=%s)",
                        len(report.drifts), job_id, pipeline_id,
                    )
                    yield f"data: {json.dumps({'corrected': report.corrected_text})}\n\n"
        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            yield f"data: {json.dumps({'text': 'Error generating response. Please try again.'})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
