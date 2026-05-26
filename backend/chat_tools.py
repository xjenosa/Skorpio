"""
Per-pipeline tools the chat endpoint exposes to Claude.

Each tool operates purely on the persisted ``job.result`` JSON — no Claude
re-invocation, no DB writes, no network. The output is fed back to Claude as
a ``tool_result`` block; Claude then narrates the answer in the chat reply.
The frozen report is never modified — these tools answer counterfactuals
*inside the chat turn only*.

Each pipeline gets one tool, with a tight description so ``tool_choice:auto``
keeps it dormant unless the user explicitly asks a counterfactual.
"""
from __future__ import annotations

from typing import Any


# ── Helpers ────────────────────────────────────────────────────────────── #

def _f(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _nearest_by(items: list[dict], key_fn) -> dict | None:
    """Pick the item where ``key_fn(item)`` is minimal."""
    if not items:
        return None
    return min(items, key=key_fn)


# ── Tool 1: Winter Peak — recompute_winter_peak ────────────────────────── #

def _recompute_winter_peak(args: dict, result: dict) -> dict:
    """Re-project the worst-case peak load under new adoption assumptions.

    Strategy: pick the existing scenario whose (hp%, ev%) is closest to the
    request. Decompose its peak hour into base + hp + backup + ev + other.
    Linearly scale the HP and EV components to the new percentages, and
    return the resulting peak vs. baseline + network nameplate headroom.
    """
    hp_pct = _f(args.get("hp_pct"))
    ev_pct = _f(args.get("ev_pct"))
    if hp_pct is None or ev_pct is None:
        return {"error": "Both hp_pct and ev_pct are required (0.0–1.0)."}
    hp_pct = _clamp(hp_pct, 0.0, 1.0)
    ev_pct = _clamp(ev_pct, 0.0, 1.0)

    scenarios = result.get("scenarios") or []
    if not scenarios:
        return {"error": "Report has no scenarios to anchor a re-projection."}

    # Pick the closest existing scenario by Euclidean distance in (hp, ev).
    def _dist(s: dict) -> float:
        sp = (s or {}).get("scenario") or {}
        a = _f(sp.get("heat_pump_adoption_pct"), 0.0) or 0.0
        b = _f(sp.get("ev_adoption_pct"), 0.0) or 0.0
        return (a - hp_pct) ** 2 + (b - ev_pct) ** 2

    anchor = _nearest_by(scenarios, _dist)
    anchor_spec = (anchor or {}).get("scenario") or {}
    anchor_lp = (anchor or {}).get("load_profile") or {}
    anchor_hp = _f(anchor_spec.get("heat_pump_adoption_pct"), 0.0) or 0.0
    anchor_ev = _f(anchor_spec.get("ev_adoption_pct"), 0.0) or 0.0

    # Find the peak hour in the anchor's hourly profile.
    hours = anchor_lp.get("hours") or []
    if not hours:
        # No hourly decomposition — fall back to flat scaling on peak_load_mw.
        anchor_peak = _f(anchor_lp.get("peak_load_mw"), 0.0) or 0.0
        # Naïve: assume HP+EV components account for (anchor_hp+anchor_ev) share
        # of growth above baseline.
        baseline = _f((result.get("network") or {}).get("baseline_winter_peak_mw"), 0.0) or 0.0
        growth = max(0.0, anchor_peak - baseline)
        hp_share = (anchor_hp / max(anchor_hp + anchor_ev, 1e-6)) * growth
        ev_share = growth - hp_share
        new_hp = hp_share * (hp_pct / max(anchor_hp, 1e-6))
        new_ev = ev_share * (ev_pct / max(anchor_ev, 1e-6))
        projected = baseline + new_hp + new_ev
        method = "flat-scale (no hourly profile)"
        peak_hour = None
        peak_temp = None
    else:
        peak_point = max(hours, key=lambda h: _f(h.get("total_load_mw"), 0.0) or 0.0)
        base_mw    = _f(peak_point.get("base_load_mw"), 0.0) or 0.0
        hp_mw      = _f(peak_point.get("heat_pump_load_mw"), 0.0) or 0.0
        backup_mw  = _f(peak_point.get("backup_resistance_mw"), 0.0) or 0.0
        baseboard  = _f(peak_point.get("baseboard_load_mw"), 0.0) or 0.0
        ev_mw      = _f(peak_point.get("ev_load_mw"), 0.0) or 0.0
        other_mw   = _f(peak_point.get("other_load_mw"), 0.0) or 0.0

        # Linear scale HP-derived (heat pump + backup resistance) and EV components.
        hp_scale = hp_pct / max(anchor_hp, 1e-6) if anchor_hp > 0 else 0.0
        ev_scale = ev_pct / max(anchor_ev, 1e-6) if anchor_ev > 0 else 0.0
        new_hp_total = (hp_mw + backup_mw) * hp_scale
        new_ev_total = ev_mw * ev_scale
        projected = base_mw + baseboard + other_mw + new_hp_total + new_ev_total
        method = "linear-scale on peak hour"
        peak_hour = peak_point.get("hour_offset")
        peak_temp = _f(peak_point.get("temp_c"))

    network = result.get("network") or {}
    baseline_peak = _f(network.get("baseline_winter_peak_mw"), 0.0) or 0.0
    nameplate_mva = sum(
        _f(s.get("nameplate_mva"), 0.0) or 0.0
        for s in (network.get("substations") or [])
    )
    # Approximate: MVA ≈ MW at unity power factor for residential winter peak.
    headroom_mw = nameplate_mva - projected if nameplate_mva > 0 else None
    headroom_pct = (headroom_mw / nameplate_mva * 100.0) if (nameplate_mva and headroom_mw is not None) else None

    # Pre-formatted narration string. The chat model is instructed to copy
    # this verbatim as sentence 1 of its reply — that sidesteps the failure
    # mode where the model reads `projected_peak_mw` and `headroom_mw` from
    # the JSON output and accidentally swaps the labels when narrating
    # ("peak climbs to <headroom value>" instead of "<projected value>").
    projected_str = f"{projected:,.0f}"
    headroom_str = f"{headroom_mw:,.0f}" if headroom_mw is not None else "n/a"
    headroom_pct_str = f"{headroom_pct:.1f}%" if headroom_pct is not None else "n/a"
    pass_or_fail = "still a pass" if (headroom_mw or 0) > 0 else "overshoots safe capacity"
    narration = (
        f"At {hp_pct*100:.0f}% HP / {ev_pct*100:.0f}% EV the network peaks "
        f"at {projected_str} MW, leaving {headroom_str} MW of headroom "
        f"({headroom_pct_str} of nameplate), {pass_or_fail}"
    )

    return {
        "anchor_scenario_name": anchor_spec.get("name"),
        "anchor_hp_pct": anchor_hp,
        "anchor_ev_pct": anchor_ev,
        "new_hp_pct": hp_pct,
        "new_ev_pct": ev_pct,
        "projected_peak_mw": round(projected, 1),
        "baseline_winter_peak_mw": round(baseline_peak, 1),
        "growth_vs_baseline_mw": round(projected - baseline_peak, 1) if baseline_peak else None,
        "growth_vs_baseline_pct": round((projected - baseline_peak) / baseline_peak * 100.0, 1) if baseline_peak else None,
        "network_nameplate_mva": round(nameplate_mva, 1) if nameplate_mva else None,
        "headroom_mw": round(headroom_mw, 1) if headroom_mw is not None else None,
        "headroom_pct": round(headroom_pct, 1) if headroom_pct is not None else None,
        "peak_hour_offset": peak_hour,
        "peak_temp_c": peak_temp,
        "method": method,
        "narration": narration,
        "note": (
            "Linear extrapolation from the nearest scenario in the persisted "
            "report. Not a fresh simulator run. Accuracy degrades the further "
            "the requested percentages drift from the anchor scenario."
        ),
    }


# ── Tool 2: Electrification — recompute_readiness ──────────────────────── #

def _recompute_readiness(args: dict, result: dict) -> dict:
    """Re-project FSA readiness under new HP/EV % adoption.

    Strategy: each FSA already has multiple scored scenarios. For each FSA,
    pick the closest scenario, scale ``incremental_peak_mw`` linearly, and
    derate ``grid_score`` proportional to the load growth.
    """
    hp_pct = _f(args.get("hp_pct"))
    ev_pct = _f(args.get("ev_pct"))
    fsa_filter = (args.get("fsa") or "").strip().upper() or None
    if hp_pct is None or ev_pct is None:
        return {"error": "Both hp_pct and ev_pct are required (0.0–1.0)."}
    hp_pct = _clamp(hp_pct, 0.0, 1.0)
    ev_pct = _clamp(ev_pct, 0.0, 1.0)

    outcomes = result.get("fsa_outcomes") or []
    if not outcomes:
        return {"error": "Report has no FSA outcomes."}

    # Bucket outcomes by FSA so we can pick the closest scenario per FSA.
    by_fsa: dict[str, list[dict]] = {}
    for o in outcomes:
        fsa = ((o.get("profile") or {}).get("fsa") or "").upper()
        if not fsa:
            continue
        by_fsa.setdefault(fsa, []).append(o)

    target_fsas = [fsa_filter] if fsa_filter and fsa_filter in by_fsa else sorted(by_fsa.keys())
    if fsa_filter and fsa_filter not in by_fsa:
        return {"error": f"FSA '{fsa_filter}' is not in the report. Available: {sorted(by_fsa.keys())}"}

    per_fsa: list[dict] = []
    for fsa in target_fsas:
        bucket = by_fsa[fsa]

        def _dist(o: dict) -> float:
            sc = o.get("scenario") or {}
            a = _f(sc.get("heat_pump_conversion_pct"), 0.0) or 0.0
            b = _f(sc.get("ev_adoption_pct"), 0.0) or 0.0
            return (a - hp_pct) ** 2 + (b - ev_pct) ** 2

        anchor = _nearest_by(bucket, _dist) or bucket[0]
        sc = anchor.get("scenario") or {}
        li = anchor.get("load_impact") or {}
        rd = anchor.get("readiness") or {}
        a_hp = _f(sc.get("heat_pump_conversion_pct"), 0.0) or 0.0
        a_ev = _f(sc.get("ev_adoption_pct"), 0.0) or 0.0
        a_peak_mw = _f(li.get("incremental_peak_mw"), 0.0) or 0.0

        # Linear scale of the HP-attributable and EV-attributable shares.
        hp_share = (a_hp / max(a_hp + a_ev, 1e-6)) * a_peak_mw
        ev_share = a_peak_mw - hp_share
        new_hp_mw = hp_share * (hp_pct / max(a_hp, 1e-6)) if a_hp > 0 else 0.0
        new_ev_mw = ev_share * (ev_pct / max(a_ev, 1e-6)) if a_ev > 0 else 0.0
        projected_peak_mw = new_hp_mw + new_ev_mw

        # Derate grid_score proportional to load growth vs. anchor.
        anchor_grid = _f(rd.get("grid_score"), 0.5) or 0.5
        growth_ratio = (projected_peak_mw / a_peak_mw) if a_peak_mw > 0 else 1.0
        new_grid = _clamp(anchor_grid / max(growth_ratio, 1e-6), 0.0, 1.0)
        # Other dimensions move modestly; affordability follows household upgrade burden.
        anchor_overall = _f(rd.get("overall_score"), 0.5) or 0.5
        overall_delta = (new_grid - anchor_grid) * 0.5  # grid weighted ~50% of overall
        new_overall = _clamp(anchor_overall + overall_delta, 0.0, 1.0)

        if new_overall >= 0.66:
            verdict = "READY"
        elif new_overall >= 0.40:
            verdict = "CONSTRAINED"
        else:
            verdict = "BLOCKED"

        per_fsa.append({
            "fsa": fsa,
            "anchor_scenario": sc.get("name"),
            "anchor_hp_pct": a_hp,
            "anchor_ev_pct": a_ev,
            "anchor_incremental_peak_mw": round(a_peak_mw, 2),
            "anchor_grid_score": round(anchor_grid, 2),
            "anchor_overall_score": round(anchor_overall, 2),
            "projected_incremental_peak_mw": round(projected_peak_mw, 2),
            "projected_grid_score": round(new_grid, 2),
            "projected_overall_score": round(new_overall, 2),
            "projected_verdict": verdict,
        })

    summary = None
    if len(per_fsa) > 1:
        avg_peak = sum(r["projected_incremental_peak_mw"] for r in per_fsa) / len(per_fsa)
        avg_overall = sum(r["projected_overall_score"] for r in per_fsa) / len(per_fsa)
        summary = {
            "fsa_count": len(per_fsa),
            "avg_projected_incremental_peak_mw": round(avg_peak, 2),
            "avg_projected_overall_score": round(avg_overall, 2),
            "blocked_count": sum(1 for r in per_fsa if r["projected_verdict"] == "BLOCKED"),
        }

    # Pre-formatted headline string — see `narration` rationale in
    # _recompute_winter_peak. Copying this verbatim avoids field-mixup.
    if summary:
        narration = (
            f"At {hp_pct*100:.0f}% HP / {ev_pct*100:.0f}% EV across "
            f"{summary['fsa_count']} FSAs, average readiness lands at "
            f"{summary['avg_projected_overall_score']:.2f} with "
            f"{summary['blocked_count']} FSA(s) tipping into BLOCKED "
            f"and an average +{summary['avg_projected_incremental_peak_mw']:.1f} "
            f"MW incremental peak"
        )
    elif per_fsa:
        f0 = per_fsa[0]
        narration = (
            f"At {hp_pct*100:.0f}% HP / {ev_pct*100:.0f}% EV, {f0['fsa']} "
            f"lands at readiness {f0['projected_overall_score']:.2f} "
            f"({f0['projected_verdict']}) with +"
            f"{f0['projected_incremental_peak_mw']:.1f} MW incremental peak"
        )
    else:
        narration = "No FSAs available to re-project."

    return {
        "new_hp_pct": hp_pct,
        "new_ev_pct": ev_pct,
        "per_fsa": per_fsa,
        "summary": summary,
        "narration": narration,
        "method": "linear scale of incremental peak + grid-score derating from the nearest persisted scenario",
        "note": "Linear extrapolation. Not a fresh adoption-model run. Accuracy degrades far from the anchor scenarios.",
    }


# ── Tool 3: Expansion — recompute_expansion ────────────────────────────── #

def _recompute_expansion(args: dict, result: dict) -> dict:
    """Re-pick the funded set under a different target MW + brownfield bias."""
    target_mw = _f(args.get("target_mw"))
    if target_mw is None or target_mw <= 0:
        return {"error": "target_mw is required (positive number)."}
    prefer_brownfield = bool(args.get("prefer_brownfield", True))

    options = result.get("options") or []
    if not options:
        return {"error": "Report has no scored options."}

    def _adj_score(opt: dict) -> float:
        s = _f(opt.get("overall_score"), 0.0) or 0.0
        if prefer_brownfield and opt.get("option_type") == "brownfield":
            s += 0.10
        return s

    ranked = sorted(options, key=_adj_score, reverse=True)
    selected: list[dict] = []
    total_mw = 0.0
    total_capex = 0.0
    weighted_carbon_num = 0.0
    for opt in ranked:
        mw = _f(opt.get("new_capacity_mw"), 0.0) or 0.0
        if mw <= 0:
            continue
        selected.append({
            "option_id": opt.get("option_id"),
            "option_type": opt.get("option_type"),
            "title": opt.get("title"),
            "new_capacity_mw": mw,
            "capex_cad": _f(opt.get("capex_cad"), 0.0),
            "overall_score": _f(opt.get("overall_score"), 0.0),
            "avg_carbon_g_kwh": _f(opt.get("avg_carbon_g_kwh"), 0.0),
        })
        total_mw += mw
        total_capex += _f(opt.get("capex_cad"), 0.0) or 0.0
        weighted_carbon_num += (_f(opt.get("avg_carbon_g_kwh"), 0.0) or 0.0) * mw
        if total_mw >= target_mw:
            break

    blended_carbon = (weighted_carbon_num / total_mw) if total_mw > 0 else None
    coverage_pct = (total_mw / target_mw * 100.0) if target_mw > 0 else None

    # Pre-formatted headline. Copy verbatim as sentence 1 to avoid swapping
    # capex / carbon / coverage values in narration.
    capex_str = (
        f"${total_capex/1e9:.2f}B" if total_capex >= 1e9
        else f"${total_capex/1e6:.0f}M"
    )
    carbon_str = f"{blended_carbon:.0f} g/kWh" if blended_carbon is not None else "n/a"
    coverage_str = f"{coverage_pct:.0f}% of target" if coverage_pct is not None else "n/a"
    bias_str = "brownfield-biased" if prefer_brownfield else "greenfield-biased"
    narration = (
        f"At a {target_mw:.0f} MW {bias_str} target the plan funds "
        f"{round(total_mw, 1):,.0f} MW at {capex_str} ({carbon_str} "
        f"blended), {coverage_str}"
    )

    return {
        "target_mw": target_mw,
        "prefer_brownfield": prefer_brownfield,
        "selected": selected,
        "total_new_capacity_mw": round(total_mw, 1),
        "total_capex_cad": round(total_capex, 0),
        "blended_carbon_g_kwh": round(blended_carbon, 1) if blended_carbon is not None else None,
        "coverage_pct": round(coverage_pct, 1) if coverage_pct is not None else None,
        "narration": narration,
        "method": "greedy by overall_score (brownfield bonus +0.10 when prefer_brownfield)",
    }


# ── Tool 4: Investment — reoptimize_portfolio ──────────────────────────── #

def _reoptimize_portfolio(args: dict, result: dict) -> dict:
    """Re-run the greedy ROI knapsack with a new budget."""
    budget = _f(args.get("budget_cad"))
    if budget is None or budget <= 0:
        return {"error": "budget_cad is required (positive number, in CAD)."}

    spec = result.get("spec") or {}
    horizon = int(_f(spec.get("horizon_years"), 5) or 5)
    candidates = result.get("candidate_projects") or []
    if not candidates:
        return {"error": "Report has no candidate projects."}

    def _roi(p: dict) -> float:
        capex = _f(p.get("capex_cad"), 0.0) or 0.0
        if capex <= 0:
            return 0.0
        annual = _f(p.get("risk_reduction_cad_per_year"), 0.0) or 0.0
        return (annual * horizon) / capex

    ranked = sorted(candidates, key=_roi, reverse=True)

    funded: list[dict] = []
    total_capex = 0.0
    total_annual_avoided = 0.0
    total_customers = 0
    for p in ranked:
        capex = _f(p.get("capex_cad"), 0.0) or 0.0
        if capex <= 0 or total_capex + capex > budget:
            continue
        funded.append({
            "project_id": p.get("project_id"),
            "title": p.get("title"),
            "category": p.get("category"),
            "capex_cad": capex,
            "risk_reduction_cad_per_year": _f(p.get("risk_reduction_cad_per_year"), 0.0),
            "customers_protected": int(_f(p.get("customers_protected"), 0) or 0),
            "roi_ratio": round(_roi(p), 2),
            "hazards_addressed": p.get("hazards_addressed") or [],
        })
        total_capex += capex
        total_annual_avoided += _f(p.get("risk_reduction_cad_per_year"), 0.0) or 0.0
        total_customers += int(_f(p.get("customers_protected"), 0) or 0)

    portfolio_roi = ((total_annual_avoided * horizon) / total_capex) if total_capex > 0 else None

    # Pre-formatted headline. Copy verbatim as sentence 1 to avoid swapping
    # budget / capex / roi values in narration.
    budget_str = (
        f"${budget/1e9:.2f}B" if budget >= 1e9
        else f"${budget/1e6:.0f}M"
    )
    capex_str = (
        f"${total_capex/1e9:.2f}B" if total_capex >= 1e9
        else f"${total_capex/1e6:.0f}M"
    )
    roi_str = f"{portfolio_roi:.2f}×" if portfolio_roi is not None else "n/a"
    narration = (
        f"At a {budget_str} budget the portfolio funds {len(funded)} "
        f"project(s), commits {capex_str}, protects "
        f"{total_customers:,} customers, and returns {roi_str} lifetime ROI"
    )

    return {
        "budget_cad": budget,
        "horizon_years": horizon,
        "funded_projects": funded,
        "funded_count": len(funded),
        "total_capex_committed_cad": round(total_capex, 0),
        "total_annual_loss_avoided_cad": round(total_annual_avoided, 0),
        "customers_protected": total_customers,
        "portfolio_roi_ratio": round(portfolio_roi, 2) if portfolio_roi is not None else None,
        "budget_utilization_pct": round(total_capex / budget * 100.0, 1) if budget else None,
        "narration": narration,
        "method": "greedy by ROI = (annual loss avoided × horizon_years) / capex",
    }


# ── Tool 5: Siting — filter_siting_candidates ──────────────────────────── #

def _filter_siting_candidates(args: dict, result: dict) -> dict:
    """Re-filter the ranked siting candidates by ad-hoc constraints."""
    region = (args.get("region") or "").strip().upper() or None
    max_deploy = _f(args.get("max_deployment_months"))
    max_lcoe = _f(args.get("max_lcoe_usd_mwh"))
    min_cap = _f(args.get("min_capacity_mw"))

    candidates = result.get("top_candidates") or []
    if not candidates:
        return {"error": "Report has no ranked candidates."}

    def _passes(c: dict) -> tuple[bool, str | None]:
        if region and (c.get("region_iso") or "").upper() != region:
            return False, "region"
        prof = (c.get("site") or {}).get("profile") or {}
        if max_deploy is not None:
            dm = _f(prof.get("deployment_months"))
            if dm is None or dm > max_deploy:
                return False, "deployment_months"
        if max_lcoe is not None:
            lcoe = _f(c.get("levelized_cost_usd_mwh"))
            if lcoe is None or lcoe > max_lcoe:
                return False, "max_lcoe"
        if min_cap is not None:
            cap = _f(prof.get("capacity_mw"))
            if cap is None or cap < min_cap:
                return False, "min_capacity"
        return True, None

    passing: list[dict] = []
    for c in candidates:
        ok, _why = _passes(c)
        if not ok:
            continue
        site = c.get("site") or {}
        prof = site.get("profile") or {}
        passing.append({
            "rank_original": c.get("rank"),
            "site_name": site.get("name"),
            "region_iso": c.get("region_iso"),
            "latitude": site.get("latitude"),
            "longitude": site.get("longitude"),
            "levelized_cost_usd_mwh": _f(c.get("levelized_cost_usd_mwh")),
            "capacity_mw": _f(prof.get("capacity_mw")),
            "deployment_months": _f(prof.get("deployment_months")),
            "fiber_latency_ms": _f(prof.get("fiber_latency_ms")),
            "transmission_headroom_mw": _f(prof.get("transmission_headroom_mw")),
        })

    # Pre-formatted headline. Copy verbatim as sentence 1 to avoid swapping
    # LCOE / capacity / deployment values in narration.
    constraints: list[str] = []
    if region:
        constraints.append(region)
    if max_deploy is not None:
        constraints.append(f"deploy ≤ {max_deploy:.0f} mo")
    if max_lcoe is not None:
        constraints.append(f"LCOE ≤ ${max_lcoe:.0f}/MWh")
    if min_cap is not None:
        constraints.append(f"≥ {min_cap:.0f} MW")
    constraint_str = ", ".join(constraints) or "no filters"
    if passing:
        top = passing[0]
        narration = (
            f"With {constraint_str}, {len(passing)} of {len(candidates)} "
            f"candidates pass. Top pick is {top['site_name']} "
            f"({top['region_iso']}) at ${top['levelized_cost_usd_mwh']:.0f}/MWh, "
            f"{top['capacity_mw']:.0f} MW, "
            f"{top['deployment_months']:.0f}-month deploy"
        )
    else:
        narration = (
            f"With {constraint_str}, no candidates pass. Relax one "
            f"of the constraints to find a fit"
        )

    return {
        "filters": {
            "region": region,
            "max_deployment_months": max_deploy,
            "max_lcoe_usd_mwh": max_lcoe,
            "min_capacity_mw": min_cap,
        },
        "passing_count": len(passing),
        "total_candidates": len(candidates),
        "passing_candidates": passing[:7],  # cap the payload size
        "top_candidate": passing[0] if passing else None,
        "narration": narration,
        "method": "filter pre-ranked candidates; no re-scoring",
    }


# ── Tool registry ──────────────────────────────────────────────────────── #

_WINTER_TOOL = {
    "name": "recompute_winter_peak",
    "description": (
        "ALWAYS call this for any counterfactual on heat-pump or EV "
        "adoption %. Trigger phrases include 'what if HP hits X%', "
        "'what if heat pump adoption is Y%', 'at Z% adoption', 'if EV "
        "goes to N%', 'how does the peak change at K%'. Decomposes the "
        "peak hour into base + HP + backup-resistance + EV + other "
        "components, then linearly scales the HP/backup and EV shares "
        "to the new percentages, which gives the correct counterfactual "
        "peak. NEVER estimate the new peak load in your head when this "
        "tool is available; call it first, then narrate the result.\n\n"
        "NARRATION RULE: the tool result includes a `narration` field "
        "that pre-formats the headline finding in the correct shape (e.g. "
        "'At 50% HP / 30% EV the network peaks at 3,780 MW, leaving "
        "1,425 MW of headroom (27.4% of nameplate), still a pass'). "
        "Use that `narration` string verbatim as sentence 1 of your reply. "
        "Do NOT re-extract `projected_peak_mw` and `headroom_mw` from the "
        "JSON and re-label them yourself, since that has caused field-swap "
        "errors in the past where peak and headroom values got reversed. "
        "Sentence 2 can add one supporting fact (which feeders bear the "
        "load, comparison to the 30% case, etc.) followed by the "
        "'(first-order, linear-scaled from the X% anchor)' hedge.\n\n"
        "Do NOT call for questions about the existing report's scenarios, "
        "methodology, definitions, mitigations, or comparisons between "
        "scenarios already in the report; those are already answered in "
        "the report context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "hp_pct": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Heat pump adoption share, 0.0–1.0 (e.g. 0.5 = 50%).",
            },
            "ev_pct": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "EV adoption share, 0.0–1.0.",
            },
        },
        "required": ["hp_pct", "ev_pct"],
    },
}

_ELECTRIFICATION_TOOL = {
    "name": "recompute_readiness",
    "description": (
        "ALWAYS call this for any counterfactual on heat-pump conversion "
        "% or EV adoption %. Trigger phrases include 'what if HP hits X%', "
        "'at Y% conversion', 'how does FSA Z fare at N% EV', 'what if "
        "adoption goes to K%'. Linearly scales the incremental peak and "
        "derates grid_score per FSA from the nearest persisted scenario. "
        "NEVER estimate the new readiness score in your head when this "
        "tool is available; call it first, then narrate the result.\n\n"
        "Do NOT call for questions about existing readiness numbers, "
        "blockers, interventions, or comparisons already in the report."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "hp_pct": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Heat pump conversion share, 0.0–1.0.",
            },
            "ev_pct": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "EV adoption share, 0.0–1.0.",
            },
            "fsa": {
                "type": "string",
                "description": "Optional FSA code (e.g. 'M5V'). If omitted, projects all FSAs in the report.",
            },
        },
        "required": ["hp_pct", "ev_pct"],
    },
}

_EXPANSION_TOOL = {
    "name": "recompute_expansion",
    "description": (
        "ALWAYS call this for any counterfactual on target capacity or "
        "brownfield/greenfield bias. Trigger phrases include 'what if we "
        "needed X MW instead', 'what if the target were Y MW', 'what if "
        "we only used brownfield', 'what if greenfield only'. Re-runs the "
        "greedy selection against the report's pre-scored options. NEVER "
        "estimate the new funded set or capex total in your head when "
        "this tool is available; call it first, then narrate the result.\n\n"
        "Do NOT call for questions about the existing funded set, "
        "individual option scores, or carbon; those are in the report."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "target_mw": {
                "type": "number",
                "exclusiveMinimum": 0.0,
                "description": "New target additional capacity in MW.",
            },
            "prefer_brownfield": {
                "type": "boolean",
                "description": "If true, brownfield options get a +0.10 score bonus. Default true.",
            },
        },
        "required": ["target_mw"],
    },
}

_INVESTMENT_TOOL = {
    "name": "reoptimize_portfolio",
    "description": (
        "ALWAYS call this for any counterfactual on the total budget. "
        "Trigger phrases include 'what if the budget were $X', 'at $Y "
        "instead', 'how does the portfolio change at $Z', 'what if we "
        "had $N more/less', 'what would $K buy'. Re-runs the greedy ROI "
        "knapsack against the report's candidate projects with the new "
        "budget. NEVER estimate the new funded set, committed capex, or "
        "portfolio ROI in your head when this tool is available; call "
        "it first, then narrate the result.\n\n"
        "Do NOT call for questions about which projects are funded today, "
        "individual project scores, ROI, or hazards; those are in the "
        "report."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "budget_cad": {
                "type": "number",
                "exclusiveMinimum": 0.0,
                "description": "Total budget in CAD.",
            },
        },
        "required": ["budget_cad"],
    },
}

_SITING_TOOL = {
    "name": "filter_siting_candidates",
    "description": (
        "ALWAYS call this when the user adds a NEW constraint not already "
        "in the report. Region, deployment speed, LCOE ceiling, or "
        "capacity floor. Trigger phrases include 'only in Quebec', 'only "
        "sites under X months', 'only under $Y/MWh', 'at least Z MW', "
        "'cheapest in region W', 'fastest to deploy'. Re-filters the "
        "ranked candidates and returns the new top pick. NEVER guess the "
        "new top candidate or its LCOE in your head when this tool is "
        "available; call it first, then narrate the result.\n\n"
        "Do NOT call for questions about the existing top candidates, "
        "region insights, methodology, or explanations; those are in "
        "the report."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "region": {
                "type": "string",
                "description": "ISO region code to keep (e.g. 'QC', 'ON', 'AB').",
            },
            "max_deployment_months": {
                "type": "number",
                "exclusiveMinimum": 0.0,
                "description": "Drop any candidate whose deployment_months exceeds this.",
            },
            "max_lcoe_usd_mwh": {
                "type": "number",
                "exclusiveMinimum": 0.0,
                "description": "Drop any candidate whose levelized cost exceeds this ($/MWh).",
            },
            "min_capacity_mw": {
                "type": "number",
                "exclusiveMinimum": 0.0,
                "description": "Drop any candidate whose site capacity is below this (MW).",
            },
        },
    },
}


TOOLS_BY_PIPELINE: dict[str, list[dict]] = {
    "winter-peak-stress":         [_WINTER_TOOL],
    "electrification-readiness":  [_ELECTRIFICATION_TOOL],
    "datacenter-expansion":       [_EXPANSION_TOOL],
    "grid-investment-optimizer":  [_INVESTMENT_TOOL],
    "datacenter-siting":          [_SITING_TOOL],
}


_HANDLERS = {
    "recompute_winter_peak":     _recompute_winter_peak,
    "recompute_readiness":       _recompute_readiness,
    "recompute_expansion":       _recompute_expansion,
    "reoptimize_portfolio":      _reoptimize_portfolio,
    "filter_siting_candidates":  _filter_siting_candidates,
}


def get_tools_for_pipeline(pipeline_id: str | None) -> list[dict]:
    """Return the tool definitions Claude should see for this pipeline.
    Empty list = no tools = legacy chat behaviour."""
    if not pipeline_id:
        return []
    return TOOLS_BY_PIPELINE.get(pipeline_id, [])


def handle_tool_call(tool_name: str, args: dict, result: dict) -> dict:
    """Dispatch a tool_use block to its handler. Returns a dict that will be
    JSON-serialised and handed back to Claude as tool_result content."""
    handler = _HANDLERS.get(tool_name)
    if handler is None:
        return {"error": f"Unknown tool '{tool_name}'."}
    try:
        return handler(args or {}, result or {})
    except Exception as exc:
        return {"error": f"Tool handler failed: {exc.__class__.__name__}: {exc}"}


# ── Tool-result → reconciliation facts ─────────────────────────────────── #
#
# When a counterfactual tool fires, its output is the new ground truth
# for *this chat turn*. Without remapping, the post-stream `reconcile()`
# pass would still anchor on the frozen report's worst-scenario peak —
# snapping a legitimate "+50% HP pushes the peak to ~3,710 MW" answer
# back to the report's 30%-anchor value of 3,387 MW and producing the
# "feels dumb" failure mode the user flagged.
#
# Keys MUST match the entries in `_DEFAULT_CONTEXT_HINTS` in
# `utils/reconciliation.py`; anything else is silently ignored.

def tool_result_to_facts(tool_name: str, output: dict) -> dict[str, float]:
    """Translate a tool's output into reconciliation fact keys.

    The chat router merges these on top of the frozen-report facts so
    `reconcile()` guards the *counterfactual* number rather than
    overwriting it with the original report value.

    Returns {} on tool errors or unknown tool names — caller should
    treat an empty dict as "no override; reconcile against the report".
    """
    if not isinstance(output, dict) or output.get("error"):
        return {}

    facts: dict[str, float] = {}

    if tool_name == "recompute_winter_peak":
        peak = _f(output.get("projected_peak_mw"))
        if peak is not None:
            # Only the peak-load fact. Skipped on purpose:
            #   - demand_gw: hint "load" is too broad and matched
            #     unrelated phrases like "the added load most likely
            #     to stress…", rewriting feeder ID digits to a GW value.
            #   - headroom_mw: hint "headroom" sat 50 chars away from
            #     unrelated numbers (the inter-scenario delta, etc.),
            #     causing false-positive rewrites. The pre-formatted
            #     `narration` string in the tool output is what the
            #     model copies verbatim, so it doesn't need reconciler
            #     enforcement on the headroom value itself.
            facts["peak_load_mw"] = peak

    elif tool_name == "recompute_readiness":
        summary = output.get("summary") or {}
        avg_overall = _f(summary.get("avg_projected_overall_score"))
        if avg_overall is not None:
            facts["overall_score"] = avg_overall

    elif tool_name == "recompute_expansion":
        cap = _f(output.get("total_new_capacity_mw"))
        if cap is not None:
            facts["capacity_mw"] = cap
        carbon = _f(output.get("blended_carbon_g_kwh"))
        if carbon is not None:
            facts["carbon_intensity_g_per_kwh"] = carbon

    elif tool_name == "reoptimize_portfolio":
        budget = _f(output.get("budget_cad"))
        if budget is not None:
            facts["budget_cad"] = budget
        committed = _f(output.get("total_capex_committed_cad"))
        if committed is not None:
            facts["total_capex_committed_cad"] = committed
        protected = _f(output.get("customers_protected"))
        if protected is not None:
            facts["customers_protected"] = protected

    elif tool_name == "filter_siting_candidates":
        top = output.get("top_candidate") or {}
        lcoe = _f(top.get("levelized_cost_usd_mwh"))
        if lcoe is not None:
            facts["lcoe_usd_mwh"] = lcoe
        cap = _f(top.get("capacity_mw"))
        if cap is not None:
            facts["capacity_mw"] = cap

    return facts
