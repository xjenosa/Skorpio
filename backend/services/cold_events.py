"""
Reference cold events for the Winter Peak Stress Tester.

Two real historical events plus a custom-event factory. Hourly curves are
synthesized from publicly reported daily lows + ECCC station data — the
shape (rapid drop, sustained cold, gradual warm-up) reflects the actual
event's reported pattern rather than precise station readings.

For demo defensibility: these curves are anchored on real reported lows
and event durations from IESO post-mortems and ECCC summaries. They are
NOT the raw station data (which would be 5+ stations × 1-min resolution)
but a smoothed, demo-grade representation.

Sources documented per-event in `sources` field.
"""
from typing import Optional

from backend.models.winter_peak import ColdEvent, HourlyTemperature
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# ── Curve helpers ──────────────────────────────────────────────────────── #


def _smooth_curve(
    start_temp: float,
    min_temp: float,
    end_temp: float,
    duration_hours: int,
    drop_hours: int,
    sustain_hours: int,
    peak_window_hours: int = 12,
) -> list[HourlyTemperature]:
    """
    Build a plausible hourly temperature curve with shape:
        start  →  rapid drop  →  sustained cold (with diurnal wobble)  →  warm-up

    This is an approximation — the actual ECCC station data has more noise,
    but for stress-testing purposes the envelope (peak cold + duration) is
    what matters.
    """
    points: list[HourlyTemperature] = []
    rebound_hours = duration_hours - drop_hours - sustain_hours

    for h in range(duration_hours):
        if h < drop_hours:
            # Linear drop to min
            t = start_temp + (min_temp - start_temp) * (h / max(1, drop_hours))
        elif h < drop_hours + sustain_hours:
            # Sustained cold with diurnal swing (warmer afternoon, colder pre-dawn)
            sustain_h = h - drop_hours
            diurnal = 2.5 * (-1 if sustain_h % 24 < 8 else 1 if sustain_h % 24 < 16 else -1)
            t = min_temp + diurnal
        else:
            # Linear warm-up
            rebound_h = h - drop_hours - sustain_hours
            t = min_temp + (end_temp - min_temp) * (rebound_h / max(1, rebound_hours))

        # Mark peak window: the coldest stretch
        is_peak = drop_hours - 1 <= h <= drop_hours + min(peak_window_hours, sustain_hours)

        points.append(HourlyTemperature(
            hour_offset=h,
            temp_c=round(t, 1),
            wind_speed_kmh=15.0 + (5.0 if is_peak else 0.0),
            is_peak_hour=is_peak,
        ))
    return points


# ── Reference events ──────────────────────────────────────────────────── #


def polar_vortex_2014() -> ColdEvent:
    """
    January 2014 Polar Vortex.

    Toronto Pearson reported a low of -25.5°C on Jan 7, with sustained
    sub-zero temps for ~5 days. IESO recorded a winter peak demand of
    23,127 MW on Jan 7, 2014 — among the top 10 winter peaks on record.
    """
    return ColdEvent(
        event_id="polar_vortex_2014",
        name="January 2014 Polar Vortex",
        region="Eastern Canada / US Midwest",
        start_date="2014-01-05",
        duration_hours=120,                       # 5 days
        min_temp_c=-25.5,
        avg_temp_c=-18.0,
        hourly_curve=_smooth_curve(
            start_temp=-8.0,
            min_temp=-25.5,
            end_temp=-5.0,
            duration_hours=120,
            drop_hours=24,
            sustain_hours=72,
            peak_window_hours=24,
        ),
        description=(
            "A high-amplitude Arctic outbreak that displaced the polar vortex "
            "southward, producing the coldest sustained period in Eastern Canada "
            "in 20+ years. IESO reported a winter peak of 23,127 MW on Jan 7. "
            "Heat pump-equipped homes saw widespread auxiliary resistance heat "
            "engagement. Used as the canonical 'severe event' baseline."
        ),
        sources=[
            "ECCC Toronto Pearson station 6158733 (Jan 2014 dailies)",
            "IESO 18-Month Outlook, March 2014",
            "Environment Canada Top 10 Weather Stories 2014",
        ],
    )


def elliott_2022() -> ColdEvent:
    """
    December 2022 Winter Storm Elliott (the "bomb cyclone").

    A bombogenesis event that crashed temperatures across Eastern North
    America between Dec 23-25, 2022. Toronto recorded -22°C with high winds.
    Caused rolling blackouts in the US Southeast and grid stress in Ontario.
    """
    return ColdEvent(
        event_id="elliott_2022",
        name="December 2022 Winter Storm Elliott",
        region="Eastern North America",
        start_date="2022-12-22",
        duration_hours=72,                        # 3 days
        min_temp_c=-22.0,
        avg_temp_c=-15.0,
        hourly_curve=_smooth_curve(
            start_temp=2.0,                       # rapid drop is the signature
            min_temp=-22.0,
            end_temp=-3.0,
            duration_hours=72,
            drop_hours=12,
            sustain_hours=36,
            peak_window_hours=18,
        ),
        description=(
            "A rapidly intensifying 'bomb cyclone' that dropped temperatures "
            "30+ degrees in 12 hours across Ontario and Quebec on Dec 23, 2022. "
            "Sustained winds amplified perceived cold and EV battery losses. "
            "TVA and Duke Energy issued rolling blackouts in the US Southeast; "
            "Eastern Canadian utilities held but reported elevated stress. "
            "Used as the 'fast-onset event' baseline that tests grid response time."
        ),
        sources=[
            "ECCC Toronto Pearson station 6158733 (Dec 22-25, 2022)",
            "NOAA Storm Events Database",
            "FERC/NERC Winter Storm Elliott Inquiry, October 2023",
        ],
    )


def polar_vortex_2019() -> ColdEvent:
    """
    January 2019 Polar Vortex (Jan 28-31, 2019).

    A short, sharp Arctic outbreak. Chicago hit -30°C and parts of the US
    Midwest dropped below -40°C. Toronto Pearson recorded lows near -22°C
    on Jan 30-31. Shorter than the 2014 event (~3 days vs 5) but with a
    faster onset — a useful test of grid response to deep-but-brief cold
    after the heat-pump fleet has grown post-2014.
    """
    return ColdEvent(
        event_id="polar_vortex_2019",
        name="January 2019 Polar Vortex",
        region="Eastern Canada / US Midwest",
        start_date="2019-01-28",
        duration_hours=72,                        # 3 days
        min_temp_c=-22.0,
        avg_temp_c=-16.0,
        hourly_curve=_smooth_curve(
            start_temp=-5.0,
            min_temp=-22.0,
            end_temp=-6.0,
            duration_hours=72,
            drop_hours=18,
            sustain_hours=36,
            peak_window_hours=18,
        ),
        description=(
            "A high-amplitude polar vortex disruption that collapsed Arctic air "
            "deep into the US Midwest, with Chicago reaching -30°C. Ontario "
            "experienced sustained sub-zero conditions for ~3 days with Toronto "
            "Pearson lows near -22°C on Jan 30-31. Tests grid response to a "
            "deep-but-brief cold event after several years of heat-pump growth."
        ),
        sources=[
            "ECCC Toronto Pearson station 6158733 (Jan 28-31, 2019 dailies)",
            "NWS Storm Summary, Polar Vortex January 2019",
            "IESO 18-Month Outlook, March 2019",
        ],
    )


def deep_freeze_feb_2015() -> ColdEvent:
    """
    February 2015 — coldest February in Toronto since 1875.

    Not a single event but a sustained month of deep cold; we model the
    peak week (Feb 13-20) as a long, moderately-cold stretch rather than
    a single peak. Toronto Pearson recorded a low near -23°C on Feb 16,
    2015, but the operationally interesting story is the *duration* of
    sub-zero conditions, not the absolute floor.
    """
    return ColdEvent(
        event_id="deep_freeze_feb_2015",
        name="February 2015 Deep Freeze",
        region="Eastern Canada / Northeast US",
        start_date="2015-02-13",
        duration_hours=168,                       # 7 days
        min_temp_c=-23.0,
        avg_temp_c=-15.0,
        hourly_curve=_smooth_curve(
            start_temp=-8.0,
            min_temp=-23.0,
            end_temp=-10.0,
            duration_hours=168,
            drop_hours=24,
            sustain_hours=120,
            peak_window_hours=48,
        ),
        description=(
            "A week-long stretch of sustained deep cold during what became the "
            "coldest February in Toronto since 1875. Less extreme than the 2014 "
            "polar vortex at peak but with longer duration — tests grid stress "
            "under prolonged elevated heating load rather than a single peak hour. "
            "Particularly relevant for heat-pump-heavy scenarios where multi-day "
            "auxiliary resistance engagement compounds feeder loading."
        ),
        sources=[
            "ECCC Toronto Pearson station 6158733 (Feb 2015 dailies)",
            "ECCC Top 10 Weather Stories 2015",
            "IESO 18-Month Outlook, March 2015",
        ],
    )


def winter_storm_uri_2021() -> ColdEvent:
    """
    February 2021 Winter Storm Uri (Feb 13-17, 2021).

    The cross-jurisdictional benchmark event: caused the Texas grid collapse
    that left 4.5M customers without power and 246+ dead. Ontario experienced
    the same Arctic air mass with Toronto Pearson lows near -22°C, but the
    Ontario grid held. Included as a real test of jurisdictional grid
    hardening — same weather, different outcomes.
    """
    return ColdEvent(
        event_id="winter_storm_uri_2021",
        name="February 2021 Winter Storm Uri",
        region="North America (Texas to Eastern Canada)",
        start_date="2021-02-13",
        duration_hours=96,                        # 4 days
        min_temp_c=-22.0,
        avg_temp_c=-15.0,
        hourly_curve=_smooth_curve(
            start_temp=-3.0,
            min_temp=-22.0,
            end_temp=-7.0,
            duration_hours=96,
            drop_hours=24,
            sustain_hours=48,
            peak_window_hours=24,
        ),
        description=(
            "A continent-spanning Arctic outbreak that caused the catastrophic "
            "Texas grid collapse (ERCOT load-shed of ~20 GW, 4.5M customers "
            "affected). Ontario felt the same air mass with Toronto Pearson lows "
            "near -22°C and held without significant outages. Included as a "
            "cross-jurisdictional benchmark — useful for comparing Ontario "
            "outcomes against the FERC/NERC findings on ERCOT failure modes."
        ),
        sources=[
            "FERC/NERC Joint Inquiry into the February 2021 Cold Weather Outages (Nov 2021)",
            "ECCC Toronto Pearson station 6158733 (Feb 13-17, 2021 dailies)",
            "IESO 18-Month Outlook, March 2021",
        ],
    )


def custom_event(
    min_temp_c: float,
    duration_hours: int,
    location_label: str = "User-defined location",
) -> ColdEvent:
    """
    Generate a synthetic cold event for what-if exploration.

    Shape: 1/4 of duration is the rapid drop, 1/2 is sustained cold,
    1/4 is the warm-up. A reasonable default profile for exploring
    "what if we had a colder/longer event than 2014?"
    """
    drop_hours = max(6, duration_hours // 4)
    rebound_hours = max(6, duration_hours // 4)
    sustain_hours = duration_hours - drop_hours - rebound_hours

    return ColdEvent(
        event_id="custom",
        name=f"Custom event ({min_temp_c:.1f}°C / {duration_hours}h)",
        region=location_label,
        start_date=None,
        duration_hours=duration_hours,
        min_temp_c=min_temp_c,
        avg_temp_c=min_temp_c * 0.6,              # rough approximation
        hourly_curve=_smooth_curve(
            start_temp=max(-5.0, min_temp_c + 15),
            min_temp=min_temp_c,
            end_temp=max(-5.0, min_temp_c + 10),
            duration_hours=duration_hours,
            drop_hours=drop_hours,
            sustain_hours=sustain_hours,
            peak_window_hours=min(24, sustain_hours // 2),
        ),
        description=(
            f"Synthetic cold event for exploration. Drop to {min_temp_c:.1f}°C "
            f"over {drop_hours}h, sustain for {sustain_hours}h, warm-up over "
            f"{rebound_hours}h. Curve shape mirrors the 2014 Polar Vortex."
        ),
        sources=["Synthetic, derived from 2014 Polar Vortex envelope"],
    )


# ── Public API ────────────────────────────────────────────────────────── #


_REGISTRY = {
    "polar_vortex_2014": polar_vortex_2014,
    "elliott_2022": elliott_2022,
    "polar_vortex_2019": polar_vortex_2019,
    "deep_freeze_feb_2015": deep_freeze_feb_2015,
    "winter_storm_uri_2021": winter_storm_uri_2021,
}


def list_reference_events() -> list[dict]:
    """Catalog used by the UI scenario picker."""
    return [
        {"event_id": "polar_vortex_2014", "name": "January 2014 Polar Vortex",
         "min_temp_c": -25.5, "duration_hours": 120,
         "blurb": "5-day Arctic outbreak; IESO winter peak 23,127 MW."},
        {"event_id": "elliott_2022", "name": "December 2022 Winter Storm Elliott",
         "min_temp_c": -22.0, "duration_hours": 72,
         "blurb": "Rapid 'bomb cyclone' drop; tested grid response time."},
        {"event_id": "polar_vortex_2019", "name": "January 2019 Polar Vortex",
         "min_temp_c": -22.0, "duration_hours": 72,
         "blurb": "Short, sharp Arctic outbreak; Chicago hit -30°C."},
        {"event_id": "deep_freeze_feb_2015", "name": "February 2015 Deep Freeze",
         "min_temp_c": -23.0, "duration_hours": 168,
         "blurb": "Week-long sustained cold; coldest Toronto Feb since 1875."},
        {"event_id": "winter_storm_uri_2021", "name": "February 2021 Winter Storm Uri",
         "min_temp_c": -22.0, "duration_hours": 96,
         "blurb": "Caused Texas grid collapse; Ontario held — cross-jurisdictional benchmark."},
        {"event_id": "custom", "name": "Custom event",
         "min_temp_c": None, "duration_hours": None,
         "blurb": "Specify your own minimum temperature and duration."},
    ]


def get_event(
    event_id: str,
    custom_min_temp_c: Optional[float] = None,
    custom_duration_hours: Optional[int] = None,
    custom_location_label: str = "User-defined location",
) -> ColdEvent:
    """Resolve an event_id (with optional custom parameters) to a ColdEvent."""
    if event_id == "custom":
        if custom_min_temp_c is None or custom_duration_hours is None:
            raise ValueError("Custom event requires min_temp_c and duration_hours")
        return custom_event(custom_min_temp_c, custom_duration_hours, custom_location_label)
    factory = _REGISTRY.get(event_id)
    if factory is None:
        raise ValueError(f"Unknown event_id: {event_id}")
    return factory()
