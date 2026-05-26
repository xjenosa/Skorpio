"""
Stage 1 of Neighborhood Electrification Readiness — query → ElectrificationSpec.
"""
from typing import Optional

from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.models.electrification import AdoptionScenario, ElectrificationSpec
from backend.services.statscan import (
    CITY_DEFAULT_FSAS,
    _FSA_REGISTRY,
    default_fsas_for_city,
)


_SUPPORTED_CITY_LIST = ", ".join(sorted(CITY_DEFAULT_FSAS.keys()))

SYSTEM = f"""You are a neighborhood electrification analyst. Your role is to
parse natural-language readiness requests into a structured spec.

Supported cities: {_SUPPORTED_CITY_LIST}.

If the user names a postal code (e.g. M5V), keep just the FSA (first 3
characters). If they name a city only, leave fsas empty and we will fill
in a default sample. If they name a city not on the supported list,
return that city's name verbatim in the `city` field rather than
substituting a different one. The normalizer will fall back gracefully.

Supported scenarios:
  - conservative  (today: 5% HP conversion, 7% EV)
  - moderate      (2030 plans: 25% HP, 30% EV)
  - aggressive    (2035 net-zero: 50% HP, 60% EV)

Always respond with valid JSON. No markdown.""" + GROUNDING_RULES


SCENARIO_PRESETS: dict[str, AdoptionScenario] = {
    "conservative": AdoptionScenario(
        name="Conservative",
        label="Today (5% HP, 7% EV)",
        heat_pump_conversion_pct=0.05,
        ev_adoption_pct=0.07,
        target_year=2025,
        description="Current Canadian residential adoption levels.",
    ),
    "moderate": AdoptionScenario(
        name="Moderate",
        label="2030 Plans (25% HP, 30% EV)",
        heat_pump_conversion_pct=0.25,
        ev_adoption_pct=0.30,
        target_year=2030,
        description="Trajectory consistent with announced provincial 2030 electrification plans.",
    ),
    "aggressive": AdoptionScenario(
        name="Aggressive",
        label="2035 Net-Zero (50% HP, 60% EV)",
        heat_pump_conversion_pct=0.50,
        ev_adoption_pct=0.60,
        target_year=2035,
        description="Pace required for 2035 net-zero electricity targets.",
    ),
}


class ElectrificationWorkloadAgent(BaseAgent):
    async def parse_query(
        self,
        query: str,
        progress_callback=None,
    ) -> ElectrificationSpec:
        self.logger.info(f"Parsing electrification query: {query}")
        if progress_callback:
            await progress_callback("Parsing electrification scope with AI...", 5)

        prompt = f"""Parse this neighborhood electrification readiness request into JSON:

QUERY: "{query}"

Required JSON shape:
{{
  "city": "Toronto",                                  // one of the supported cities
  "fsas": ["M5V", "M5A"],                             // FSAs from query, or [] for whole-city sample
  "scope": "heating_and_ev",                          // "heating_only" | "ev_only" | "heating_and_ev"
  "scenario_keys": ["conservative", "moderate", "aggressive"],
  "horizon_year": 2030,
  "explicit_hp_pct": null,                            // 0.0-1.0 if user gave a specific HP %
  "explicit_ev_pct": null,                            // 0.0-1.0 if user gave a specific EV %
  "normalized_name": "Toronto downtown · 2030 Aggressive scenario"
}}

If the user mentioned only a city, default to that city's sample FSAs.
If they didn't specify scenarios, include all three presets."""

        try:
            parsed = await self.ask_claude_json(SYSTEM, prompt)
        except Exception as e:
            self.logger.warning(f"Workload parse failed, using defaults: {e}")
            parsed = {
                "city": "Toronto",
                "fsas": [],
                "scope": "heating_and_ev",
                "scenario_keys": ["conservative", "moderate", "aggressive"],
                "horizon_year": 2030,
                "normalized_name": "Default: Toronto · 2030 · all scenarios",
            }

        city = (parsed.get("city") or "Toronto").strip()
        # Normalize city to a known one (case-insensitive); else fall back to Toronto.
        known_city = next((k for k in CITY_DEFAULT_FSAS if k.lower() == city.lower()), None)
        if not known_city:
            self.logger.warning(f"Unknown city '{city}', defaulting to Toronto")
            known_city = "Toronto"

        fsas = [str(f).upper().strip()[:3] for f in (parsed.get("fsas") or [])]
        fsas = [f for f in fsas if len(f) == 3 and f[0].isalpha()]
        if not fsas:
            fsas = default_fsas_for_city(known_city)

        # Province inferred from the first matching registry entry
        province = "ON"
        for fsa in fsas:
            if fsa in _FSA_REGISTRY:
                province = _FSA_REGISTRY[fsa]["province"]
                break

        scope = parsed.get("scope") or "heating_and_ev"
        if scope not in {"heating_only", "ev_only", "heating_and_ev"}:
            scope = "heating_and_ev"

        scenarios = self._resolve_scenarios(
            parsed.get("scenario_keys") or [],
            parsed.get("explicit_hp_pct"),
            parsed.get("explicit_ev_pct"),
            parsed.get("horizon_year") or 2030,
        )

        spec = ElectrificationSpec(
            query=query,
            normalized_name=parsed.get("normalized_name") or f"{known_city} electrification readiness",
            city=known_city,
            province=province,
            fsas=fsas,
            scope=scope,
            scenarios=scenarios,
            horizon_year=int(parsed.get("horizon_year") or 2030),
        )

        if progress_callback:
            await progress_callback(
                f"Parsed: {known_city} · {len(fsas)} FSA(s) · {len(scenarios)} scenario(s)",
                10,
            )

        spec.context_summary = await self._summarize(spec)
        return spec

    def _resolve_scenarios(
        self,
        keys: list[str],
        explicit_hp: Optional[float],
        explicit_ev: Optional[float],
        horizon_year: int,
    ) -> list[AdoptionScenario]:
        if explicit_hp is not None or explicit_ev is not None:
            hp = explicit_hp if explicit_hp is not None else 0.25
            ev = explicit_ev if explicit_ev is not None else 0.30
            return [AdoptionScenario(
                name="Custom",
                label=f"User-specified ({int(hp*100)}% HP, {int(ev*100)}% EV)",
                heat_pump_conversion_pct=max(0.0, min(1.0, hp)),
                ev_adoption_pct=max(0.0, min(1.0, ev)),
                target_year=int(horizon_year),
                description=f"User-provided adoption rates for {horizon_year}.",
            )]

        if not keys:
            keys = ["conservative", "moderate", "aggressive"]
        out: list[AdoptionScenario] = []
        for k in keys:
            preset = SCENARIO_PRESETS.get(k.lower())
            if preset is not None:
                out.append(preset)
        if not out:
            out = list(SCENARIO_PRESETS.values())
        return out

    async def _summarize(self, spec: ElectrificationSpec) -> str:
        scenario_labels = ", ".join(s.label for s in spec.scenarios)
        prompt = f"""Write a one-paragraph (3-4 sentence) plain-English overview of this electrification readiness study:

City: {spec.city} ({spec.province})
FSAs: {', '.join(spec.fsas) if spec.fsas else '(city sample)'}
Scope: {spec.scope.replace('_', ' ')}
Scenarios: {scenario_labels}
Horizon year: {spec.horizon_year}

Tone: confident, expert. Avoid jargon. Mention what's being assessed and
why it matters for neighborhood-level grid planning. Do not include a
header or markdown — just plain text."""
        try:
            return (await self.ask_claude(SYSTEM, prompt, max_tokens=300)).strip()
        except Exception as e:
            self.logger.warning(f"Spec summary failed: {e}")
            return (
                f"Readiness assessment of {len(spec.fsas)} FSA(s) in {spec.city} "
                f"under {len(spec.scenarios)} electrification scenario(s) for {spec.horizon_year}."
            )
