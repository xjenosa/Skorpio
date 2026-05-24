"""
Cross-router runtime state for the Skorpio backend.

The pipeline-starting endpoints (in ``routers/pipelines.py``) need to
register the asyncio.Tasks they spawn so that the cancel/delete endpoints
(in ``routers/jobs.py``) can interrupt them mid-Claude-call. Sticking the
registry in either router would make the other depend on its sibling;
hoisting it into this small module breaks the loop and lets every router
import from a neutral location.

Holds:
  * ``ALLOWED_MODELS``         — model picker allowlist.
  * Pipeline request/response Pydantic schemas (re-used across endpoints).
  * ``running_tasks``          — id → asyncio.Task registry of in-flight runs.
  * ``spawn_pipeline_task``    — register-and-launch helper.
  * ``run_*_task`` wrappers    — translate orchestrator exceptions into DB
                                  state and clean up the registry.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from pydantic import BaseModel, Field

from backend.db import crud
from backend.db.session import AsyncSessionLocal
from backend.orchestrator import orchestrator
from backend.utils.logger import get_logger


logger = get_logger(__name__)


# ── Model allowlist ───────────────────────────────────────────────────── #

# Only the three Claude models we've validated against. Anything else is
# rejected at the endpoint layer so the org isn't billed for arbitrary
# user-supplied model strings.
ALLOWED_MODELS: frozenset[str] = frozenset({
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
})


# ── Request / response schemas ────────────────────────────────────────── #

_MODEL_OVERRIDE_FIELD = Field(
    default=None,
    description="Optional Claude model override. Falls back to ANTHROPIC_MODEL.",
)


class SiteRequest(BaseModel):
    workload: str = Field(
        ...,
        min_length=2,
        max_length=500,
        examples=[
            "Training cluster · Q3 expansion · 42 MW",
            "Inference fleet · West Coast · target 28 MW · < 35ms",
        ],
        description="Natural language workload placement spec",
    )
    max_regions: int = Field(default=3, ge=1, le=5)
    max_sites: int = Field(default=24, ge=8, le=100)
    model: str | None = _MODEL_OVERRIDE_FIELD


class SiteResponse(BaseModel):
    job_id: str
    message: str
    stream_url: str
    status_url: str
    results_url: str


class SnowflakeSeedRequest(BaseModel):
    job_id: str = Field(default="snowflake-test-job")
    workload: str = Field(default="Snowflake Connectivity Test")
    region: str = Field(default="PJM-W")
    n_sites: int = Field(default=6, ge=3, le=30)


class WinterPeakRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=2,
        max_length=500,
        examples=[
            "Will Mississauga's grid hold a -25°C polar vortex with 30% heat pumps?",
            "Stress-test Ottawa's grid against a 5-day cold snap in 2030.",
            "How does the December 2022 storm affect Edmonton with 40% EV adoption?",
        ],
        description="Natural-language winter-peak stress-test query",
    )
    model: str | None = _MODEL_OVERRIDE_FIELD


class ElectrificationRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=2,
        max_length=500,
        examples=[
            "Score Toronto downtown FSAs (M5V, M5A, M4Y) for 2030 heat pump + EV readiness.",
            "Can Mississauga handle 40% heat pump conversion by 2030?",
            "Rate readiness for Ottawa's Glebe under aggressive 2035 net-zero scenario.",
        ],
        description="Natural-language neighborhood electrification readiness query",
    )
    model: str | None = _MODEL_OVERRIDE_FIELD


class InvestmentRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=2,
        max_length=500,
        examples=[
            "Allocate $500M of Hydro One's 5-year capital plan against 2030 ice + heat exposure.",
            "Optimize Toronto Hydro's $200M hardening budget for 2035.",
            "Where should EPCOR spend $300M to protect against wildfire and wind?",
        ],
        description="Natural-language climate-adapted grid investment query",
    )
    model: str | None = _MODEL_OVERRIDE_FIELD


class ExpansionRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=2,
        max_length=500,
        examples=[
            "Plan 60 MW of expansion at eStruxture's Quebec footprint by 2030, AI training mix.",
            "Where should Cologix add 40 MW of inference capacity over the next 3 years?",
            "Add 100 MW for Hyperion in Alberta, brownfield first.",
        ],
        description="Natural-language datacenter expansion planner query",
    )
    model: str | None = _MODEL_OVERRIDE_FIELD


class RouteRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=500)
    model: str | None = Field(
        default=None,
        description="Optional Claude model override. Defaults to Haiku for cost reasons.",
    )


class PipelineTagRequest(BaseModel):
    pipeline_id: str = Field(
        ...,
        description="One of the supported PipelineId values. The result blob is "
                    "NOT re-rendered, so re-tagging a completed job to a different "
                    "pipeline may make its report viewer error.",
    )


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str | None = None


# ── Pipeline ID allowlist ─────────────────────────────────────────────── #

# Mirror of PipelineId in frontend/src/pipelines.ts. Used by the retag
# endpoint to reject unknown values.
ALLOWED_PIPELINE_IDS: frozenset[str] = frozenset({
    "datacenter-siting",
    "datacenter-expansion",
    "winter-peak-stress",
    "electrification-readiness",
    "grid-investment-optimizer",
})


# ── In-flight task registry ───────────────────────────────────────────── #

# job_id → asyncio.Task running orchestrator.run_*. ``cancel_job`` and
# ``delete_job`` consult this map to call task.cancel(), which raises
# CancelledError at the current await and interrupts in-flight Claude
# calls — cutting cancellation latency from "wait out the stage" to ~1s.
running_tasks: dict[str, asyncio.Task] = {}


async def _persist_cancelled(job_id: str) -> None:
    """Write the "Cancelled by user" failure row after a CancelledError.

    The orchestrator's own try/except chain doesn't run when cancellation
    fires mid-await, so we open a fresh session here and stamp the job
    directly. Wrapped in a broad except because the DB may itself be in
    a torn-down state (e.g. during app shutdown) — we'd rather log than
    crash the cleanup path.
    """
    try:
        async with AsyncSessionLocal() as db:
            await crud.fail_job(db, job_id, "Cancelled by user")
    except Exception as exc:
        logger.warning("Could not stamp cancellation for job %s: %s", job_id, exc)


def _make_wrapper(
    label: str,
    runner: Callable[..., Coroutine[Any, Any, Any]],
) -> Callable[..., Coroutine[Any, Any, None]]:
    """Build a per-pipeline background-task coroutine.

    Each wrapper:
      1. Awaits the underlying orchestrator coroutine.
      2. Translates CancelledError into a "Cancelled by user" DB row.
      3. Logs and swallows other exceptions so the background task dies
         cleanly without crashing uvicorn.
      4. Pops the job out of ``running_tasks`` in finally so the registry
         doesn't leak.
    """

    async def wrapper(job_id: str, *args: Any, **kwargs: Any) -> None:
        try:
            await runner(job_id, *args, **kwargs)
        except asyncio.CancelledError:
            logger.info("%s job %s cancelled by user", label, job_id)
            await _persist_cancelled(job_id)
            raise
        except Exception as exc:
            logger.error("%s background error for job %s: %s", label, job_id, exc)
        finally:
            running_tasks.pop(job_id, None)

    wrapper.__name__ = f"_run_{label.lower().replace(' ', '_')}_task"
    return wrapper


# Per-pipeline background wrappers. Each one awaits the corresponding
# orchestrator coroutine; the wrapper provides cancel/error handling
# uniformly so individual pipelines don't reimplement it.
run_siting_task = _make_wrapper("Siting", orchestrator.run_pipeline)
run_winter_peak_task = _make_wrapper("Winter peak", orchestrator.run_winter_peak)
run_electrification_task = _make_wrapper("Electrification", orchestrator.run_electrification)
run_investment_task = _make_wrapper("Investment", orchestrator.run_investment)
run_expansion_task = _make_wrapper("Expansion", orchestrator.run_expansion)


def spawn_pipeline_task(job_id: str, coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """Register a pipeline coroutine as a tracked asyncio.Task.

    Replaces FastAPI's BackgroundTasks for pipeline runs — BackgroundTasks
    don't expose the Task object, so cancellation isn't possible. The
    asyncio.Task is stored in ``running_tasks`` until the wrapper's
    finally clause pops it.
    """
    task = asyncio.create_task(coro)
    running_tasks[job_id] = task
    return task
