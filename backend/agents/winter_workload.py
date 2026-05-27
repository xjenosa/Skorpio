"""
Winter Workload Intelligence Agent — Stage 1 of the Winter Peak pipeline.

Parses a natural-language query like
    "Will Mississauga's grid hold a -25°C polar vortex with 30% heat pumps?"
into a structured WinterPeakSpec.
"""
from typing import Optional

from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.grid.feeder_topology import CITY_PROFILES
from backend.models.winter_peak import ScenarioPreset, WinterPeakSpec
from backend.services.adoption_curves import (
    TRACK_DESCRIPTIONS,
    adoption_at_year,
)
from backend.services.cold_events import list_reference_events


SYSTEM_WINTER_WORKLOAD = """You are a grid resilience analyst. Your role is
to parse natural-language stress-test requests into a structured spec.

Supported cities (use the key in lowercase):
  - mississauga (Alectra Utilities, Ontario)
  - toronto (Toronto Hydro, Ontario)
  - ottawa (Hydro Ottawa, Ontario)
  - edmonton (EPCOR Distribution, Alberta)
  - montreal (Hydro-Québec Distribution, Québec)

Supported reference cold events:
  - polar_vortex_2014      (5-day Arctic outbreak, -25.5°C; IESO peak 23,127 MW)
  - elliott_2022           (3-day bomb cyclone, -22°C; fast-onset stress test)
  - polar_vortex_2019      (3-day short-sharp polar vortex, -22°C; Chicago hit -30°C)
  - deep_freeze_feb_2015   (7-day sustained moderate cold, -23°C; coldest Toronto Feb since 1875)
  - winter_storm_uri_2021  (4-day continent-wide event, -22°C; caused Texas grid collapse)
  - custom                 (user specifies min_temp_c and duration_hours)

Supported scenario tracks (each is a year-anchored adoption curve; the
horizon_year you choose drives the actual HP/EV percentages):
  - conservative  (current-policy trajectory; slow electrification)
  - moderate      (announced federal/provincial targets on track)
  - aggressive    (2035 net-zero electricity + full building electrification)

Include all three tracks unless the user is specific. The horizon_year
field is meaningful — extract any year the user mentions ("by 2050",
"2040 outlook"); default to 2030 only if no year is mentioned.

If the user mentions a specific HP/EV percentage, set scenario to "custom"
and include the explicit values.

Always respond with valid JSON. No markdown.""" + GROUNDING_RULES


# ── Scenario track metadata ───────────────────────────────────────────── #
# The actual adoption percentages live in `backend.services.adoption_curves`
# and are resolved at the user-supplied horizon_year. The track entries
# here just carry display names; numbers come from the curve.


_TRACK_DISPLAY_NAMES: dict[str, str] = {
    "conservative": "Conservative",
    "moderate": "Moderate",
    "aggressive": "Aggressive",
}


def _preset_at_year(track: str, year: int) -> ScenarioPreset:
    """Build a ScenarioPreset for `track` at `year` from the adoption curve."""
    hp, ev = adoption_at_year(track, year)
    name = _TRACK_DISPLAY_NAMES.get(track.lower(), track.title())
    return ScenarioPreset(
        name=name,
        label=f"{name} · {year} ({int(round(hp * 100))}% HP, {int(round(ev * 100))}% EV)",
        heat_pump_adoption_pct=hp,
        ev_adoption_pct=ev,
        description=TRACK_DESCRIPTIONS.get(track.lower(), ""),
    )


class WinterWorkloadAgent(BaseAgent):
    """Stage 1: query → WinterPeakSpec."""

    async def parse_query(
        self,
        query: str,
        progress_callback=None,
    ) -> WinterPeakSpec:
        """
        Parse the raw query into a WinterPeakSpec.
        Uses Claude for intent extraction; falls back to defaults on parse failure.
        """
        self.logger.info(f"Parsing winter peak query: {query}")

        if progress_callback:
            await progress_callback("Parsing stress-test scenario with AI...", 5)

        prompt = f"""Parse this winter-peak stress test request into JSON:

QUERY: "{query}"

Required JSON shape:
{{
  "city_key": "mississauga",  // one of the supported cities
  "cold_event_id": "polar_vortex_2014",  // one of the supported events
  "custom_min_temp_c": null,  // REQUIRED numeric value if cold_event_id == "custom", null otherwise
  "custom_duration_hours": null,  // REQUIRED numeric value if cold_event_id == "custom", null otherwise
  "scenario_keys": ["conservative", "moderate", "aggressive"],  // include all 3 unless user is specific
  "horizon_year": 2030,  // year context for the analysis
  "explicit_hp_pct": null,  // 0.0-1.0 if user gave a specific HP %
  "explicit_ev_pct": null,  // 0.0-1.0 if user gave a specific EV %
  "normalized_name": "Mississauga · 2014 Polar Vortex · Moderate scenario"
}}

If the user mentioned a specific city not in the list, default to "mississauga".
If they gave a specific HP%, set explicit_hp_pct (0.30 for "30%") and put
"custom" as the only scenario_keys entry.

COLD EVENT RULES (important):
- Set cold_event_id to "custom" whenever the user supplied EITHER a specific
  temperature OR a specific duration that doesn't match a preset. Extract
  whichever number(s) they gave; leave the other as null and downstream
  code will fill a sensible default. Examples:
  "-30C" or "minus 30 degrees" -> custom_min_temp_c: -30.0
  "4 days" or "96 hours" or "four-day cold snap" -> custom_duration_hours: 96
  ("3 days" -> 72, "5 days" -> 120, "1 week" -> 168)
- Prefer a preset id when the user's phrasing clearly invokes one:
  "polar vortex", "January 2014", "2014 vortex"             -> "polar_vortex_2014"
  "bomb cyclone", "Elliott", "fast-onset", "rapid drop"      -> "elliott_2022"
  "January 2019", "2019 polar vortex", "short polar vortex"  -> "polar_vortex_2019"
  "February 2015", "deep freeze", "sustained cold month",
    "week-long cold snap", "prolonged cold"                  -> "deep_freeze_feb_2015"
  "Uri", "February 2021", "Texas freeze", "ERCOT event",
    "cross-jurisdictional benchmark"                         -> "winter_storm_uri_2021"
- When choosing between presets, match on event SHAPE not just temperature:
  short and deep -> polar_vortex_2019; long and moderate -> deep_freeze_feb_2015;
  fast-onset -> elliott_2022; extreme sustained -> polar_vortex_2014.
- If the user described a cold event vaguely (e.g. "a really cold snap",
  "a few days of arctic weather") with no numbers and no preset cue,
  default to "polar_vortex_2014".
- If the user said nothing about a cold event at all, default to
  "polar_vortex_2014"."""

        try:
            parsed = await self.ask_claude_json(SYSTEM_WINTER_WORKLOAD, prompt)
        except Exception as e:
            self.logger.warning(f"Workload parse failed, using defaults: {e}")
            parsed = {
                "city_key": "mississauga",
                "cold_event_id": "polar_vortex_2014",
                "scenario_keys": ["conservative", "moderate", "aggressive"],
                "horizon_year": 2030,
                "normalized_name": "Default: Mississauga · 2014 Polar Vortex · all scenarios",
            }

        # Resolve city
        city_key = (parsed.get("city_key") or "mississauga").lower()
        if city_key not in CITY_PROFILES:
            self.logger.warning(f"Unknown city '{city_key}', defaulting to mississauga")
            city_key = "mississauga"
        profile = CITY_PROFILES[city_key]

        horizon_year = int(parsed.get("horizon_year") or 2030)

        # Resolve scenarios at the requested horizon year so adoption %
        # actually reflects the user's "by 2050" / "by 2030" intent.
        scenarios = self._resolve_scenarios(
            parsed.get("scenario_keys", []),
            parsed.get("explicit_hp_pct"),
            parsed.get("explicit_ev_pct"),
            horizon_year=horizon_year,
        )

        # Resolve cold event id
        cold_event_id = parsed.get("cold_event_id") or "polar_vortex_2014"
        if cold_event_id not in {
            "polar_vortex_2014",
            "elliott_2022",
            "polar_vortex_2019",
            "deep_freeze_feb_2015",
            "winter_storm_uri_2021",
            "custom",
        }:
            cold_event_id = "polar_vortex_2014"

        custom_min_temp_c = parsed.get("custom_min_temp_c")
        custom_duration_hours = parsed.get("custom_duration_hours")

        # custom_event() requires both numbers. If the LLM picked "custom" with
        # only one supplied, fill a sensible default for the other rather than
        # silently collapsing to the 2014 reference event (which discards the
        # user's intent). Both missing -> no usable signal, fall back.
        if cold_event_id == "custom":
            if custom_min_temp_c is None and custom_duration_hours is None:
                cold_event_id = "polar_vortex_2014"
            else:
                if custom_min_temp_c is None:
                    # "5-day cold snap" without a temperature — Elliott-grade
                    # severity is a safer default than polar-vortex extreme.
                    custom_min_temp_c = -22.0
                if custom_duration_hours is None:
                    # Temperature given without a duration — 96h (4 days) is a
                    # mid-severity stress window.
                    custom_duration_hours = 96

        spec = WinterPeakSpec(
            query=query,
            normalized_name=parsed.get("normalized_name") or f"{profile.city} winter stress test",
            city=profile.city,
            utility=profile.utility,
            province=profile.province,
            iso_zone=profile.iso_zone,
            cold_event_id=cold_event_id,
            custom_min_temp_c=custom_min_temp_c,
            custom_duration_hours=custom_duration_hours,
            scenarios=scenarios,
            horizon_year=horizon_year,
        )

        if progress_callback:
            await progress_callback(
                f"Parsed: {profile.city} · {cold_event_id} · {len(scenarios)} scenario(s)",
                10,
            )

        # Generate plain-English context summary
        spec.context_summary = await self._summarize_spec(spec)
        return spec

    def _resolve_scenarios(
        self,
        keys: list[str],
        explicit_hp: Optional[float],
        explicit_ev: Optional[float],
        horizon_year: int,
    ) -> list[ScenarioPreset]:
        """Convert scenario keys (or explicit numbers) into ScenarioPreset objects."""
        # User gave explicit % — build a single custom scenario. Their
        # numbers are the user's numbers, not a trajectory; ignore the
        # horizon-year curve here but tag the label with the year so
        # the report still shows the time context the user asked about.
        if explicit_hp is not None or explicit_ev is not None:
            hp = explicit_hp if explicit_hp is not None else 0.25
            ev = explicit_ev if explicit_ev is not None else 0.30
            return [ScenarioPreset(
                name="Custom",
                label=f"User-specified · {horizon_year} ({int(hp*100)}% HP, {int(ev*100)}% EV)",
                heat_pump_adoption_pct=max(0.0, min(1.0, hp)),
                ev_adoption_pct=max(0.0, min(1.0, ev)),
                description=f"User-provided adoption rates for {horizon_year}: {int(hp*100)}% heat pump, {int(ev*100)}% EV.",
            )]

        # Otherwise resolve track keys against the year-anchored curve
        if not keys:
            keys = ["conservative", "moderate", "aggressive"]
        scenarios: list[ScenarioPreset] = []
        for k in keys:
            key = k.lower()
            if key in _TRACK_DISPLAY_NAMES:
                scenarios.append(_preset_at_year(key, horizon_year))
        if not scenarios:
            scenarios = [
                _preset_at_year(t, horizon_year)
                for t in ("conservative", "moderate", "aggressive")
            ]
        return scenarios

    async def _summarize_spec(self, spec: WinterPeakSpec) -> str:
        """Generate a one-paragraph context summary for the report header."""
        scenario_labels = ", ".join(s.label for s in spec.scenarios)
        prompt = f"""Write a one-paragraph (3-4 sentence) plain-English overview of this stress test:

City: {spec.city} ({spec.utility}, {spec.province})
Cold event: {spec.cold_event_id}
Scenarios being tested: {scenario_labels}
Horizon year: {spec.horizon_year}

Tone: confident, expert. Avoid jargon. Mention what's being tested and why
it matters for grid resilience. Do not include a header or markdown. Just
plain text."""

        try:
            return (await self.ask_claude(SYSTEM_WINTER_WORKLOAD, prompt, max_tokens=300)).strip()
        except Exception as e:
            self.logger.warning(f"Spec summary failed: {e}")
            return (
                f"Stress test of {spec.city}'s distribution grid against the "
                f"{spec.cold_event_id} reference event under "
                f"{len(spec.scenarios)} electrification scenario(s)."
            )
