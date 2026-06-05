"""
Inline source citation validation for synthesis-agent outputs.

Phase 2 of the REPORTS_COHESION §7c citation system. Every pipeline's
synthesis agent prompts Claude to emit `[[sN|cited text]]` markers in the
executive summary and a `citation_sources` dict on the side, then the
orchestrator validates the pair before returning the plan.

The validation rules implemented here mirror the contract documented in
`frontend/src/components/CITATIONS_PHASE_2.md §2.6` (density target) and
`§4` (validation hook). See that doc for the rationale behind each rule.

Public API:

    validate_citations(text, sources) -> list[CitationError]
        Run all checks and return any failures. Empty list = passed.

    format_errors_for_retry(errors) -> str
        Render the failure list as a one-paragraph instruction to append
        to the synthesis prompt on retry, so Claude knows what to fix.

    CITATION_PROMPT_RULES: str
        The instruction block to embed in every synthesis prompt. Defines
        the marker syntax, the four status values, and the density target.

Typical use:

    txt, sources = await self._synthesize_with_citations(prompt)
    errors = validate_citations(txt, sources)
    if errors:
        retry_prompt = prompt + "\n\n" + format_errors_for_retry(errors)
        txt, sources = await self._synthesize_with_citations(retry_prompt)
        # If errors still present, fall back to stub.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Protocol

from backend.models.report import CitationSource

# ── Marker syntax ──────────────────────────────────────────────────────── #
#
# A citation marker is `[[sN|cited text]]` where `sN` is an id like `s1`,
# `s12`, etc. The cited text can contain any character except `]`.

_MARKER_RE = re.compile(r"\[\[(s\w+)\|([^\]]+)\]\]")

# Detects a marker prefix `[[sN|` — used as the canonical
# already-wrapped-phrase detector for retry idempotency. DO NOT replace
# this with a fixed-width character lookback; the Phase 1 helper script
# tried `text.slice(-4)` and it failed to catch wrappers, producing
# nested `[[s1|[[s1|...]]]]` corruption on its second run. See
# CITATIONS_PHASE_2.md §"Lessons from iteration".
_WRAP_PREFIX_RE = re.compile(r"\[\[s\w+\|")

# Detects a marker inside another marker's text region — i.e. a literal
# nested wrapper, which is invalid output.
_NESTED_MARKER_RE = re.compile(r"\[\[s\w+\|[^\]]*\[\[s")

# Per-paragraph "this paragraph makes a factual claim" heuristic. Any
# paragraph matching this pattern needs ≥ 2 markers. Tuned to be
# permissive: a digit, a $ amount, a percentage, an ISO/MW unit, or a
# capitalized multi-word phrase that looks like a named entity.
_FACTUAL_HINTS_RE = re.compile(
    r"\d+|\$|%|\bMW\b|\bMVA\b|\bkV\b|\bgCO2\b|\bkWh\b|"
    r"\b(?:OEB|IESO|ECCC|NRCan|StatsCan|IPCC|Alectra|Hydro One|eStruxture|"
    r"Equinix|Cologix|NREL|ArcGIS)\b"
)

# Density: minimum chars-per-marker. Lower = denser.
_DENSITY_FLOOR_CHARS = 350

# Per-paragraph minimum markers when factual hints present.
_PER_PARAGRAPH_MIN_MARKERS = 2


# ── Errors ─────────────────────────────────────────────────────────────── #


@dataclass(frozen=True)
class CitationError:
    code: str
    message: str


# ── Validators ─────────────────────────────────────────────────────────── #


def validate_citations(
    executive_summary: str,
    citation_sources: dict[str, CitationSource],
) -> list[CitationError]:
    """Run all validation checks; return list of failures (empty = passed)."""
    errors: list[CitationError] = []

    # 1. No double-wrapping (the failure mode from Phase 1's broken helper)
    nested = _NESTED_MARKER_RE.search(executive_summary)
    if nested:
        errors.append(CitationError(
            code="double_wrapped",
            message=(
                f"A marker is nested inside another marker near "
                f"{executive_summary[max(0, nested.start()-20):nested.end()+20]!r}. "
                f"Each `[[sN|...]]` must contain only plain text, never another marker."
            ),
        ))

    # 2. Marker–source consistency
    referenced_ids: set[str] = {m.group(1) for m in _MARKER_RE.finditer(executive_summary)}
    source_ids = set(citation_sources.keys())

    missing = referenced_ids - source_ids
    if missing:
        errors.append(CitationError(
            code="missing_source",
            message=(
                f"Markers reference id(s) {sorted(missing)} but no entry exists "
                f"in `citation_sources`. Every `[[sN|...]]` must have a matching "
                f"`citation_sources[sN]` entry with label, detail, and status."
            ),
        ))

    orphans = source_ids - referenced_ids
    if orphans:
        errors.append(CitationError(
            code="orphan_source",
            message=(
                f"`citation_sources` defines id(s) {sorted(orphans)} that are "
                f"never referenced by any marker in the executive summary. "
                f"Remove the orphans or wrap the corresponding phrases."
            ),
        ))

    # 3. Density floor — enough markers per total length
    total_markers = sum(1 for _ in _MARKER_RE.finditer(executive_summary))
    expected_min = math.ceil(len(executive_summary) / _DENSITY_FLOOR_CHARS)
    if total_markers < expected_min:
        errors.append(CitationError(
            code="density_low",
            message=(
                f"Exec summary has {total_markers} marker(s) across "
                f"{len(executive_summary)} chars; the floor is "
                f"{expected_min} (one marker per {_DENSITY_FLOOR_CHARS} chars). "
                f"Add more `[[sN|cited text]]` markers — every quantitative claim, "
                f"named asset, named regulation, and industry-pattern claim should be cited."
            ),
        ))

    # 4. Per-paragraph minimum — each "factual" paragraph needs ≥ 2 markers
    sparse_paragraphs: list[int] = []
    for idx, raw in enumerate(executive_summary.split("\n\n")):
        para = raw.strip()
        if not para:
            continue
        # Skip pure-header paragraphs (just a single `# ...` line)
        if para.startswith("#") and "\n" not in para:
            continue
        if not _FACTUAL_HINTS_RE.search(para):
            continue
        para_marker_count = sum(1 for _ in _MARKER_RE.finditer(para))
        if para_marker_count < _PER_PARAGRAPH_MIN_MARKERS:
            sparse_paragraphs.append(idx)
    if sparse_paragraphs:
        errors.append(CitationError(
            code="paragraph_under_cited",
            message=(
                f"Paragraph(s) {sparse_paragraphs} (0-indexed) make factual claims "
                f"but contain fewer than {_PER_PARAGRAPH_MIN_MARKERS} citation markers. "
                f"Every factual paragraph must have at least {_PER_PARAGRAPH_MIN_MARKERS} markers."
            ),
        ))

    # 5. citation_sources schema spot-check (Pydantic already validates
    # types; we additionally enforce that source_id == dict key, which
    # the LLM has been known to disagree about)
    for key, src in citation_sources.items():
        if src.source_id != key:
            errors.append(CitationError(
                code="source_id_mismatch",
                message=(
                    f"`citation_sources[{key!r}].source_id` is {src.source_id!r}; "
                    f"the two must match."
                ),
            ))

    return errors


def format_errors_for_retry(errors: list[CitationError]) -> str:
    """Render error list as a retry-prompt addendum."""
    if not errors:
        return ""
    bullet = "\n- "
    body = bullet.join(e.message for e in errors)
    return (
        "Your previous response did not pass citation validation. "
        "Fix the following issues and regenerate:\n- " + body +
        "\n\nReturn ONLY the corrected JSON with `executive_summary` and "
        "`citation_sources` keys; do not add commentary."
    )


# ── Prompt block shared by every synthesis agent ───────────────────────── #


# ── Synthesis helper — JSON call + validation + retry ──────────────────── #


class _SynthesisAgent(Protocol):
    """Structural type for the synthesis agent the helper needs. Avoids a
    hard import of BaseAgent (which would create a cycle: BaseAgent →
    citations → BaseAgent)."""
    logger: Any
    async def ask_claude_json(self, system: str, prompt: str, max_tokens: int = ...) -> Any: ...


_JSON_TAIL = (
    "\n\nReturn ONLY a single JSON object with exactly these two top-level "
    "keys:\n"
    '  "executive_summary": <the markdown exec summary string with [[sN|...]] markers>\n'
    '  "citation_sources":  <object mapping each "sN" id to {source_id, label, detail, status}>\n'
    "No prose, no code fences, no commentary outside the JSON."
)


async def synthesize_with_citations(
    agent: _SynthesisAgent,
    *,
    system: str,
    prompt: str,
    max_tokens: int = 1800,
    max_retries: int = 2,
) -> tuple[str, dict[str, CitationSource]]:
    """Run a synthesis prompt expecting `{executive_summary, citation_sources}`
    JSON. Validate the citations, retry up to `max_retries` times with the
    validator's feedback appended to the prompt on each failure. Return the
    validated text + sources.

    On unrecoverable failure (LLM unavailable, or final validation still
    failing after retries), returns the last attempt's `(text, sources)`
    pair — the caller can detect failure by checking
    `validate_citations()` again or by falling back to a stub on empty
    text.

    The `CITATION_PROMPT_RULES` block is automatically appended to the
    prompt, so callers only need to write the pipeline-specific guidance.
    """
    full_prompt = prompt + "\n\n" + CITATION_PROMPT_RULES + _JSON_TAIL
    last_text = ""
    last_sources: dict[str, CitationSource] = {}
    last_errors: list[CitationError] = []

    for attempt in range(max_retries + 1):
        attempt_prompt = full_prompt
        if attempt > 0:
            attempt_prompt = full_prompt + "\n\n" + format_errors_for_retry(last_errors)

        try:
            response = await agent.ask_claude_json(system, attempt_prompt, max_tokens=max_tokens)
        except Exception as exc:
            agent.logger.warning(
                "Synthesis JSON call failed on attempt %d: %s", attempt + 1, exc,
            )
            return last_text, last_sources

        if not isinstance(response, dict):
            last_errors = [CitationError(
                code="not_a_json_object",
                message="Top-level response is not a JSON object.",
            )]
            continue

        last_text = response.get("executive_summary", "") or ""
        raw_sources = response.get("citation_sources", {}) or {}
        try:
            last_sources = {
                key: (val if isinstance(val, CitationSource) else CitationSource(**val))
                for key, val in raw_sources.items()
            }
        except Exception as exc:
            last_errors = [CitationError(
                code="parse_error",
                message=f"`citation_sources` could not be parsed: {exc}",
            )]
            continue

        last_errors = validate_citations(last_text, last_sources)
        if not last_errors:
            return last_text, last_sources

        agent.logger.warning(
            "Citation validation failed on attempt %d/%d: %s",
            attempt + 1, max_retries + 1,
            "; ".join(e.code for e in last_errors),
        )

    return last_text, last_sources


# ── Prompt block shared by every synthesis agent ───────────────────────── #


CITATION_PROMPT_RULES = """
=== INLINE SOURCE CITATIONS (required) ===

Your `executive_summary` field MUST contain inline citation markers of the
form `[[sN|cited text]]` (e.g. `[[s4|3.62× lifetime ROI]]`) wrapped around
every:

  • quantitative number ($ amounts, MW values, %, hours, counts, etc.)
  • named asset (substation/feeder name, datacenter site, city)
  • named regulation, framework, or program
  • industry-pattern claim or rule of thumb

Each `sN` id you use MUST have a corresponding entry in a top-level
`citation_sources` dict with this shape:

  {
    "sN": {
      "source_id": "sN",
      "label": "<short title for the popover header, ≤ 50 chars>",
      "detail": "<one-sentence 'where this value came from', ≤ 120 chars>",
      "status": "live" | "frozen" | "modeled" | "llm"
    },
    ...
  }

Status meanings (be honest — picking the wrong one is hallucination):

  • `frozen`   — value comes from an ingested public dataset, a hand-
                 curated catalog header, OR a user-supplied scenario input.
                 Example: OEB Licensed Distributor Territories, IPCC AR5
                 lifecycle factors, "$50M budget supplied at job submission".

  • `modeled`  — value is computed by a pipeline stage over frozen/live
                 inputs. Example: knapsack output, predicted LCOE,
                 utilization %, blended carbon intensity.

  • `live`     — value was pulled from an external API on this run.
                 Example: NREL utility-rates response, ArcGIS GeoEnrichment
                 demographics, IESO live carbon snapshot. ONLY use this if
                 a live fetch actually happened.

  • `llm`      — claim is your general knowledge / industry pattern /
                 regulatory framing / recommendation reasoning. It is NOT
                 derived from any dataset passed to you. Use this for
                 phrases like "vegetation contact is the leading cause of
                 outages" or "Ontario's evolving reliability framework".
                 Honestly mark these as `llm` — leaving them uncited reads
                 as sleight of hand.

CITATION DENSITY (both rules are mandatory):

  1. Overall: at least one marker per 350 characters of exec summary prose.
  2. Per-paragraph: every paragraph that makes a quantitative claim, names
     an asset/regulation, or asserts an industry pattern MUST contain at
     least TWO markers.

Repeated mentions of the same fact should reuse the same `sN` id. Never
fabricate a source. If a number has no defensible origin, omit it from the
summary rather than inventing a label.

ANTI-HALLUCINATION RULES:

  • Cite the actual ingest source, not what "sounds plausible". If an
    Ontario service-territory polygon came from the OEB Licensed
    Distributor Territories KMZ, the label is that file — not "Annual
    Report".
  • A regulator's name alone (e.g. "OEB") is NOT a citation candidate
    unless a quantitative claim is attached to it.
  • User-supplied scenario inputs ($50M budget, 26-year horizon, 30% EV
    penetration) are `frozen`, not `modeled`. They are inputs, not
    outputs.
  • Hand-curated catalogs are labeled `"Hand-curated catalog · {scope}"`
    with the detail naming the public filings they calibrate against —
    never as a single filing name.
""".strip()
