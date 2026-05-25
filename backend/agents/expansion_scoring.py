"""
Stage 4 of Expansion Planner — score each candidate option on 5 axes,
rank by overall, and pick the budget-fit subset that covers target_mw.

Axes:
  grid           — transformer headroom + fiber density at the option's location
  sustainability — lower g/kWh + better PUE + cooling type
  speed          — brownfield (~18mo) beats greenfield (~30mo)
  cost           — lower capex_per_mw is better
  risk           — newer plot + larger headroom = lower risk
"""
import asyncio

from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.grid.expansion_modeling import generate_options
from backend.models.expansion import (
    DemandForecast,
    ExpansionOption,
    ExpansionSpec,
    OperatorFootprint,
)


SYSTEM = """You are a datacenter portfolio planner writing a one-sentence
rationale for an expansion option. Be specific and numeric. No markdown.""" + GROUNDING_RULES


# 10-20 options typical; cap at 4 concurrent rationale calls to stay safe
# on Opus tier-1 output-TPM. Same pattern as the other pipelines.
_RATIONALE_SEMAPHORE = asyncio.Semaphore(4)


# Capex-per-MW bounds for normalization. Anything below the low bound scores
# 1.0; anything above the high bound scores 0.0.
_CAPEX_LOW = 9_000_000
_CAPEX_HIGH = 18_000_000

# Carbon bounds (g CO₂eq / kWh).
_CARBON_LOW = 20.0
_CARBON_HIGH = 400.0


def _norm_inverse(value: float, low: float, high: float) -> float:
    """Map [low..high] → [1..0] with clamps."""
    if high <= low:
        return 0.5
    return max(0.0, min(1.0, 1.0 - (value - low) / (high - low)))


# Brownfield bonus applied when the option's target_site_id matches the
# user-pinned site from ExpansionSpec.target_site_id. Sized so it can flip
# ranking against a marginally-better non-pinned option (e.g. one with a
# 0.05 cost edge) but not against a structurally-broken one (e.g. one with
# 0.4 less headroom). 0.12 is the empirical sweet spot — small enough that
# the optimizer still prefers a clearly-better Vaughan-adjacent greenfield
# over a Vaughan brownfield with zero headroom, large enough that a tie
# with the user's named campus resolves in favor of the named campus.
_PINNED_SITE_BONUS = 0.12


def _score_option(
    opt: ExpansionOption,
    parent: dict[str, dict] | None,
    spec: ExpansionSpec,
) -> ExpansionOption:
    """Populate opt's 5 axis scores + overall + rationale-blockers. Returns the same obj."""
    is_brownfield = opt.option_type == "brownfield"
    parent_meta = parent.get(opt.target_site_id, {}) if (parent and opt.target_site_id) else {}
    fiber_n = int(parent_meta.get("fiber_count", 3 if is_brownfield else 2))
    headroom_mw = float(parent_meta.get("transformer_headroom_mw", opt.new_capacity_mw))
    age_years = int(parent_meta.get("age_years", 5))
    pue = float(parent_meta.get("pue", 1.30 if is_brownfield else 1.25))
    cooling = str(parent_meta.get("cooling", "hybrid"))

    grid = max(0.0, min(1.0, (headroom_mw / max(1.0, opt.new_capacity_mw)) * 0.6 + min(1.0, fiber_n / 5) * 0.4))
    sustainability = (
        _norm_inverse(opt.avg_carbon_g_kwh, _CARBON_LOW, _CARBON_HIGH) * 0.6
        + _norm_inverse(pue, 1.10, 1.50) * 0.25
        + (0.15 if cooling in ("free_air", "liquid_immersion", "hybrid") else 0.0)
    )
    speed = 0.95 if is_brownfield else 0.55
    cost = _norm_inverse(opt.capex_per_mw_cad, _CAPEX_LOW, _CAPEX_HIGH)
    # Brownfield + recent commissioning = low risk. Greenfield = elevated risk.
    risk_age_penalty = max(0.0, (age_years - 10) / 30.0)
    risk = (0.85 if is_brownfield else 0.55) - risk_age_penalty
    risk = max(0.0, min(1.0, risk))

    # Weights — match the typical operator's expansion-committee scoring.
    overall = (
        grid * 0.25
        + sustainability * 0.20
        + speed * 0.20
        + cost * 0.20
        + risk * 0.15
    )

    # Pinned-site bias: when the user named a specific campus (resolved into
    # spec.target_site_id by the workload agent), nudge the brownfield option
    # at that campus upward so the funded plan reflects "expand what the user
    # asked about". Clamped to [0,1] so the bonus never pushes the score out
    # of band even when overall was already near 1.0.
    if spec.target_site_id and opt.target_site_id == spec.target_site_id:
        overall = min(1.0, overall + _PINNED_SITE_BONUS)

    blockers: list[str] = []
    if headroom_mw < opt.new_capacity_mw * 0.6:
        blockers.append(f"Transformer headroom ({headroom_mw:.0f} MW) below option size, may need utility upgrade")
    if not is_brownfield:
        blockers.append("Greenfield permitting and build add 24 to 36 months on top of base schedule")
    if cooling == "air" and spec.workload_mix == "ai_training":
        blockers.append("Air cooling limits rack density, AI training will need a liquid retrofit")

    opt.grid_score = round(grid, 3)
    opt.sustainability_score = round(sustainability, 3)
    opt.speed_score = round(speed, 3)
    opt.cost_score = round(cost, 3)
    opt.risk_score = round(risk, 3)
    opt.overall_score = round(overall, 3)
    opt.blockers = blockers
    return opt


def _greedy_fund(options: list[ExpansionOption], target_mw: float) -> list[ExpansionOption]:
    """Take highest-overall options until cumulative MW meets target_mw × 1.0."""
    ranked = sorted(options, key=lambda o: o.overall_score, reverse=True)
    funded: list[ExpansionOption] = []
    total = 0.0
    for opt in ranked:
        if total >= target_mw and len(funded) >= 1:
            break
        funded.append(opt)
        total += opt.new_capacity_mw
    return funded


class ExpansionScoringAgent(BaseAgent):
    async def score(
        self,
        spec: ExpansionSpec,
        footprint: OperatorFootprint,
        demand: DemandForecast,
        progress_callback=None,
        progress_offset_pct: int = 50,
    ) -> tuple[list[ExpansionOption], list[ExpansionOption]]:
        """Returns (all_scored_options, funded_subset)."""
        if progress_callback:
            await progress_callback("Generating candidate expansion options...", progress_offset_pct)

        options = generate_options(spec, footprint, demand)
        parent_meta = {
            s.site_id: {
                "fiber_count": len(s.fiber_providers),
                "transformer_headroom_mw": s.transformer_headroom_mw,
                "age_years": max(0, 2026 - s.year_commissioned),
                "pue": s.pue,
                "cooling": s.cooling,
            }
            for s in footprint.sites
        }

        # Phase 1 — score every option synchronously (pure functions, no Claude).
        for opt in options:
            _score_option(opt, parent_meta, spec)

        if progress_callback and options:
            await progress_callback(
                f"Generating rationales for {len(options)} expansion options in parallel...",
                progress_offset_pct + 8,
            )

        # Phase 2 — gather rationale Claude calls under the global semaphore.
        async def _one_rationale(opt: ExpansionOption) -> str:
            async with _RATIONALE_SEMAPHORE:
                return await self._rationale(opt, spec)

        rationales = await asyncio.gather(*(_one_rationale(opt) for opt in options))
        for opt, rationale in zip(options, rationales):
            opt.rationale = rationale

        if progress_callback and options:
            await progress_callback(
                f"Scored {len(options)} expansion options",
                progress_offset_pct + 22,
            )

        # Rank
        options.sort(key=lambda o: o.overall_score, reverse=True)
        for r, o in enumerate(options, start=1):
            o.rank = r

        # Pick funded subset that meets target MW (greedy on score).
        funded = _greedy_fund(options, spec.target_additional_mw)

        if progress_callback:
            funded_mw = sum(o.new_capacity_mw for o in funded)
            await progress_callback(
                f"Selected {len(funded)} option(s) covering {funded_mw:.0f} MW of {spec.target_additional_mw:.0f} MW target",
                progress_offset_pct + 25,
            )
        return options, funded

    async def _rationale(self, opt: ExpansionOption, spec: ExpansionSpec) -> str:
        prompt = f"""Write a one-sentence justification for this datacenter expansion option:

Title: {opt.title}
Type: {opt.option_type}
New capacity: +{opt.new_capacity_mw:.0f} MW
Capex: ${opt.capex_cad/1e6:.0f}M (${opt.capex_per_mw_cad/1e6:.1f}M/MW)
Deployment: {opt.deployment_months} months
Grid carbon: {opt.avg_carbon_g_kwh:.0f} g/kWh
Workload mix: {spec.workload_mix.replace('_', ' ')}
Scores (0–1): grid={opt.grid_score} sustain={opt.sustainability_score} speed={opt.speed_score} cost={opt.cost_score} risk={opt.risk_score}

Be concrete and numeric. Plain text. One sentence."""
        try:
            return (await self.ask_claude(SYSTEM, prompt, max_tokens=140)).strip()
        except Exception as e:
            self.logger.warning(f"Option rationale failed: {e}")
            return (
                f"{opt.option_type.title()} adds {opt.new_capacity_mw:.0f} MW at "
                f"${opt.capex_per_mw_cad/1e6:.1f}M/MW in {opt.deployment_months}mo."
            )
