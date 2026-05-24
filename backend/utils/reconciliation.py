"""
Cross-reference reconciliation — Pattern 3 of three anti-hallucination patterns.

After Claude generates prose (region insight, executive summary, etc.), the
backend already knows the *real* numbers it fed into the prompt: carbon
intensity from Electricity Maps, LCOE from the scorer, capacity from the
workload spec, etc.

This helper compares what Claude wrote against those known values. For any
number Claude mentions near a known-fact keyword, we flag a drift if it
diverges by more than `tolerance_pct`. When `replace=True` (the default),
the helper also rewrites the prose so the drifted number is replaced by
the source-of-truth value, preserving the original number's formatting
(decimal precision, commas, percentage style).

Usage:
    from backend.utils.reconciliation import reconcile

    facts = {
        "carbon_intensity_g_per_kwh": 138.0,
        "lcoe_usd_mwh": 47.2,
        "capacity_mw": 50.0,
    }
    report = reconcile(claude_text=exec_summary, source_facts=facts)
    if report.has_drift:
        logger.warning("Drift corrected: %s", report.drifts)
    final_summary = report.corrected_text   # use this instead of the raw text
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from backend.utils.logger import get_logger

logger = get_logger(__name__)


# Keyword hints per known source fact. Each fact key (the dict key the
# caller passes in) maps to a list of substrings the helper looks for in
# Claude's text. Found a hint → scan nearby for the claimed number.
_DEFAULT_CONTEXT_HINTS: dict[str, list[str]] = {
    # Siting
    "carbon_intensity_g_per_kwh": ["carbon", "co2", "co₂", "gco", "g/kwh", "intensity"],
    "lcoe_usd_mwh":                ["lcoe", "levelized", "levelised", "$/mwh", "usd/mwh", "$ /mwh"],
    "capacity_mw":                 ["capacity", "mw of", "mw at", "nameplate"],
    "headroom_mw":                 ["headroom", "available headroom", "available mw"],
    "uptime":                      ["uptime", "availability"],
    "transmission_headroom_mw":    ["transmission headroom", "poi headroom"],
    "fiber_latency_ms":            ["latency", "fibre", "fiber"],
    "deployment_months":           ["months", "time to power", "permitting"],
    # Winter Peak. Broad hints are safe now that `_unit_compatible` filters
    # out candidates whose explicit unit doesn't match the fact (e.g.
    # "30% HP" near "peak demand" no longer gets rewritten to the MW peak
    # value — the "%" suffix disqualifies it before the drift check).
    "demand_gw":                   ["demand", "gw", "load"],
    # Winter Peak — chat phrasing. Claude tends to say "peak climbs from X
    # MW to Y MW" or "peak demand reaches X MW". Kept these explicit
    # multi-word patterns; dropped bare "peak" because it fired on
    # unrelated phrases like "peak hour", "off-peak", "peak winter".
    # Unit guard catches cross-unit false positives downstream.
    "peak_load_mw":                ["peak load", "peak demand", "peak climbs", "peak reaches", "peak hits", "peaks at"],
    # Electrification
    "heat_pump_adoption_pct":      ["heat pump", "hp adoption", "hp conversion"],
    "ev_adoption_pct":             ["ev adoption", "ev penetration", "electric vehicle"],
    # Tightened to require "score" / "index" attached — the bare word
    # "readiness" appeared too often in Electrification exec summaries
    # ("readiness for 40% EV", "Brampton's readiness...") and matched
    # unrelated nearby numbers ("4 transformers", "1067 households") as
    # false-positive score claims.
    "overall_score":               ["readiness score", "overall score", "composite score", "composite readiness", "readiness index"],
    # Investment
    "budget_cad":                  ["budget", "capital allocation", "capex envelope"],
    "customers_protected":         ["customers protected", "households protected", "customers served"],
    "total_capex_committed_cad":   ["capex committed", "total capex", "committed capital"],
}

# Maximum text-window (in characters) around a hint we will scan for numbers.
# Tightened from 80 → 50: at 80 we caught numbers across full sentence
# boundaries and triggered false-positive rewrites on numbers that were
# adjacent topically but not the *referent* of the keyword. 50 keeps the
# in-clause numbers without bleeding into the next clause.
_WINDOW = 50

# Numbers in Claude's text. Captures plain integers, decimals, and
# comma-grouped thousands (e.g. "1,500.7").
_NUM_RE = re.compile(r"(?<![\w.])(-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)")


# ── Unit-aware filtering ───────────────────────────────────────────────── #
#
# The original validator only looked at proximity between a number and a
# keyword hint. That over-fired in chat conversations where Claude legitimately
# writes "30% HP" near "peak demand" — bare "peak" matched, the 30 got
# compared to peak_load_mw (e.g. 2527 MW), drift was huge, and the validator
# rewrote "30%" to "2527%" — a hallucination *introduced* by the validator
# itself.
#
# The fix is to look at the *unit* attached to each candidate number. A
# number written as "30%" can never be a MW value; "5 MW" can never be a
# percentage. The validator only compares when the claimed unit matches one
# of the units the fact is allowed to carry. Bare numbers (no explicit
# unit) still flow through the drift check — keyword proximity is the
# safeguard there.

# Recognized unit tokens that may follow a number in Claude's prose. The
# regex matches one token at the start of the lookahead window so we can
# anchor on what's immediately after the number.
_UNIT_AFTER_RE = re.compile(
    r"\s*("
    # Composite power / energy units (longest-first to avoid prefix matches)
    r"\$/mwh|usd/mwh|"
    r"gco₂?/kwh|gco2/kwh|g/kwh|"
    r"mwh|gwh|kwh|"
    r"mva|kva|"
    r"mw|gw|kw|"
    # Currency words
    r"cad|usd|"
    # Time / latency / temperature
    r"ms|°c|°f|"
    r"months?|years?|yrs?|"
    # Magnitude suffixes that imply currency when paired with a $ prefix
    r"k|m|b|"
    # Counts
    r"%|"
    r"customers|households|homes"
    # `(?!\w)` instead of `\b`: \b requires a word/non-word transition,
    # which silently fails when both the unit and the following char are
    # non-word (e.g. "50% " — % and space are both non-word, no boundary,
    # \b fails, % goes undetected, and the unit guard collapses for any
    # percentage followed by punctuation/whitespace). That bug caused the
    # reconciler to rewrite "30% HP" → "3387% HP" because % wasn't seen
    # as a unit and the bare number got matched against peak_load_mw.
    # `(?!\w)` only checks that the next char isn't word-like, which
    # correctly terminates non-word units too.
    r")(?!\w)",
    re.IGNORECASE,
)

# Per-fact: which units the claimed number must carry to be eligible for
# comparison. An empty set means "bare numbers only" (e.g. unitless
# scores). A missing key means "no unit constraint applied" — fall back
# to the legacy keyword-proximity check only.
_FACT_UNITS: dict[str, set[str]] = {
    # Power / load
    "peak_load_mw":              {"mw"},
    "demand_gw":                 {"gw"},
    "capacity_mw":               {"mw"},
    "headroom_mw":               {"mw"},
    "transmission_headroom_mw":  {"mw"},
    # Energy economics
    "lcoe_usd_mwh":              {"$/mwh", "usd/mwh"},
    # Carbon
    "carbon_intensity_g_per_kwh": {"g/kwh", "gco2/kwh", "gco₂/kwh"},
    # Latency
    "fiber_latency_ms":          {"ms"},
    # Time horizons — only months. Years are a different unit; let prose
    # like "5-year horizon" through to the drift check unmodified.
    "deployment_months":         {"months", "month"},
    # Currency. $200M / $50M / $5K patterns recognized via the $ prefix
    # plus magnitude suffix; bare "$200" without a suffix also passes.
    "budget_cad":                {"$", "$m", "$k", "$b", "cad"},
    "total_capex_committed_cad": {"$", "$m", "$k", "$b", "cad"},
    # Counts
    "customers_protected":       {"customers", "households", "homes"},
    # Percentages
    "heat_pump_adoption_pct":    {"%"},
    "ev_adoption_pct":           {"%"},
    "uptime":                    {"%"},
    # Unitless score — only bare numbers can match
    "overall_score":             set(),
}


def _detect_unit(text: str, num_start: int, num_end: int) -> Optional[str]:
    """Detect the unit attached to a number at positions [num_start, num_end].
    Returns None when the number is bare (no recognized unit immediately
    surrounding it). Looks BEFORE for the `$` currency prefix and AFTER for
    everything else.

    Examples:
        "$200M"   → "$m"
        "$50"     → "$"
        "30%"     → "%"
        "5 MW"    → "mw"
        "1,800 customers"  → "customers"
        "1,800"   → None
    """
    # Currency prefix: $200, $200M, $50K, $5B
    has_dollar = num_start > 0 and text[num_start - 1] == "$"

    after_match = _UNIT_AFTER_RE.match(text, num_end)
    after_unit = after_match.group(1).lower() if after_match else None

    if has_dollar:
        if after_unit in ("m", "k", "b"):
            return f"${after_unit}"
        return "$"

    if not after_unit:
        return None

    # Normalize aliases. "month/months" → "months"; "year/years/yr/yrs" → "yrs".
    if after_unit in ("month", "months"):
        return "months"
    if after_unit in ("year", "years", "yr", "yrs"):
        return "yrs"
    # Bare "k" / "m" / "b" without a leading $ is ambiguous — could be a
    # currency abbreviation, could be something else. Treat as bare so we
    # don't accidentally match against budget facts.
    if after_unit in ("k", "m", "b"):
        return None
    return after_unit


def _unit_compatible(fact_key: str, claimed_unit: Optional[str]) -> bool:
    """True when a candidate number is unit-compatible with the fact.

    Rules:
      - Bare numbers (no unit detected) always pass — keyword proximity
        and drift threshold are the only guards in that case.
      - When the fact has no entry in `_FACT_UNITS`, no unit constraint
        is applied (backwards compatible with any new facts that haven't
        been classified yet).
      - When the fact lists an empty set, only bare numbers pass —
        e.g. unitless scores.
      - Otherwise, the claimed unit must be in the fact's accepted set.
    """
    if claimed_unit is None:
        return True
    accepted = _FACT_UNITS.get(fact_key)
    if accepted is None:
        return True
    return claimed_unit in accepted


class NumericDrift(BaseModel):
    """One suspected case of Claude saying number X near keyword Y that
    actually has a different value in the backend's source data."""
    fact_key: str
    expected: float
    claimed: float
    drift_pct: float
    context: str
    start_pos: int
    end_pos: int
    replacement_text: str


class ReconciliationReport(BaseModel):
    drifts: list[NumericDrift] = []
    facts_checked: int = 0
    corrected_text: str = ""

    @property
    def has_drift(self) -> bool:
        return bool(self.drifts)


# ── helpers ────────────────────────────────────────────────────────────── #


def _looks_like_percentage(fact_key: str) -> bool:
    """A fact key denotes a percentage if it ends in _pct or _percent.
    For these, Claude usually writes "25%" while the backend stores 0.25,
    so we scale by 100 before comparing and replacing."""
    k = fact_key.lower()
    return k.endswith("_pct") or k.endswith("_percent") or "_percent_" in k


def _format_replacement(expected: float, original_str: str) -> str:
    """Format `expected` so it matches the visible precision and comma style
    of `original_str` (the number Claude wrote)."""
    clean = original_str.replace(",", "")
    if "." in clean:
        decimals = len(clean.split(".")[1])
        out = f"{expected:.{decimals}f}"
    elif 0 < abs(expected) < 1.0:
        # Sub-1.0 fractional source (e.g. overall_score=0.503) written by
        # Claude as an integer ("4"). Plain int(round(0.503)) = 1 would
        # destroy the fractional meaning ("0.50 readiness score" rendered
        # as "1"). Force 2-decimal output so the corrected value preserves
        # the fact's natural scale.
        out = f"{expected:.2f}"
    else:
        out = f"{int(round(expected))}"
    had_comma = "," in original_str
    if had_comma and abs(expected) >= 1000:
        parts = out.split(".")
        try:
            parts[0] = f"{int(parts[0]):,}"
        except ValueError:
            pass
        out = ".".join(parts)
    return out


# ── public API ─────────────────────────────────────────────────────────── #


def reconcile(
    claude_text: str,
    source_facts: dict[str, float],
    tolerance_pct: float = 10.0,
    context_hints: Optional[dict[str, list[str]]] = None,
    replace: bool = True,
) -> ReconciliationReport:
    """Compare Claude's text against the backend's source facts.

    Scans `claude_text` for numbers near keywords associated with each fact
    in `source_facts`. If a claimed number diverges from the expected value
    by more than `tolerance_pct`, it's recorded as a NumericDrift. When
    `replace=True` (the default), the drifted numbers are rewritten in
    `corrected_text` to match the source-of-truth values, preserving the
    original number's decimal precision and comma style.

    Returns a ReconciliationReport. `corrected_text` is always populated —
    when there are no drifts, it equals the input text unchanged.
    """
    hints = context_hints or _DEFAULT_CONTEXT_HINTS
    text = claude_text or ""
    text_lower = text.lower()
    drifts: list[NumericDrift] = []
    facts_checked = 0
    claimed_spans: set[tuple[int, int]] = set()

    for fact_key, expected in source_facts.items():
        try:
            expected_f = float(expected)
        except (TypeError, ValueError):
            continue
        keyword_list = hints.get(fact_key, [fact_key.lower()])
        facts_checked += 1
        is_pct = _looks_like_percentage(fact_key)
        compare_expected = expected_f * 100.0 if is_pct else expected_f

        for kw in keyword_list:
            for hit in re.finditer(re.escape(kw.lower()), text_lower):
                start = max(0, hit.start() - _WINDOW)
                end = min(len(text), hit.end() + _WINDOW)
                window = text[start:end]

                for num_match in _NUM_RE.finditer(window):
                    raw = num_match.group().replace(",", "")
                    try:
                        claimed = float(raw)
                    except ValueError:
                        continue

                    # Skip implausible noise.
                    if abs(claimed) > 1_000_000_000:
                        continue

                    abs_start = start + num_match.start()
                    abs_end = start + num_match.end()
                    if (abs_start, abs_end) in claimed_spans:
                        continue   # already replaced by a different fact

                    # Unit guard: skip when the candidate has an explicit
                    # unit that conflicts with the fact's expected unit.
                    # This is what prevents the historical "30% near
                    # 'peak demand' gets rewritten to MW value" bug — the
                    # candidate's '%' suffix is incompatible with the
                    # peak_load_mw fact, so the drift check is skipped
                    # before it can do damage. Bare numbers still flow
                    # through; keyword proximity remains their safeguard.
                    claimed_unit = _detect_unit(text, abs_start, abs_end)
                    if not _unit_compatible(fact_key, claimed_unit):
                        continue

                    if abs(claimed - compare_expected) < 0.05:
                        continue   # close enough — not a drift

                    denom = max(abs(compare_expected), 1e-6)
                    drift_pct = abs(claimed - compare_expected) / denom * 100.0
                    if drift_pct <= tolerance_pct or abs(claimed - compare_expected) <= 0.5:
                        continue   # within tolerance

                    replacement = _format_replacement(compare_expected, num_match.group())
                    drifts.append(NumericDrift(
                        fact_key=fact_key,
                        expected=round(expected_f, 4),
                        claimed=round(claimed, 4),
                        drift_pct=round(drift_pct, 1),
                        context=window.strip(),
                        start_pos=abs_start,
                        end_pos=abs_end,
                        replacement_text=replacement,
                    ))
                    claimed_spans.add((abs_start, abs_end))

    # Apply replacements in reverse order so earlier positions stay valid.
    corrected = text
    if replace and drifts:
        for d in sorted(drifts, key=lambda x: x.start_pos, reverse=True):
            corrected = corrected[: d.start_pos] + d.replacement_text + corrected[d.end_pos:]

    if drifts:
        verb = "replaced" if replace else "found"
        logger.warning(
            "Reconciliation %s %d numeric drift(s) vs. source facts: %s",
            verb,
            len(drifts),
            [{"fact": d.fact_key, "expected": d.expected, "claimed": d.claimed,
              "drift_pct": d.drift_pct, "replacement": d.replacement_text} for d in drifts],
        )
    return ReconciliationReport(
        drifts=drifts,
        facts_checked=facts_checked,
        corrected_text=corrected,
    )
