"""
Winter Synthesis Agent — Stage 5 of the Winter Peak pipeline.

Combines the per-scenario simulation outputs and per-feeder risks into
a final ResiliencePlan with executive summary, scenario verdicts, and
ranked mitigation recommendations.
"""
from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.models.winter_peak import (
    ColdEvent,
    DistributionNetwork,
    Mitigation,
    ResiliencePlan,
    ScenarioOutcome,
    WinterPeakSpec,
)
from backend.utils.reconciliation import reconcile


SYSTEM_WINTER_SYNTHESIS = """You are a senior grid resilience consultant
writing an executive briefing for a utility planning team. Be specific
with numbers (MW, hours, customer counts), honest about limitations,
and prescriptive about next steps. Avoid jargon. Avoid hyperbole.
Output exactly the JSON shape requested. No markdown.""" + GROUNDING_RULES


class WinterSynthesisAgent(BaseAgent):
    """Stage 5: scenario outcomes → ResiliencePlan."""

    async def synthesize(
        self,
        job_id: str,
        spec: WinterPeakSpec,
        cold_event: ColdEvent,
        network: DistributionNetwork,
        scenario_outcomes: list[ScenarioOutcome],
        progress_callback=None,
    ) -> ResiliencePlan:
        """Generate the final synthesized report."""
        if progress_callback:
            await progress_callback("Generating executive resilience report...", 88)

        # Determine each scenario's verdict from worst-of (per-feeder risk,
        # per-substation risk, system headroom). Aggregate headroom alone
        # masks single-feeder overloads — a grid fails when any feeder
        # cooks, not when the network mean is fine.
        for outcome in scenario_outcomes:
            outcome.summary_verdict = self._verdict_for_outcome(outcome)
            outcome.headline = self._headline(outcome)
            outcome.notable_failures = self._notable_failures(outcome)

        # Generate Claude-driven narrative + mitigations
        report_payload = self._build_payload(spec, cold_event, network, scenario_outcomes)
        narrative = await self._generate_narrative(report_payload)

        exec_summary = narrative.get("executive_summary", "")

        # Pattern 3 — reconcile Claude's exec summary against simulation facts.
        # If Claude drifts from the deterministic simulator's values by >10%,
        # the wrong number is rewritten with the simulator's value.
        if scenario_outcomes:
            worst = max(scenario_outcomes, key=lambda o: o.load_profile.peak_load_mw or 0)
            recon_facts = {
                "demand_gw": (worst.load_profile.peak_load_mw or 0.0) / 1000.0,
                "capacity_mw": worst.load_profile.peak_load_mw or 0.0,
            }
            exec_summary = reconcile(exec_summary, recon_facts).corrected_text

        # If the synthesis Claude call hit max_tokens, push a clear safety flag
        # so the operator sees the narrative may have been clipped (vs. a
        # silently-truncated mitigations array). Counter accumulates across
        # every ask_claude on this agent instance; see base_agent.
        safety_flags = list(narrative.get("safety_flags", []))
        if self.had_truncation():
            safety_flags.append(
                f"{self._truncation_count} Claude response(s) hit the max_tokens "
                "cap during synthesis, so executive summary or mitigations may be "
                "incomplete. Raise the cap in REPORTS_COHESION.md §8b and re-run."
            )

        plan = ResiliencePlan(
            job_id=job_id,
            spec=spec,
            cold_event=cold_event,
            network=network,
            scenarios=scenario_outcomes,
            mitigations=self._parse_mitigations(narrative.get("mitigations", []), scenario_outcomes),
            executive_summary=exec_summary,
            methodology_notes=narrative.get("methodology_notes", self._default_methodology()),
            safety_flags=safety_flags,
            limitations=narrative.get("limitations", self._default_limitations(network)),
        )

        if progress_callback:
            await progress_callback("Resilience plan complete", 100)

        return plan

    # ── Verdict + headline helpers ────────────────────────────────────── #

    def _verdict_for_outcome(self, outcome: ScenarioOutcome) -> str:
        """
        Verdict = worst of three signals:
          (a) any feeder past its thermal limit          → FAIL
          (b) any substation aggregate-stressed          → FAIL
          (c) system-level headroom collapsed            → FAIL

        System thresholds are tighter than the old 20% PASS floor: the
        synthesized substations are already sized at 1.35× today's peak
        ([feeder_topology._build_substations]), so demanding *another*
        20% on top of that double-counts safety and lets every scenario
        coast to PASS. IESO operates with ~13-16% reserve margin; 15%
        as the PASS floor and 5% as the FAIL floor matches that.

        overload_risk on a feeder ramps 0→1 linearly between 80% and
        120% capacity utilization ([feeder_risk._score_feeder]), so:
          ≥0.8 ≈ ≥116% util  →  thermal failure expected   → FAIL
          ≥0.4 ≈ ≥96% util   →  at the limit              → MARGINAL
        """
        headroom_pct = outcome.load_profile.headroom_pct_at_peak
        worst_feeder = max(
            (fr.overload_risk for fr in outcome.feeder_risks), default=0.0
        )
        worst_sub = max(
            (s.aggregate_risk for s in outcome.substation_risks), default=0.0
        )

        if worst_feeder >= 0.8 or worst_sub >= 0.8 or headroom_pct < 5:
            return "FAIL"
        if worst_feeder >= 0.4 or worst_sub >= 0.4 or headroom_pct < 15:
            return "MARGINAL"
        return "PASS"

    def _headline(self, outcome: ScenarioOutcome) -> str:
        v = outcome.summary_verdict
        h = outcome.load_profile.headroom_pct_at_peak
        peak = outcome.load_profile.peak_load_mw
        n_overloaded = sum(1 for fr in outcome.feeder_risks if fr.overload_risk >= 0.8)
        n_stressed = sum(1 for fr in outcome.feeder_risks if 0.4 <= fr.overload_risk < 0.8)

        if v == "FAIL":
            if n_overloaded:
                return (
                    f"Network fails. {n_overloaded} feeder(s) past thermal limit; "
                    f"system peaks at {peak:.0f} MW ({h:.0f}% headroom)."
                )
            # System-aggregate-driven FAIL (no feeder triggered) — h is < 5%.
            if h < 0:
                return f"Network fails. Peaks at {peak:.0f} MW, {abs(h):.0f}% over capacity."
            return f"Network fails. Peaks at {peak:.0f} MW with only {h:.0f}% headroom."
        if v == "MARGINAL":
            if n_stressed or n_overloaded:
                return (
                    f"Network strained. {n_stressed + n_overloaded} feeder(s) at or "
                    f"past capacity; peak {peak:.0f} MW ({h:.0f}% system headroom)."
                )
            return f"Network strained. Peaks at {peak:.0f} MW with only {h:.0f}% headroom."
        return f"Network holds. Peaks at {peak:.0f} MW with {h:.0f}% headroom; no feeders overloaded."

    def _notable_failures(self, outcome: ScenarioOutcome) -> list[str]:
        items = []
        at_risk_feeders = [fr for fr in outcome.feeder_risks if fr.overload_risk >= 0.7]
        if at_risk_feeders:
            items.append(f"{len(at_risk_feeders)} feeder(s) over 70% overload risk.")
        critical_subs = [s for s in outcome.substation_risks if s.aggregate_risk >= 0.7]
        if critical_subs:
            items.append(f"{len(critical_subs)} substation(s) showing aggregate failure risk.")
        if outcome.load_profile.headroom_at_peak_mw < 0:
            items.append(
                f"Peak load exceeds nameplate by "
                f"{abs(outcome.load_profile.headroom_at_peak_mw):.0f} MW."
            )
        return items

    # ── Payload + narrative ────────────────────────────────────────────── #

    def _build_payload(
        self,
        spec: WinterPeakSpec,
        cold_event: ColdEvent,
        network: DistributionNetwork,
        scenario_outcomes: list[ScenarioOutcome],
    ) -> dict:
        return {
            "city": spec.city,
            "utility": spec.utility,
            "province": spec.province,
            "cold_event": {
                "name": cold_event.name,
                "min_temp_c": cold_event.min_temp_c,
                "duration_hours": cold_event.duration_hours,
            },
            "network": {
                "substations": len(network.substations),
                "feeders": len(network.feeders),
                "customers": sum(f.customer_count for f in network.feeders),
                "baseline_winter_peak_mw": network.baseline_winter_peak_mw,
                "is_synthesized": network.is_synthesized,
            },
            "scenarios": [
                {
                    "name": o.scenario.name,
                    "label": o.scenario.label,
                    "hp_pct": o.scenario.heat_pump_adoption_pct,
                    "ev_pct": o.scenario.ev_adoption_pct,
                    "peak_mw": o.load_profile.peak_load_mw,
                    "peak_hour": o.load_profile.peak_hour_offset,
                    "peak_temp_c": o.load_profile.peak_temp_c,
                    "headroom_mw": o.load_profile.headroom_at_peak_mw,
                    "headroom_pct": o.load_profile.headroom_pct_at_peak,
                    "verdict": o.summary_verdict,
                    "at_risk_feeders": sum(1 for fr in o.feeder_risks if fr.overload_risk >= 0.5),
                    "top_3_at_risk_feeders": [
                        {
                            "feeder_id": fr.feeder_id,
                            "name": fr.feeder_name,
                            "utilization_pct": fr.capacity_utilization_pct,
                            "rationale": fr.rationale,
                        }
                        for fr in o.feeder_risks[:3]
                    ],
                }
                for o in scenario_outcomes
            ],
        }

    async def _generate_narrative(self, payload: dict) -> dict:
        prompt = f"""Generate the resilience report narrative as JSON. Input:

{payload}

Return JSON shape:
{{
  "executive_summary": "4-5 paragraph markdown. Open with '# Executive Summary: <one-line topic>'. Each paragraph begins with '**<2-5 word bold title>**' on its own line, then a blank line, then the prose. Separate paragraphs with blank lines only. Do NOT insert '---' or any horizontal-rule dividers, and do NOT use markdown tables (the renderer does not display them). Paragraph 1: headline finding (verdict and one-sentence why). Paragraph 2: most important supporting evidence (which scenarios failed or passed and by how much). Paragraph 3: at-risk assets and customers. Paragraph 4: caveats and limitations. Paragraph 5: recommended next action. Write for a utility executive who will skim, in plain English, no jargon. Avoid em dashes anywhere in the prose, use commas, periods, or parentheses instead.",
  "methodology_notes": "2-3 sentence methodology. Mention the deterministic load model, the COP-adjusted heat pump curves, and that per-feeder values are modeled (if synthesized).",
  "safety_flags": ["..."],  // 0-3 plain-English risk flags relevant to public safety (medical devices, vulnerable populations)
  "limitations": ["..."],  // 1-3 honest caveats about the analysis
  "mitigations": [
    {{
      "title": "Demand response on top 5 feeders",
      "category": "demand_response | transformer_upgrade | feeder_reconductor | load_shift",
      "estimated_load_relief_mw": 8.5,
      "estimated_cost_cad": 250000,
      "deployment_months": 6,
      "risk_reduction_pct": 25,
      "rationale": "..."
    }}
  ]
}}

Mitigation guidance:
  - Always include 3-5 mitigations.
  - Mix categories: at least one demand-side (DR / load shift) and one
    capital (upgrade / reconductor) option.
  - Targeted, specific costs in CAD. Be conservative: typical Canadian
    feeder reconductor is $0.5-2M per feeder; transformer upgrade is
    $1-5M; demand-response programs are $50-300/customer enrolled.
  - risk_reduction_pct is the percent reduction in aggregate peak risk."""

        try:
            # Observed: at 2500 the call truncated at ~9352 chars (≈2340 tokens)
            # mid-mitigation. The mitigations array (3-5 objects × 7 fields each
            # including verbose `rationale` strings) dominates the response size
            # and Claude can be unpredictably wordy. 3500 gives ~40% headroom
            # over the largest observed run. If you see truncation in the
            # safety_flags block again, either bump further or split the call
            # into exec-summary-and-methodology + mitigations (two smaller asks).
            return await self.ask_claude_json(SYSTEM_WINTER_SYNTHESIS, prompt, max_tokens=3500)
        except Exception as e:
            # Anthropic 529s and other transient failures already got 3 retries
            # in base_agent. If we're here, the LLM is genuinely unavailable —
            # but the deterministic simulator data is complete, so we compose
            # a real executive summary and mitigations from it. The operator
            # still gets actionable output instead of an apologetic placeholder.
            self.logger.warning(
                "Narrative generation failed after retries (%s); "
                "falling back to deterministic templated summary.", e,
            )
            return self._deterministic_narrative(payload)

    def _deterministic_narrative(self, payload: dict) -> dict:
        """Compose a real exec summary from simulation data when Claude is
        unavailable.

        Per REPORTS_COHESION.md §0 (data provenance), every number in this
        fallback must come from the deterministic simulator — no invented
        cost / relief / deployment estimates. The exec-summary prose is
        templated from real scenario outputs; the mitigations array is
        left empty because mitigation economics require LLM synthesis
        (no real per-utility cost catalog exists for those fields).
        Honest limitation surfaced so the operator knows why the
        mitigations section is empty.
        """
        return {
            "executive_summary": self._templated_exec_summary(payload),
            "methodology_notes": self._default_methodology(),
            "safety_flags": [],
            "limitations": [
                "Executive summary was templated directly from simulation "
                "outputs because the LLM narrative service was unavailable; "
                "every figure in the summary comes from the deterministic "
                "stress test.",
                "Mitigation recommendations were skipped on this run. "
                "Mitigation cost, load-relief, and deployment estimates "
                "require LLM synthesis against domain knowledge. Re-run "
                "this pipeline once Anthropic capacity recovers to populate "
                "the mitigations table.",
            ],
            "mitigations": [],
        }

    def _templated_exec_summary(self, payload: dict) -> str:
        """Build a 5-paragraph markdown exec summary from simulation facts."""
        city = payload["city"]
        utility = payload["utility"]
        event = payload["cold_event"]
        network = payload["network"]
        scenarios = payload["scenarios"] or []

        worst = max(scenarios, key=lambda s: s["peak_mw"] or 0.0, default=None)
        passing = [s for s in scenarios if s["verdict"] == "PASS"]
        failing = [s for s in scenarios if s["verdict"] == "FAIL"]
        marginal = [s for s in scenarios if s["verdict"] == "MARGINAL"]

        if not worst:
            verdict_word, why = "INCONCLUSIVE", "no scenarios were simulated"
        elif failing:
            verdict_word = "FAIL"
            why = (
                f"{len(failing)} of {len(scenarios)} scenarios exceed nameplate "
                f"capacity during the {event['name']} cold event"
            )
        elif marginal:
            verdict_word = "MARGINAL"
            why = (
                f"{len(marginal)} of {len(scenarios)} scenarios leave under 20% "
                f"headroom at peak"
            )
        else:
            verdict_word = "PASS"
            why = f"all {len(scenarios)} scenarios stay within capacity"

        para1 = (
            f"**Headline verdict**\n\n"
            f"The {utility} distribution network in {city} returns **{verdict_word}** "
            f"against the {event['name']} stress test ({event['min_temp_c']:.0f}°C "
            f"for {event['duration_hours']:.0f} hours): {why}."
        )

        if worst:
            para2 = (
                f"**Worst-case scenario**\n\n"
                f"The {worst['label']} scenario peaks at "
                f"{worst['peak_mw']:.0f} MW with "
                f"{worst['headroom_pct']:+.0f}% headroom against nameplate. "
                f"Heat pump adoption of {worst['hp_pct']:.0f}% combined with "
                f"{worst['ev_pct']:.0f}% EV adoption drives the peak hour to "
                f"offset {worst['peak_hour']} of the event window."
            )
        else:
            para2 = "**Worst-case scenario**\n\nNo scenarios were simulated."

        total_at_risk = sum(s.get("at_risk_feeders", 0) for s in scenarios)
        para3 = (
            f"**At-risk assets**\n\n"
            f"Across all scenarios, {total_at_risk} feeder-scenario combinations "
            f"cross the 50% overload-risk threshold serving roughly "
            f"{network['customers']:,} customers on {network['feeders']} feeders. "
            f"Passing scenarios: {len(passing)}; marginal: {len(marginal)}; "
            f"failing: {len(failing)}."
        )

        para4 = (
            f"**Caveats**\n\n"
            f"Per-feeder topology is "
            + ("modeled from public utility filings"
               if network["is_synthesized"] else "drawn from utility records")
            + ". Heat pump COP curves use population averages; actual "
            f"installed-fleet mix varies by neighborhood. Mitigation "
            f"recommendations are not included on this run because the "
            f"LLM narrative service was unavailable."
        )

        if verdict_word == "FAIL":
            next_action = (
                "Prioritize transformer-headroom upgrades on the substations "
                "feeding the at-risk feeders and stand up a demand-response "
                "program for the next planning cycle."
            )
        elif verdict_word == "MARGINAL":
            next_action = (
                "Run a follow-on study on the marginal scenarios with localized "
                "weather inputs and validate per-feeder utilization against "
                "SCADA telemetry before committing capital."
            )
        else:
            next_action = (
                "Maintain the current capacity plan and re-run this stress test "
                "annually as electrification adoption updates."
            )
        para5 = f"**Recommended next action**\n\n{next_action}"

        return (
            f"# Executive Summary: {city} Winter Peak Stress Test\n\n"
            + "\n\n".join([para1, para2, para3, para4, para5])
        )


    def _parse_mitigations(self, raw: list[dict], scenario_outcomes: list[ScenarioOutcome]) -> list[Mitigation]:
        """Convert raw Claude mitigation dicts into Mitigation models."""
        # Use the worst-scenario at-risk feeders as default targets
        worst = max(
            scenario_outcomes,
            key=lambda o: o.load_profile.peak_load_mw,
            default=None,
        )
        default_targets = (
            [fr.feeder_id for fr in worst.feeder_risks[:5]] if worst else []
        )

        results = []
        for i, m in enumerate(raw):
            mid = f"M-{i+1:02d}"
            results.append(Mitigation(
                mitigation_id=mid,
                title=m.get("title", f"Mitigation {i+1}"),
                category=m.get("category", "demand_response"),
                targeted_feeders=m.get("targeted_feeders") or default_targets[:5],
                estimated_load_relief_mw=float(m.get("estimated_load_relief_mw") or 0),
                estimated_cost_cad=m.get("estimated_cost_cad"),
                deployment_months=m.get("deployment_months"),
                risk_reduction_pct=float(m.get("risk_reduction_pct") or 0),
                rationale=m.get("rationale", ""),
            ))
        return results

    def _default_methodology(self) -> str:
        return (
            "Hourly load simulation across the cold event window using "
            "NRCan-aligned heat pump COP curves, residential cold-weather EV "
            "draw factors, and a calibrated diurnal residential profile. "
            "Per-feeder values are modeled from public utility filings; the "
            "deterministic simulator drives risk scoring, with Claude generating "
            "per-feeder narrative rationales."
        )

    def _default_limitations(self, network: DistributionNetwork) -> list[str]:
        items = []
        if network.is_synthesized:
            items.append(
                "Per-feeder topology is modeled from public utility filings; "
                "actual asset condition data is not publicly available."
            )
        items.append(
            "Heat pump COP curves are population averages; actual installed "
            "fleet mix (standard vs cold-climate units) varies by neighborhood."
        )
        items.append(
            "Mitigation cost estimates are benchmark ranges for Canadian "
            "distribution work; real procurement varies with supply-chain conditions."
        )
        return items
