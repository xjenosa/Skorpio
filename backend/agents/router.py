"""
Pipeline Router Agent.

Classifies a free-form natural-language prompt into one of the five Skorpio
pipelines so the orchestrator can dispatch correctly. Replaces the
frontend's regex-only `inferPipelineFromPrompt` stub.

Defaults to Claude Haiku 4.5 — a short classification call (~250 tokens
in, ~80 out) runs at <$0.001 per submission, which is negligible vs the
multi-stage pipeline that follows. The same allowlist of models guards
against arbitrary model overrides.

Fallback: if Claude fails (network, rate limit, malformed JSON), we fall
back to the same keyword regex the frontend used to ship. Never blocks
the user — worst case they get the regex's guess.
"""
import re
from typing import Optional

from backend.agents.base_agent import BaseAgent


# Default to Haiku so this stays cheap. Operators can override via the
# `model` param on POST /api/route if they want to evaluate Sonnet/Opus.
DEFAULT_ROUTER_MODEL = "claude-haiku-4-5-20251001"


# Mirror of the frontend PIPELINES catalog — keep in sync with
# frontend/src/pipelines.ts. The router uses this both for the system
# prompt and for validating Claude's output.
PIPELINE_CATALOG: list[dict] = [
    {
        "id": "datacenter-siting",
        "label": "Datacenter Siting",
        "scope": (
            "Pick the best NEW location (fresh greenfield) for an AI/HPC "
            "datacenter in Canada. Optimizes for grid carbon, latency, cost. "
            "Use when the user is starting from no site."
        ),
        "signals": ["find a site", "best location", "where should I site", "greenfield datacenter"],
    },
    {
        "id": "datacenter-expansion",
        "label": "Datacenter Expansion Planner",
        "scope": (
            "Grow an existing datacenter operator's footprint with brownfield "
            "phases at existing sites plus 1-2 greenfield neighbors. "
            "Use when the user names an existing operator (eStruxture, "
            "Cologix, Equinix, Hyperion, Q-Scale) or asks to 'expand' or "
            "'add MW at our site'."
        ),
        "signals": ["expansion", "expand", "grow capacity", "add MW", "next phase"],
    },
    {
        "id": "winter-peak-stress",
        "label": "Winter Peak Stress Tester",
        "scope": (
            "Simulate extreme cold on a regional grid: heat pump COP loss, "
            "EV cold-weather draw, baseboard spikes. Use when the user "
            "names a cold event (polar vortex, Elliott, -25°C), or asks "
            "about winter peak / stress test."
        ),
        "signals": ["polar vortex", "cold snap", "winter peak", "stress test", "-25°C"],
    },
    {
        "id": "electrification-readiness",
        "label": "Neighborhood Electrification Readiness",
        "scope": (
            "Score how READY a Canadian neighborhood (named by FSA like M5V "
            "or by city name + zone) is for full electrification (heat "
            "pumps and EVs). Use when the user names FSAs / postal codes / "
            "neighborhoods and asks about readiness or scoring, not stress."
        ),
        "signals": ["neighborhood", "FSA", "postal code", "readiness", "score the", "EV + heat pump"],
    },
    {
        "id": "grid-investment-optimizer",
        "label": "Climate-Adapted Grid Investment Optimizer",
        "scope": (
            "Allocate a fixed CAPITAL BUDGET across grid hardening projects "
            "for the best ROI under climate scenarios. Use when the user "
            "mentions a dollar amount, a utility name (Hydro One, Toronto "
            "Hydro, EPCOR, Hydro-Québec), and an investment / budget framing."
        ),
        "signals": ["$", "M budget", "B budget", "allocate", "invest", "spend", "hardening"],
    },
]


VALID_PIPELINE_IDS = {p["id"] for p in PIPELINE_CATALOG}


def _build_system_prompt() -> str:
    lines = [
        "You are the Skorpio pipeline router. Classify a user's free-form "
        "natural-language question into exactly ONE of these five pipelines:",
        "",
    ]
    for p in PIPELINE_CATALOG:
        lines.append(f"- {p['id']}  →  {p['label']}")
        lines.append(f"    {p['scope']}")
        lines.append(f"    Strong signals: {', '.join(p['signals'])}")
        lines.append("")
    lines.append(
        "Decision rules:\n"
        "  • If the user names a datacenter OPERATOR + wants to add capacity → datacenter-expansion.\n"
        "  • If the user mentions a UTILITY + a DOLLAR BUDGET → grid-investment-optimizer.\n"
        "  • If the user mentions COLD WEATHER + heat pumps / EV draw → winter-peak-stress.\n"
        "  • If the user names FSAs / postal codes / neighborhoods + 'readiness' → electrification-readiness.\n"
        "  • If the user wants a NEW site from scratch → datacenter-siting.\n"
        "  • When ambiguous, prefer the more specific pipeline. Datacenter-siting is the catch-all."
        "\n\n"
        "REJECTION RULES. Set off_topic=true if ANY of these apply:\n"
        "  • The prompt isn't about Canadian (or comparative) energy grids, datacenters, "
        "electrification, climate-grid investment, or related infrastructure planning.\n"
        "  • The prompt is a general LLM request (write a poem, summarize an article, "
        "answer trivia, explain a concept unrelated to grids).\n"
        "  • The prompt is gibberish, a test string ('asdfasdf', 'test test'), or a single "
        "word with no scenario context.\n"
        "  • The prompt is a meta-question about Skorpio itself rather than a workload "
        "request ('what can you do?', 'how does this work?').\n"
        "\n"
        "MULTI-LOCATION RULE. Set multi_location=true if the user mentions MORE THAN ONE "
        "distinct geographic target (e.g. 'Toronto AND Montreal', 'compare Ontario vs Alberta', "
        "'M5V and M4Y'). Skorpio runs one location per submission."
    )
    return "\n".join(lines)


SYSTEM_ROUTER = _build_system_prompt()


# Regex fallback — same shape as the frontend's inferPipelineFromPrompt.
# Used only when Claude fails. Returns ('pipeline_id', 'regex-fallback') so
# the caller can surface that this was a degraded path.
def _regex_fallback(prompt: str) -> str:
    p = prompt.lower()
    if re.search(r"(polar vortex|cold snap|winter peak|stress[- ]?test|cold weather|-\s?\d{2}\s?°?c)", p):
        return "winter-peak-stress"
    if re.search(r"(neighborhood|electrification|fsa|postal|heat pump|ev (adoption|growth)|score (the|a) [a-z])", p):
        return "electrification-readiness"
    if re.search(r"(invest|budget|allocate|spend|\$\d|grid upgrade|hardening)", p):
        return "grid-investment-optimizer"
    if re.search(r"(expansion|expand|grow capacity|add capacity|next phase)", p):
        return "datacenter-expansion"
    return "datacenter-siting"


class RouterAgent(BaseAgent):
    """Classifies prompts into Skorpio pipelines via Claude (default Haiku)."""

    def __init__(self, model: Optional[str] = None):
        super().__init__(model=model or DEFAULT_ROUTER_MODEL)

    async def classify(self, prompt: str) -> dict:
        """
        Returns:
          {
            "pipeline_id":    "winter-peak-stress" | None,
            "confidence":     0.92,                          # 0..1
            "rationale":      "Query names a polar vortex...",
            "source":         "claude" | "regex-fallback",   # how it was decided
            "off_topic":      bool,                          # True → reject the request
            "multi_location": bool,                          # True → reject with "one at a time"
            "reject_reason":  str | None,                    # message for the user when rejected
          }
        """
        prompt = (prompt or "").strip()
        if not prompt:
            return {
                "pipeline_id": None,
                "confidence": 0.0,
                "rationale": "Empty prompt.",
                "source": "regex-fallback",
                "off_topic": True,
                "multi_location": False,
                "reject_reason": "Describe what you want Skorpio to do. Try one of the example prompts.",
            }

        user_msg = (
            f'Classify this prompt:\n\nPROMPT: "{prompt}"\n\n'
            "Respond with ONLY valid JSON (no markdown, no preamble) in this shape:\n"
            '{\n'
            '  "pipeline_id":    "<one of the five ids above>",\n'
            '  "confidence":     <0.0 to 1.0>,\n'
            '  "rationale":      "<one short sentence, max 25 words>",\n'
            '  "off_topic":      <true if the prompt is not about grids/energy/datacenters>,\n'
            '  "multi_location": <true if the prompt names more than one distinct location>\n'
            '}'
        )

        try:
            parsed = await self.ask_claude_json(SYSTEM_ROUTER, user_msg, max_tokens=240)
        except Exception as e:
            self.logger.warning(f"Router classification failed, falling back to regex: {e}")
            return {
                "pipeline_id": _regex_fallback(prompt),
                "confidence": 0.40,
                "rationale": "Claude classifier unavailable; keyword fallback used.",
                "source": "regex-fallback",
                "off_topic": False,
                "multi_location": False,
                "reject_reason": None,
            }

        off_topic = bool(parsed.get("off_topic", False))
        multi_location = bool(parsed.get("multi_location", False))

        pid = (parsed.get("pipeline_id") or "").strip()
        if pid not in VALID_PIPELINE_IDS:
            pid = _regex_fallback(prompt) if not off_topic else None
            source = "regex-fallback"
            confidence = 0.40
            rationale = f"Classifier returned unknown pipeline; keyword fallback used."
        else:
            source = "claude"
            try:
                confidence = float(parsed.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            confidence = max(0.0, min(1.0, confidence))
            rationale = str(parsed.get("rationale") or "").strip() or f"Classified as {pid}."

        reject_reason: Optional[str] = None
        if off_topic:
            reject_reason = (
                "That prompt doesn't look like a Skorpio request. "
                "Skorpio analyzes Canadian energy grids, datacenter siting, electrification "
                "readiness, climate investment, and winter peak stress. "
                "Try one of the example prompts on the home page."
            )
        elif multi_location:
            reject_reason = (
                "Skorpio runs one location per submission. "
                "Please rephrase with a single city, FSA, or region, "
                "and re-run for each additional location separately."
            )

        return {
            "pipeline_id": None if off_topic else pid,
            "confidence": round(confidence, 2),
            "rationale": rationale,
            "source": source,
            "off_topic": off_topic,
            "multi_location": multi_location,
            "reject_reason": reject_reason,
        }
