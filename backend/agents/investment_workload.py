"""
Stage 1 of Climate-Adapted Grid Investment Optimizer — query → InvestmentSpec.
"""
import re

from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.models.investment import InvestmentSpec


SYSTEM = """You are a utility capital-planning analyst. Your role is to parse
natural-language climate-investment requests into a structured spec.

Supported utilities (use the canonical name):
  - Hydro One           (province: ON) — bulk transmission + rural distribution
  - Toronto Hydro       (province: ON) — Toronto core distribution
  - Alectra Utilities   (province: ON) — distribution across the GTHA
                                         (Mississauga, Brampton, Hamilton,
                                         Vaughan, Markham, St. Catharines, …)
  - EPCOR               (province: AB)
  - Hydro-Québec        (province: QC)

Region → utility routing hints:
  - "GTHA" / "Greater Toronto and Hamilton Area" / "GTA distribution"
    / a city in Alectra's territory (Mississauga, Brampton, Hamilton,
    Vaughan, Markham, St. Catharines) → "Alectra Utilities"
  - "Toronto" / city of Toronto only → "Toronto Hydro"
  - rural Ontario / 500 kV transmission / bulk grid → "Hydro One"

Supported hazards (any subset, order = priority):
  - ice_storm, heat_wave, wildfire, flood, wind

Always respond with valid JSON. No markdown.""" + GROUNDING_RULES


_DEFAULT_BUDGET = 500_000_000


def _budget_from_text(query: str) -> float | None:
    """Pull a dollar amount from the query, supporting $500M / 1B / 250 million / etc."""
    m = re.search(r"\$?\s*(\d+(?:\.\d+)?)\s*([mMbB]|million|billion)?", query)
    if not m:
        return None
    n = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit.startswith("b") or unit == "billion":
        return n * 1_000_000_000
    if unit.startswith("m") or unit == "million":
        return n * 1_000_000
    return n if n > 1000 else None  # raw small numbers aren't a budget


class InvestmentWorkloadAgent(BaseAgent):
    async def parse_query(self, query: str, progress_callback=None) -> InvestmentSpec:
        self.logger.info(f"Parsing investment query: {query}")
        if progress_callback:
            await progress_callback("Parsing investment scope with AI...", 5)

        prompt = f"""Parse this climate-adapted grid investment request into JSON:

QUERY: "{query}"

Required JSON shape:
{{
  "utility": "Hydro One",
  "province": "ON",
  "budget_cad": 500000000,
  "horizon_years": 5,
  "target_year": 2030,
  "priority_hazards": ["ice_storm", "heat_wave"],
  "normalized_name": "Hydro One · $500M · 2030 · ice & heat"
}}

If the user didn't name a utility, default to "Hydro One".
If they didn't specify a budget, leave budget_cad as null (we'll default).
If priority_hazards weren't mentioned, leave as []."""

        try:
            parsed = await self.ask_claude_json(SYSTEM, prompt)
        except Exception as e:
            self.logger.warning(f"Workload parse failed, using defaults: {e}")
            parsed = {
                "utility": "Hydro One",
                "province": "ON",
                "horizon_years": 5,
                "target_year": 2030,
                "priority_hazards": [],
                "normalized_name": f"Default: Hydro One 2030 portfolio",
            }

        utility = (parsed.get("utility") or "Hydro One").strip()
        province = (parsed.get("province") or "ON").strip().upper()
        budget = parsed.get("budget_cad")
        if not budget:
            budget = _budget_from_text(query) or _DEFAULT_BUDGET
        budget = float(max(50_000_000, budget))      # floor at $50M to keep the optimizer interesting

        horizon = int(parsed.get("horizon_years") or 5)
        horizon = max(1, min(30, horizon))
        target_year = int(parsed.get("target_year") or 2030)

        hazards = [str(h).lower() for h in (parsed.get("priority_hazards") or [])]
        hazards = [h for h in hazards if h in {"ice_storm", "heat_wave", "wildfire", "flood", "wind"}]

        spec = InvestmentSpec(
            query=query,
            normalized_name=parsed.get("normalized_name") or f"{utility} · ${budget/1e6:.0f}M · {target_year}",
            utility=utility,
            province=province,
            budget_cad=budget,
            horizon_years=horizon,
            target_year=target_year,
            priority_hazards=hazards,
        )

        if progress_callback:
            await progress_callback(
                f"Parsed: {utility} · ${budget/1e6:.0f}M · {horizon}y horizon · {target_year} target",
                10,
            )

        spec.context_summary = await self._summarize(spec)
        return spec

    async def _summarize(self, spec: InvestmentSpec) -> str:
        hazards = ", ".join(spec.priority_hazards) if spec.priority_hazards else "all hazards"
        prompt = f"""Write a one-paragraph (3-4 sentence) plain-English overview of this climate-adapted grid investment study:

Utility: {spec.utility} ({spec.province})
Budget: ${spec.budget_cad/1e6:.0f}M
Horizon: {spec.horizon_years} years
Target year: {spec.target_year}
Priority hazards: {hazards}

Tone: confident, expert. Avoid jargon. Mention what's being optimized and
why it matters for grid resilience under climate change. No markdown."""
        try:
            return (await self.ask_claude(SYSTEM, prompt, max_tokens=300)).strip()
        except Exception as e:
            self.logger.warning(f"Spec summary failed: {e}")
            return (
                f"Capital-allocation study for {spec.utility}: optimize ${spec.budget_cad/1e6:.0f}M "
                f"of hardening investment over {spec.horizon_years} years against {spec.target_year} climate exposure."
            )
