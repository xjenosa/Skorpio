"""
Year-anchored electrification adoption trajectories for the Winter Peak
pipeline.

Each scenario track (conservative / moderate / aggressive) is a piecewise-
linear curve over a small number of anchor years for heat-pump (HP) and
electric-vehicle (EV) residential adoption. The simulator interpolates to
the user-supplied `horizon_year` so that the same "Moderate" track means
different adoption percentages at 2030 vs. 2050.

Why piecewise-linear: the public sources below report scenario endpoints
at 2030 / 2035 / 2050 only. Linear interpolation between anchors is the
honest default — any smoother curve (logistic, S-curve) would be an
opinion the sources don't license. Clamp at endpoints for years outside
the anchored range (anything before the 2024 baseline or beyond 2050).

──────────────────────────────────────────────────────────────────────────
Sources
──────────────────────────────────────────────────────────────────────────
Baseline (2024):
  - NRCan, "Survey of Household Energy Use 2019" — residential heating
    mix (heat-pump share ~5% nationally).
    https://natural-resources.canada.ca/energy-efficiency/data-research-insights-energy-efficiency/results-survey-household-energy-use/24142
  - StatsCan Table 23-10-0308-01 — light-duty vehicle registrations by
    fuel type (battery + plug-in hybrid share ~3-7% of new sales 2024;
    stock share ~2-3%; here we use the higher "households with at least
    one EV" framing).
    https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2310030801

Conservative track — current-policy / no acceleration:
  - Canada Energy Regulator, "Canada's Energy Future 2023", Current
    Measures scenario. Heat-pump stock ~10% by 2030, ~25% by 2050.
    https://www.cer-rec.gc.ca/en/data-analysis/canada-energy-future/2023/
  - CER 2023 same scenario, light-duty EV stock share ~15% by 2030,
    ~40% by 2050.

Moderate track — announced federal/provincial 2030 plans on track:
  - Federal Greener Homes Grant + provincial heat-pump rebates target
    ~25% HP adoption by 2030 (Canada's 2030 Emissions Reduction Plan,
    "Buildings" chapter, ECCC 2022).
    https://www.canada.ca/en/services/environment/weather/climatechange/climate-plan/climate-plan-overview/emissions-reduction-2030.html
  - Transport Canada ZEV Sales Mandate (2023): 100% new LDV sales ZEV
    by 2035, with interim 20% by 2026 → ~30% stock share by 2030.
    https://tc.canada.ca/en/road-transportation/innovative-technologies/zero-emission-vehicles
  - CER 2023 "Evolving Policies" scenario, 2050 endpoints: HP ~60%,
    EV ~80%.

Aggressive track — 2035 net-zero electricity + full building electrification:
  - CER 2023 "Canada Net-zero" scenario. HP ~50% by 2035, ~90% by 2050.
  - IEA, "Net Zero Roadmap: A Global Pathway to Keep the 1.5°C Goal in
    Reach — 2023 Update", building electrification + transport
    electrification milestones. EV ~60% by 2035, ~95% by 2050.
    https://www.iea.org/reports/net-zero-roadmap-a-global-pathway-to-keep-the-15-0c-goal-in-reach
"""
from __future__ import annotations

from dataclasses import dataclass


# Anchor years and (hp, ev) adoption fractions per track. Values are
# residential stock-share fractions in [0.0, 1.0]. Anchors must be in
# ascending year order.
@dataclass(frozen=True)
class _Anchor:
    year: int
    hp: float
    ev: float


_TRACK_ANCHORS: dict[str, tuple[_Anchor, ...]] = {
    "conservative": (
        _Anchor(2024, 0.05, 0.07),
        _Anchor(2030, 0.10, 0.15),
        _Anchor(2050, 0.25, 0.40),
    ),
    "moderate": (
        _Anchor(2024, 0.05, 0.07),
        _Anchor(2030, 0.25, 0.30),
        _Anchor(2050, 0.60, 0.80),
    ),
    "aggressive": (
        _Anchor(2024, 0.05, 0.07),
        _Anchor(2035, 0.50, 0.60),
        _Anchor(2050, 0.90, 0.95),
    ),
}


def _interp(year: int, anchors: tuple[_Anchor, ...]) -> tuple[float, float]:
    """Piecewise-linear interpolation, clamped at endpoints."""
    if year <= anchors[0].year:
        return anchors[0].hp, anchors[0].ev
    if year >= anchors[-1].year:
        return anchors[-1].hp, anchors[-1].ev
    for lo, hi in zip(anchors, anchors[1:]):
        if lo.year <= year <= hi.year:
            t = (year - lo.year) / (hi.year - lo.year)
            return (
                lo.hp + (hi.hp - lo.hp) * t,
                lo.ev + (hi.ev - lo.ev) * t,
            )
    return anchors[-1].hp, anchors[-1].ev  # unreachable


def adoption_at_year(track: str, horizon_year: int) -> tuple[float, float]:
    """
    Return (hp_pct, ev_pct) for the given track at the given year.
    Falls back to the moderate track if `track` is not recognized.
    """
    anchors = _TRACK_ANCHORS.get(track.lower(), _TRACK_ANCHORS["moderate"])
    return _interp(horizon_year, anchors)


def anchored_range() -> tuple[int, int]:
    """Earliest baseline and latest anchored projection year across all tracks."""
    lo = min(a[0].year for a in _TRACK_ANCHORS.values())
    hi = max(a[-1].year for a in _TRACK_ANCHORS.values())
    return lo, hi


TRACK_DESCRIPTIONS: dict[str, str] = {
    "conservative": (
        "Current-policy trajectory: residential electrification continues at the "
        "pace observed in CER 2023 Current Measures (limited federal/provincial push)."
    ),
    "moderate": (
        "Announced-targets trajectory: federal Greener Homes + Transport Canada "
        "ZEV mandate hit their stated 2030 milestones, then continue at policy pace."
    ),
    "aggressive": (
        "Net-zero trajectory: 2035 net-zero electricity grid plus full building "
        "electrification per CER 2023 Canada Net-zero and IEA NZ Roadmap 2023."
    ),
}
