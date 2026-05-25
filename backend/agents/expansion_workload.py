"""
Stage 1 of Expansion Planner — query → ExpansionSpec.
"""
import re

from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.models.expansion import ExpansionSpec
from backend.services.operator_footprint import cities_in_catalog, lookup_city


SYSTEM = """You are a datacenter expansion-planning analyst. Your role is
to parse natural-language expansion requests into a structured spec.

Supported operators (use the canonical name):
  - eStruxture   (primary: QC)
  - Cologix      (primary: QC, also ON / BC)
  - Hyperion     (primary: AB)
  - Q-Scale      (primary: QC, AI-first)
  - Equinix      (primary: ON)

Supported workload mixes:
  - traditional   (cloud/SaaS absorption, ~12% CAGR)
  - ai_inference  (gen-AI inference, ~25% CAGR)
  - ai_training   (hyperscale GPU clusters, ~40% CAGR)
  - balanced      (mixed pipeline, ~22% CAGR)

Always respond with valid JSON. No markdown.""" + GROUNDING_RULES


def _mw_from_text(query: str) -> float | None:
    """Extract a target MW from the query (e.g. '+60 MW', '120MW', 'add 30 MW')."""
    m = re.search(r"\+?\s*(\d+(?:\.\d+)?)\s*(?:MW|mw|megawatt)", query)
    if m:
        return float(m.group(1))
    return None


def _years_from_text(query: str) -> int | None:
    m = re.search(r"(\d+)[- ]year|over\s+(\d+)\s+years", query)
    if m:
        return int(m.group(1) or m.group(2))
    return None


def _detect_city(query: str) -> str | None:
    """Scan the prompt for any city present in the operator footprint catalog.
    Returns the catalog's display casing (e.g. "Montréal") so downstream code
    can match the city against operator sites. Longest-name-first so multi-word
    cities like "Pointe-Claire" or "Beaver County" beat shorter substrings.

    Deterministic, case-insensitive, accent-folded — matches the §0 rule that
    routing decisions be data-derived rather than LLM-inferred.
    """
    if not query:
        return None
    haystack = re.sub(r"\s+", " ", query).strip().lower()
    haystack = (
        haystack
        .replace("é", "e").replace("è", "e").replace("ê", "e")
        .replace("à", "a").replace("â", "a")
        .replace("ô", "o").replace("ç", "c")
    )
    for city in cities_in_catalog():
        needle = (
            city.lower()
            .replace("é", "e").replace("è", "e").replace("ê", "e")
            .replace("à", "a").replace("â", "a")
            .replace("ô", "o").replace("ç", "c")
        )
        # Word-boundary match so "York" doesn't fire on "New York" later.
        if re.search(rf"(?<![\w\-]){re.escape(needle)}(?![\w\-])", haystack):
            return city
    return None


def _resolve_routing(
    llm_operator: str,
    detected_city: str | None,
) -> tuple[str, str | None, str | None, str]:
    """Apply city → operator/site routing against the catalog.

    Returns: (final_operator, city_or_none, target_site_id_or_none, routing_note)

    Routing rules (data-derived per REPORTS_COHESION.md §0):
      • No city detected → keep the LLM's operator, no pin, empty note.
      • City has exactly one operator owning a site there → that's the
        canonical operator. If the LLM picked someone else, override and
        record the override in routing_note. Pin target_site_id to the one
        site. (B + C unambiguous path.)
      • City has multiple operators → if the LLM's pick owns a site there,
        respect the LLM (a hint we can't disambiguate further); else pick
        the operator with the most sites in that city. No site pin.
      • City is in the catalog but no operator owns a site there → that's
        impossible given how cities_in_catalog() is built, so skip the
        defensive branch.
    """
    if not detected_city:
        return llm_operator, None, None, ""

    matches = lookup_city(detected_city)  # [(operator, site_id), ...]
    if not matches:
        return llm_operator, detected_city, None, ""

    operators = {op for op, _ in matches}

    # Unambiguous: single operator owns the named city.
    if len(operators) == 1:
        canonical = next(iter(operators))
        site_id = matches[0][1] if len(matches) == 1 else None
        if llm_operator.strip().lower() == canonical.strip().lower():
            # LLM agreed with the catalog — silent success.
            return canonical, detected_city, site_id, (
                f"User named {detected_city}; routed to {canonical}"
                + (f" ({site_id})" if site_id else "")
                + "."
            )
        # Override — surface as a routing_note so it lands in safety_flags.
        site_suffix = f" ({site_id})" if site_id else ""
        return canonical, detected_city, site_id, (
            f"User named {detected_city}; LLM picked {llm_operator} but "
            f"{canonical} is the only operator with a site in {detected_city}"
            f"{site_suffix}. Overrode operator to {canonical}."
        )

    # Ambiguous: multiple operators own the city.
    llm_owns = any(op.strip().lower() == llm_operator.strip().lower() for op in operators)
    if llm_owns:
        return llm_operator, detected_city, None, (
            f"User named {detected_city}; multiple operators own sites there. "
            f"Respected LLM's pick of {llm_operator}; no specific site pinned."
        )
    # Pick the operator with the most sites in this city.
    op_counts: dict[str, int] = {}
    for op, _ in matches:
        op_counts[op] = op_counts.get(op, 0) + 1
    chosen = max(op_counts.items(), key=lambda kv: kv[1])[0]
    return chosen, detected_city, None, (
        f"User named {detected_city}; LLM picked {llm_operator} but {llm_operator} has "
        f"no site there. Overrode operator to {chosen} (largest presence in {detected_city})."
    )


class ExpansionWorkloadAgent(BaseAgent):
    async def parse_query(self, query: str, progress_callback=None) -> ExpansionSpec:
        self.logger.info(f"Parsing expansion query: {query}")
        if progress_callback:
            await progress_callback("Parsing expansion scope with AI...", 5)

        prompt = f"""Parse this datacenter expansion request into JSON:

QUERY: "{query}"

Required JSON shape:
{{
  "operator": "eStruxture",
  "province": "QC",
  "city": "Vaughan",                  // literal city named by user, null if absent
  "target_additional_mw": 60,
  "horizon_years": 3,
  "target_year": 2030,
  "workload_mix": "ai_training",      // one of the four supported
  "prefer_brownfield": true,
  "normalized_name": "eStruxture · +60 MW · 2030 AI training"
}}

If the user didn't name an operator, default to "eStruxture".
If the user named a city, return it VERBATIM as they wrote it (don't infer
or substitute — "our Vaughan datacenter" → "Vaughan"). If no city is named,
return null. Do NOT pick a city based on the operator's headquarters or
typical territory — only return a city the user actually wrote.
If no MW target, leave null (we'll default).
If no workload mix mentioned, infer from context (mentions of AI / training
/ inference, otherwise "balanced")."""

        try:
            parsed = await self.ask_claude_json(SYSTEM, prompt)
        except Exception as e:
            self.logger.warning(f"Workload parse failed, using defaults: {e}")
            parsed = {
                "operator": "eStruxture",
                "province": "QC",
                "city": None,
                "target_additional_mw": None,
                "horizon_years": 3,
                "target_year": 2030,
                "workload_mix": "balanced",
                "prefer_brownfield": True,
                "normalized_name": "Default: eStruxture expansion",
            }

        llm_operator = (parsed.get("operator") or "eStruxture").strip()
        target_mw = parsed.get("target_additional_mw")
        if not target_mw:
            target_mw = _mw_from_text(query) or 30.0
        target_mw = float(max(5.0, target_mw))

        horizon = parsed.get("horizon_years") or _years_from_text(query) or 3
        horizon = max(1, min(15, int(horizon)))
        target_year = int(parsed.get("target_year") or (2024 + horizon))

        workload_mix = (parsed.get("workload_mix") or "balanced").lower()
        if workload_mix not in {"traditional", "ai_inference", "ai_training", "balanced"}:
            workload_mix = "balanced"

        # City detection: prefer Claude's literal extraction; fall back to the
        # deterministic catalog scanner on the raw query in case the LLM
        # silently dropped it. Either way, validation happens in
        # _resolve_routing against the operator footprint catalog (no LLM
        # guessing — §0 of REPORTS_COHESION.md).
        llm_city = (parsed.get("city") or "").strip() or None
        detected_city = llm_city or _detect_city(query)

        operator, resolved_city, target_site_id, routing_note = _resolve_routing(
            llm_operator=llm_operator,
            detected_city=detected_city,
        )

        province = (parsed.get("province") or "QC").strip().upper()

        spec = ExpansionSpec(
            query=query,
            normalized_name=parsed.get("normalized_name") or f"{operator} · +{int(target_mw)} MW · {target_year}",
            operator=operator,
            province=province,
            target_additional_mw=target_mw,
            horizon_years=horizon,
            target_year=target_year,
            workload_mix=workload_mix,
            prefer_brownfield=bool(parsed.get("prefer_brownfield", True)),
            city=resolved_city,
            target_site_id=target_site_id,
            routing_note=routing_note,
        )

        if progress_callback:
            await progress_callback(
                f"Parsed: {operator} · +{int(target_mw)} MW · {horizon}y · {workload_mix.replace('_', ' ')}",
                10,
            )
            # §11 — emit a substep line when routing actually fired, so the
            # operator can see why the operator/site was chosen.
            if routing_note:
                await progress_callback(routing_note, 12)

        spec.context_summary = await self._summarize(spec)
        return spec

    async def _summarize(self, spec: ExpansionSpec) -> str:
        prompt = f"""Write a one-paragraph (3-4 sentence) plain-English overview of this datacenter expansion study:

Operator: {spec.operator} ({spec.province})
Target capacity to add: +{spec.target_additional_mw:.0f} MW
Horizon: {spec.horizon_years} years (target year {spec.target_year})
Workload mix: {spec.workload_mix.replace('_', ' ')}
Brownfield preference: {'yes' if spec.prefer_brownfield else 'no'}

Tone: confident, expert. Avoid jargon. Mention what's being planned (brownfield phases at existing sites vs greenfield neighbors) and why the workload mix matters. No markdown."""
        try:
            return (await self.ask_claude(SYSTEM, prompt, max_tokens=300)).strip()
        except Exception as e:
            self.logger.warning(f"Spec summary failed: {e}")
            return (
                f"Expansion study for {spec.operator}: add +{spec.target_additional_mw:.0f} MW "
                f"over {spec.horizon_years} years under a {spec.workload_mix.replace('_', ' ')} workload mix."
            )
