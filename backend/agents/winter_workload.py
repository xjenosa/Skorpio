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
  - polar_vortex_2014  (5-day Arctic outbreak, -25.5°C)
  - elliott_2022       (3-day bomb cyclone, -22°C)
  - custom             (user specifies min_temp_c and duration_hours)

Supported scenario presets (use multiple if user is unclear):
  - conservative  (today: 5% heat pump adoption, 7% EV)
  - moderate      (2030 plans: 25% HP, 30% EV)
  - aggressive    (2035 net-zero: 50% HP, 60% EV)

If the user mentions a specific HP/EV percentage, set scenario to "custom"
and include the explicit values.

Always respond with valid JSON. No markdown.""" + GROUNDING_RULES


# ── Built-in scenario presets ─────────────────────────────────────────── #


SCENARIO_PRESETS: dict[str, ScenarioPreset] = {
    "conservative": ScenarioPreset(
        name="Conservative",
        label="Today (5% HP, 7% EV)",
        heat_pump_adoption_pct=0.05,
        ev_adoption_pct=0.07,
        description="Current Canadian residential adoption levels (2024).",
    ),
    "moderate": ScenarioPreset(
        name="Moderate",
        label="2030 Plans (25% HP, 30% EV)",
        heat_pump_adoption_pct=0.25,
        ev_adoption_pct=0.30,
        description="Trajectory consistent with announced provincial 2030 electrification plans.",
    ),
    "aggressive": ScenarioPreset(
        name="Aggressive",
        label="2035 Net-Zero (50% HP, 60% EV)",
        heat_pump_adoption_pct=0.50,
        ev_adoption_pct=0.60,
        description="Pace required for 2035 net-zero electricity targets.",
    ),
}


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
  "custom_min_temp_c": null,  // only if cold_event_id == "custom"
  "custom_duration_hours": null,  // only if cold_event_id == "custom"
  "scenario_keys": ["conservative", "moderate", "aggressive"],  // include all 3 unless user is specific
  "horizon_year": 2030,  // year context for the analysis
  "explicit_hp_pct": null,  // 0.0-1.0 if user gave a specific HP %
  "explicit_ev_pct": null,  // 0.0-1.0 if user gave a specific EV %
  "normalized_name": "Mississauga · 2014 Polar Vortex · Moderate scenario"
}}

If the user mentioned a specific city not in the list, default to "mississauga".
If they didn't mention a cold event, default to "polar_vortex_2014".
If they gave a specific HP%, set explicit_hp_pct (0.30 for "30%") and put
"custom" as the only scenario_keys entry."""

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

        # Resolve scenarios
        scenarios = self._resolve_scenarios(
            parsed.get("scenario_keys", []),
            parsed.get("explicit_hp_pct"),
            parsed.get("explicit_ev_pct"),
        )

        # Resolve cold event id
        cold_event_id = parsed.get("cold_event_id") or "polar_vortex_2014"
        if cold_event_id not in {"polar_vortex_2014", "elliott_2022", "custom"}:
            cold_event_id = "polar_vortex_2014"

        spec = WinterPeakSpec(
            query=query,
            normalized_name=parsed.get("normalized_name") or f"{profile.city} winter stress test",
            city=profile.city,
            utility=profile.utility,
            province=profile.province,
            iso_zone=profile.iso_zone,
            cold_event_id=cold_event_id,
            custom_min_temp_c=parsed.get("custom_min_temp_c"),
            custom_duration_hours=parsed.get("custom_duration_hours"),
            scenarios=scenarios,
            horizon_year=int(parsed.get("horizon_year") or 2030),
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
    ) -> list[ScenarioPreset]:
        """Convert scenario keys (or explicit numbers) into ScenarioPreset objects."""
        # User gave explicit % — build a single custom scenario
        if explicit_hp is not None or explicit_ev is not None:
            hp = explicit_hp if explicit_hp is not None else 0.25
            ev = explicit_ev if explicit_ev is not None else 0.30
            return [ScenarioPreset(
                name="Custom",
                label=f"User-specified ({int(hp*100)}% HP, {int(ev*100)}% EV)",
                heat_pump_adoption_pct=max(0.0, min(1.0, hp)),
                ev_adoption_pct=max(0.0, min(1.0, ev)),
                description=f"User-provided adoption rates: {int(hp*100)}% heat pump, {int(ev*100)}% EV.",
            )]

        # Otherwise resolve preset keys
        if not keys:
            keys = ["conservative", "moderate", "aggressive"]
        scenarios = []
        for k in keys:
            preset = SCENARIO_PRESETS.get(k.lower())
            if preset is not None:
                scenarios.append(preset)
        if not scenarios:
            scenarios = list(SCENARIO_PRESETS.values())
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
