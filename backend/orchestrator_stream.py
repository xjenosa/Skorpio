"""
SSE progress streamer for pipeline runs.

The frontend's ``EventSource`` connects to ``/api/stream/{job_id}`` and
expects ``data: {...}\\n\\n`` lines. This module owns the polling loop
that walks the ``jobs`` table and emits one event per poll until the
job hits a terminal stage or the timeout fires.

Kept out of ``orchestrator.py`` so the SSE plumbing isn't tangled with
the per-pipeline ``run_*`` methods — the streamer is a read-only
consumer of the DB row that the orchestrator is writing.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Callable

from backend.db import crud
from backend.db.session import AsyncSessionLocal


# Poll cadence and absolute upper-bound — at 0.5s × 1800 polls, the
# stream stays open for at most 15 minutes per connection. Pipelines
# that run longer than that will keep producing DB rows; the frontend
# just re-opens the SSE channel after the timeout.
_POLL_INTERVAL_SECONDS: float = 0.5
_MAX_POLL_ITERATIONS: int = 1800


def _build_payload(job, paused: bool) -> dict:
    """Shape one SSE payload from a job row."""
    payload: dict = {
        "job_id":   job.id,
        "stage":    job.stage,
        "progress": job.progress,
        "message":  job.message,
        "paused":   paused,
    }
    if job.error:
        payload["error"] = job.error
    return payload


def _format_event(data: dict) -> str:
    """Encode a payload dict as an SSE ``data: ...`` line."""
    return f"data: {json.dumps(data)}\n\n"


async def stream_progress(
    job_id: str,
    paused_lookup: Callable[[str], bool],
) -> AsyncIterator[str]:
    """Yield SSE lines for ``job_id`` until completion or timeout.

    ``paused_lookup`` is injected (rather than imported) so this module
    doesn't import from ``orchestrator`` — the orchestrator imports
    *this* module and supplies its own ``is_paused`` predicate. The
    one-way import keeps cycles out.
    """
    async with AsyncSessionLocal() as db:
        for _ in range(_MAX_POLL_ITERATIONS):
            job = await crud.get_job(db, job_id)
            if job is None:
                yield _format_event({"error": "Job not found"})
                return

            yield _format_event(_build_payload(job, paused_lookup(job_id)))

            if job.stage in ("completed", "failed"):
                return

            # Expire the cached row so the next ``get_job`` re-reads it
            # from the DB — without this, the SSE stream would hold a
            # stale ORM identity-map copy and never see progress
            # updates written by the orchestrator's session.
            db.expire(job)
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    yield _format_event({"error": "Timeout waiting for pipeline"})
