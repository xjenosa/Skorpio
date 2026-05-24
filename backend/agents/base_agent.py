"""
Base class for every Skorpio pipeline agent.

Each concrete agent (workload parser, scoring agent, synthesis agent, …)
subclasses ``BaseAgent`` to inherit:
  * an ``AsyncAnthropic`` client wired with our API key,
  * the project-wide model default (overridable per-instance),
  * a logger named after the subclass,
  * a tiny call-stats record so synthesis agents can detect when a
    ``max_tokens`` truncation happened and flag it on the final report.

The class intentionally stops short of building a generic LLM toolkit —
each agent owns its own prompt templates and result parsing. This file
only takes care of the bits every agent needs.
"""

from __future__ import annotations

import asyncio
import json
import re
from abc import ABC
from dataclasses import dataclass, field
from typing import Any

import anthropic

from backend.config import settings
from backend.utils.logger import get_logger


# ── Transient-failure retry policy ────────────────────────────────────── #
#
# Anthropic's API occasionally returns 529 (overloaded) or 503 (service
# unavailable) during regional capacity spikes; network blips surface as
# ``APIConnectionError`` / ``APITimeoutError``. All four are transient and
# almost always clear within a few seconds, so every Claude call retries
# with exponential backoff before surfacing the failure.
#
# Delays are seconds between attempts — len(tuple) == number of retries,
# so (1, 2, 4) means up to 4 total attempts. Tuned for hackathon-friendly
# behaviour: long enough to ride out a typical Anthropic blip, short
# enough that users don't think the pipeline is hung.

_RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({503, 529})


def _is_retryable(exc: BaseException) -> bool:
    """True for transient upstream failures worth retrying."""
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return getattr(exc, "status_code", None) in _RETRYABLE_STATUS_CODES
    return False


# ── Internal stats record ─────────────────────────────────────────────── #


@dataclass
class _CallStats:
    """Per-instance counters refreshed by each Claude call.

    Kept as a dataclass (rather than three loose attributes on ``BaseAgent``)
    so the subclass surface area stays small and additions like
    ``last_input_tokens`` are local edits instead of name-scattered ones.
    """

    last_max_tokens: int | None = None
    last_truncated: bool = False
    truncation_count: int = 0


# ── JSON post-processing helpers ──────────────────────────────────────── #
#
# Lifted to module scope (instead of nested inside ``ask_claude_json``)
# so they can be unit-tested without instantiating an Anthropic client.

_CODEFENCE_RE = re.compile(r"```(?:json)?\s*")


def _strip_codefences(raw: str) -> str:
    """Remove ```json / ``` fences that Claude sometimes wraps JSON in,
    even when explicitly asked for raw JSON."""
    return _CODEFENCE_RE.sub("", raw).strip().rstrip("`").strip()


def _parse_json_or_raise(raw: str) -> Any:
    """Strip code fences then ``json.loads``. Pure function — easy to test
    against fixture strings."""
    return json.loads(_strip_codefences(raw))


_JSON_INSTRUCTION_SUFFIX = (
    "\n\nYou MUST respond with valid JSON only. No markdown, no explanation."
)


# ── Base class ────────────────────────────────────────────────────────── #


class BaseAgent(ABC):
    """Shared scaffolding for every pipeline agent.

    Subclasses use ``self.ask_claude`` or ``self.ask_claude_json``; the
    only shared state worth knowing about is ``had_truncation()``, used
    by synthesis agents to attach a ``safety_flag`` / ``limitation`` to
    the persisted report when at least one upstream Claude call ran into
    the ``max_tokens`` cap.
    """

    def __init__(self, model: str | None = None) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = model or settings.anthropic_model
        self.logger = get_logger(self.__class__.__name__)
        self._stats = _CallStats()

    # ── Public state-introspection API used by synthesis agents ───────

    @property
    def last_truncated(self) -> bool:
        """True if the most recent Claude call hit ``max_tokens``."""
        return self._stats.last_truncated

    @property
    def last_max_tokens(self) -> int | None:
        """The ``max_tokens`` value of the most recent Claude call, or
        ``None`` if no call has been made yet on this instance."""
        return self._stats.last_max_tokens

    def had_truncation(self) -> bool:
        """True if any Claude call on this agent instance hit max_tokens."""
        return self._stats.truncation_count > 0

    @property
    def _truncation_count(self) -> int:
        """Legacy alias for ``self._stats.truncation_count``. Several
        synthesis agents read this attribute directly when building the
        report's ``limitations[]`` entry; the alias keeps the original
        call sites valid after the stats refactor."""
        return self._stats.truncation_count

    # ── Public Claude-calling API ─────────────────────────────────────

    async def ask_claude(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> str:
        """Send a prompt to Claude and return the assistant's text body.

        Retries transient upstream failures (529 overload, 503 unavailable,
        connection / timeout) per :data:`_RETRY_DELAYS_SECONDS` before
        re-raising. Non-transient errors (400, 401, 429, etc.) bubble up
        on the first attempt — retrying those would just waste credits.
        """
        response = await self._call_with_retry(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        self._record_call(max_tokens, getattr(response, "stop_reason", None))
        return response.content[0].text

    async def _call_with_retry(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> Any:
        """Issue the Claude call, retrying transient errors with backoff."""
        attempts = len(_RETRY_DELAYS_SECONDS) + 1
        for attempt_index in range(attempts):
            try:
                return await self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
            except Exception as exc:  # noqa: BLE001 — narrowed by _is_retryable
                is_last_attempt = attempt_index == attempts - 1
                if is_last_attempt or not _is_retryable(exc):
                    raise
                delay = _RETRY_DELAYS_SECONDS[attempt_index]
                self.logger.warning(
                    "Claude call failed with transient error (%s); "
                    "retrying in %.1fs (attempt %d/%d)",
                    type(exc).__name__, delay, attempt_index + 2, attempts,
                )
                await asyncio.sleep(delay)
        # Unreachable — the loop either returns or re-raises.
        raise RuntimeError("retry loop exited without returning or raising")

    async def ask_claude_json(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4096,
    ) -> Any:
        """Ask Claude for JSON, strip any code fences, parse, return.

        Temperature is forced to 0.1 (lower than the default 0.3 of
        ``ask_claude``) so structured outputs are deterministic across
        retries. Subclasses that need a different temperature for JSON
        responses should call ``ask_claude`` and parse manually.
        """
        raw = await self.ask_claude(
            system=system + _JSON_INSTRUCTION_SUFFIX,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=0.1,
        )
        return _parse_json_or_raise(raw)

    # ── Internal bookkeeping ──────────────────────────────────────────

    def _record_call(self, max_tokens: int, stop_reason: str | None) -> None:
        """Update ``_stats`` with the outcome of the call just made. Logs a
        warning when truncation occurs so the operator notices via the
        live progress panel; the synthesis agent later mirrors it into
        the report's ``limitations[]``."""
        truncated = stop_reason == "max_tokens"
        self._stats.last_max_tokens = max_tokens
        self._stats.last_truncated = truncated
        if truncated:
            self._stats.truncation_count += 1
            self.logger.warning(
                "Claude response truncated at max_tokens=%d (model=%s) — "
                "raise the cap or shorten the prompt.",
                max_tokens, self.model,
            )
