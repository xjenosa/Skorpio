"""
Cold-Event Simulation Agent — Stage 3 of the Winter Peak pipeline.

Runs the deterministic hourly load simulation across all scenarios. The
heavy lifting lives in `backend.grid.winter_simulator`; this agent
composes scenario runs, persists per-scenario load curves, and uses
Claude to generate plain-English narration of what the curves show.
"""
from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.grid.winter_simulator import simulate_network
from backend.models.winter_peak import (
    ColdEvent,
    DistributionNetwork,
    HourlyLoadProfile,
    ScenarioPreset,
)


SYSTEM_COLD_SIM = """You are a residential load-forecasting analyst.
Given hourly load curve summary numbers, explain what's happening in
plain English — when the peak hits, why it hits then, and how the load
is composed (heat pump, baseboard, EV, base). Do NOT be hyperbolic; do
NOT exaggerate. Numbers come from a deterministic simulator, not Claude.""" + GROUNDING_RULES


class ColdEventSimAgent(BaseAgent):
    """Stage 3: (DistributionNetwork, ColdEvent, scenarios) → load profiles."""

    async def run_scenarios(
        self,
        network: DistributionNetwork,
        cold_event: ColdEvent,
        scenarios: list[ScenarioPreset],
        progress_callback=None,
    ) -> dict[str, HourlyLoadProfile]:
        """
        Run the simulator for each scenario; return {scenario_name: profile}.
        """
        results: dict[str, HourlyLoadProfile] = {}
        n = max(1, len(scenarios))

        for i, scenario in enumerate(scenarios):
            if progress_callback:
                pct = 30 + int((i / n) * 30)
                await progress_callback(
                    f"Simulating {scenario.label}...",
                    pct,
                )

            self.logger.info(
                f"Running scenario '{scenario.name}' for {network.city} × {cold_event.event_id}"
            )
            profile = simulate_network(network, cold_event, scenario)
            self.logger.info(
                f"  → peak {profile.peak_load_mw} MW at hour {profile.peak_hour_offset} "
                f"(temp {profile.peak_temp_c}°C, headroom {profile.headroom_at_peak_mw} MW)"
            )
            results[scenario.name] = profile

        return results

    async def narrate_profile(
        self,
        scenario: ScenarioPreset,
        profile: HourlyLoadProfile,
        cold_event: ColdEvent,
    ) -> str:
        """Plain-English narration of one scenario's load curve."""
        # Snapshot the peak hour breakdown
        peak = next(
            (h for h in profile.hours if h.hour_offset == profile.peak_hour_offset),
            None,
        )
        if peak is None:
            return f"Peak {profile.peak_load_mw} MW at hour {profile.peak_hour_offset}."

        breakdown_pct = {
            "base": peak.base_load_mw / max(1.0, peak.total_load_mw),
            "heat_pump": peak.heat_pump_load_mw / max(1.0, peak.total_load_mw),
            "backup_resistance": peak.backup_resistance_mw / max(1.0, peak.total_load_mw),
            "baseboard": peak.baseboard_load_mw / max(1.0, peak.total_load_mw),
            "ev": peak.ev_load_mw / max(1.0, peak.total_load_mw),
            "other": peak.other_load_mw / max(1.0, peak.total_load_mw),
        }
        bd_str = ", ".join(f"{k} {v*100:.0f}%" for k, v in breakdown_pct.items() if v > 0.02)

        prompt = f"""Narrate this load curve in 3-4 sentences:

Scenario: {scenario.label}
Cold event: {cold_event.name}
Peak load: {profile.peak_load_mw} MW
Peak hour offset: {profile.peak_hour_offset} (temp {profile.peak_temp_c}°C)
Headroom at peak: {profile.headroom_at_peak_mw} MW ({profile.headroom_pct_at_peak}%)
Peak hour load mix: {bd_str}

Mention: when the peak hits, why (the temperature + the time-of-day),
and which load category dominates. Be honest about whether headroom is
healthy (>20%), tight (5-20%), or stressed (<5% or negative)."""

        try:
            return (await self.ask_claude(SYSTEM_COLD_SIM, prompt, max_tokens=300)).strip()
        except Exception as e:
            self.logger.warning(f"Profile narration failed: {e}")
            return (
                f"{scenario.label}: peak load of {profile.peak_load_mw} MW at hour "
                f"{profile.peak_hour_offset} (temp {profile.peak_temp_c}°C), "
                f"headroom {profile.headroom_at_peak_mw} MW."
            )
