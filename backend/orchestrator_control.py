"""
In-memory control plane for the pipeline orchestrator.

Houses the pause/resume and cancel flags consulted between stages, plus
the ``checkpoint`` coroutine that raises :class:`JobCancelledError` when
the user has clicked Stop. Kept in a sibling module (instead of inside
``orchestrator.py``) so the pause/cancel mechanics aren't intermingled
with the per-pipeline ``run_*`` methods — easier to reason about, easier
to swap if we ever move pause/cancel into a persistent store.

State is process-local: pause/resume/cancel never survive a backend
restart. That's deliberate — pipeline runs themselves don't either, so
the cleanest "what should happen on crash" answer is "the run is gone
too". If you want durable cancellation, add a row to the jobs table and
read it here.
"""

from __future__ import annotations

import asyncio
from typing import Final

from backend.db import crud
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class JobCancelledError(RuntimeError):
    """Raised by ``JobControl.checkpoint`` when the user clicks Stop on a
    running job. The per-pipeline ``except`` handler in
    ``backend/orchestrator.py`` catches it and marks the job failed with
    message ``"Cancelled by user"``."""


_PAUSE_POLL_SECONDS: Final[float] = 0.5


class JobControl:
    """Tracks paused / cancelled job ids and gates the orchestrator's
    stage transitions on those signals.

    Two ad-hoc sets keyed by job_id:
      * ``_paused``    — caller asked for pause; resume drops the id.
      * ``_cancelled`` — caller asked for cancel; the next ``checkpoint``
        consults this and raises.
    """

    def __init__(self) -> None:
        self._paused: set[str] = set()
        self._cancelled: set[str] = set()

    # ── Pause / resume ────────────────────────────────────────────────

    def request_pause(self, job_id: str) -> None:
        self._paused.add(job_id)

    def release_pause(self, job_id: str) -> None:
        self._paused.discard(job_id)

    def is_paused(self, job_id: str) -> bool:
        return job_id in self._paused

    # ── Cancellation ──────────────────────────────────────────────────

    def request_cancel(self, job_id: str) -> None:
        """Mark a job for cancellation. The next ``checkpoint`` call will
        raise ``JobCancelledError``. Also clears any pause flag so the
        wait loop wakes up immediately."""
        self._cancelled.add(job_id)
        self._paused.discard(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        return job_id in self._cancelled

    def release_cancel(self, job_id: str) -> None:
        """Drop the cancel flag — typically called from ``delete_job``
        cleanup so the set doesn't accumulate ids across restarts."""
        self._cancelled.discard(job_id)

    # ── Stage-boundary checkpoint ─────────────────────────────────────

    async def checkpoint(self, job_id: str, db, last_pct: float = 0.0) -> None:
        """Called at every stage boundary inside a pipeline run.

        Behaviour matrix:
          * cancelled (at any point)                  → raise JobCancelledError
          * paused only                               → write a "Paused" progress
                                                        row, sleep until released,
                                                        then write a "Resumed" row
          * paused → cancelled while waiting          → raise JobCancelledError
          * neither flag set                          → return immediately
        """
        if self.is_cancelled(job_id):
            raise JobCancelledError("Cancelled by user")
        if not self.is_paused(job_id):
            return

        await self._mark_paused(job_id, db, last_pct)
        await self._block_until_released(job_id)
        if self.is_cancelled(job_id):
            raise JobCancelledError("Cancelled by user")
        await self._mark_resumed(job_id, db, last_pct)

    # ── Pause-loop helpers ────────────────────────────────────────────

    @staticmethod
    async def _mark_paused(job_id: str, db, last_pct: float) -> None:
        await crud.update_progress(
            db, job_id,
            message="Paused. Click Resume to continue.",
            progress=float(last_pct),
        )
        logger.info("[%s] paused; waiting for resume", job_id[:8])

    async def _block_until_released(self, job_id: str) -> None:
        """Sleep loop that also watches for cancellation — without this
        a paused job stays asleep forever if the user only clicks Stop
        (never Resume)."""
        while self.is_paused(job_id):
            if self.is_cancelled(job_id):
                return  # caller re-checks and raises
            await asyncio.sleep(_PAUSE_POLL_SECONDS)

    @staticmethod
    async def _mark_resumed(job_id: str, db, last_pct: float) -> None:
        await crud.update_progress(
            db, job_id,
            message="Resumed",
            progress=float(last_pct),
        )
        logger.info("[%s] resumed", job_id[:8])
