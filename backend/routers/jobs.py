"""
Job lifecycle endpoints — get, pause, resume, cancel, delete, retag,
fetch results, stream progress, list, JSON export bundle, JSON
multi-file report import.

Cancellation interacts with the in-flight task registry from
``backend/runtime.py``: both ``/cancel`` and ``DELETE`` call
``task.cancel()`` on the running asyncio.Task, raising CancelledError at
the current await — which on a streaming Claude call drops the HTTP
connection within ~1s. The orchestrator's cooperative ``cancel()`` flag
is also set as a fallback for any task that's somehow not in the registry
(e.g. spawned before the registry existed).
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import crud
from backend.db.session import get_db
from backend.orchestrator import orchestrator
from backend.runtime import ALLOWED_PIPELINE_IDS, PipelineTagRequest, running_tasks
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["jobs"])


# ── Individual job — fetch, pause, resume, cancel, retag, delete ─────── #


@router.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get current status of a pipeline job."""
    job = await crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {
        "job_id": job_id,
        "workload_spec": job.workload_spec,
        "stage": job.stage,
        "progress": job.progress,
        "message": job.message,
        "started_at": job.started_at,
        "updated_at": job.updated_at,
        "error": job.error,
        "has_results": job.result is not None,
        "pipeline_id": job.pipeline_id,
        "paused": orchestrator.is_paused(job_id),
        "progress_log": job.progress_log or [],
    }


@router.post("/api/jobs/{job_id}/pause", status_code=202)
async def pause_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Mark a job as paused. The orchestrator halts at the next stage boundary."""
    job = await crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.stage in ("completed", "failed"):
        raise HTTPException(status_code=409, detail=f"Cannot pause a {job.stage} job")
    orchestrator.pause(job_id)
    return {"job_id": job_id, "paused": True}


@router.post("/api/jobs/{job_id}/resume", status_code=202)
async def resume_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Resume a paused job. No-op if the job wasn't paused."""
    job = await crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    orchestrator.resume(job_id)
    return {"job_id": job_id, "paused": False}


@router.post("/api/jobs/{job_id}/cancel", status_code=202)
async def cancel_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel a running job. ``task.cancel()`` raises ``CancelledError`` at
    the next ``await`` — usually within ~1s, even mid-Claude-call. The
    cooperative orchestrator flag is set too as a fallback for any task
    that's somehow not in the registry. Idempotent: 409 on terminal jobs."""
    job = await crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.stage in ("completed", "failed"):
        raise HTTPException(status_code=409, detail=f"Cannot cancel a {job.stage} job")
    orchestrator.cancel(job_id)
    task = running_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
    return {"job_id": job_id, "cancelled": True}


@router.delete("/api/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a job and its persisted result.

    Cancels the running asyncio.Task before the DB delete (otherwise a
    paused-then-deleted job silently resumes and burns the remaining
    Claude calls — ``crud.update_progress``, ``complete_job``, and
    ``fail_job`` all no-op once the row is gone, so the waste went
    undetected for as long as the asyncio task lived).
    """
    orchestrator.cancel(job_id)
    task = running_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
    await crud.delete_job(db, job_id)
    return None


@router.patch("/api/jobs/{job_id}/pipeline")
async def retag_job_pipeline(
    job_id: str,
    request: PipelineTagRequest,
    db: AsyncSession = Depends(get_db),
):
    """Manually re-tag the pipeline a job is associated with. Used when the
    auto-router picked wrong, or to migrate older runs into the right tab."""
    if request.pipeline_id not in ALLOWED_PIPELINE_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported pipeline_id '{request.pipeline_id}'. "
                   f"Allowed: {sorted(ALLOWED_PIPELINE_IDS)}",
        )
    job = await crud.set_pipeline_id(db, job_id, request.pipeline_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    logger.info("Re-tagged job %s → pipeline_id=%s", job_id, request.pipeline_id)
    return {"job_id": job_id, "pipeline_id": job.pipeline_id}


# ── Results + live stream ─────────────────────────────────────────────── #


@router.get("/api/results/{job_id}")
async def get_results(job_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve the final plan for a completed job."""
    job = await crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.stage == "failed":
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {job.error}")
    if job.stage != "completed" or job.result is None:
        return JSONResponse(
            status_code=202,
            content={
                "message": "Pipeline still running",
                "stage": job.stage,
                "progress": job.progress,
            },
        )
    return job.result


@router.get("/api/stream/{job_id}")
async def stream_progress(job_id: str, db: AsyncSession = Depends(get_db)):
    """SSE stream for real-time pipeline progress."""
    job = await crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return StreamingResponse(
        orchestrator.stream_progress(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Listing ───────────────────────────────────────────────────────────── #


@router.get("/api/jobs")
async def list_jobs(db: AsyncSession = Depends(get_db)):
    """List all pipeline jobs (newest first)."""
    jobs = await crud.list_jobs(db)
    return [
        {
            "job_id": j.id,
            "workload_spec": j.workload_spec,
            "stage": j.stage,
            "progress": j.progress,
            "created_at": j.created_at,
            "pipeline_id": j.pipeline_id,
            "imported": j.imported,
            "imported_from_email": j.imported_from_email,
        }
        for j in jobs
    ]


# ── JSON export bundle / multi-file JSON import ───────────────────────── #
#
# Export shape — one file per report, written as:
#
#   { "skorpio_export_version": 1,
#     "exported_at": <iso-utc>,
#     "exported_by": <email or null>,
#     "job":    { job_id, workload_spec, pipeline_id, stage, progress, created_at },
#     "result": <full plan blob or null> }
#
# When the user exports 1 report → single .json download.
# When the user exports N reports → .zip containing N .json files, one
# per report, named skorpio-report-{job_id_short}.json.
#
# Import accepts one or more .json files in the same multipart request,
# each parsed independently. Conflict resolution mirrors the previous
# CSV flow: 409 on first call lists the conflicting job_ids; the client
# re-POSTs with a `strategies` JSON map to resolve.

_EXPORT_VERSION = 1


def _serialize_report(job, *, exported_by: str | None) -> dict:
    """Pack one DB job row into the export envelope."""
    return {
        "skorpio_export_version": _EXPORT_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "exported_by": exported_by or None,
        "job": {
            "job_id": job.id,
            "workload_spec": job.workload_spec,
            "pipeline_id": job.pipeline_id or None,
            "stage": job.stage,
            "progress": job.progress,
            "created_at": job.created_at.isoformat() if job.created_at else None,
        },
        "result": job.result,
    }


@router.post("/api/jobs/export-bundle")
async def export_jobs_bundle(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Export one or more reports as JSON.

    Body shape:
        { "job_ids": ["abc", "def", ...],   # required, non-empty
          "from_email": "user@example.com"  # optional, written into each envelope }

    Returns ``application/json`` when ``len(job_ids) == 1`` and
    ``application/zip`` when > 1. 404 if any requested id is missing.
    """
    job_ids = payload.get("job_ids") or []
    if not isinstance(job_ids, list) or not job_ids:
        raise HTTPException(status_code=400, detail="job_ids must be a non-empty array")
    from_email = payload.get("from_email")

    all_jobs = await crud.list_jobs(db)
    by_id = {j.id: j for j in all_jobs}
    missing = [jid for jid in job_ids if jid not in by_id]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown job_ids: {', '.join(missing)}",
        )

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")

    # Single report — return the JSON file directly.
    if len(job_ids) == 1:
        envelope = _serialize_report(by_id[job_ids[0]], exported_by=from_email)
        filename = f"skorpio-report-{job_ids[0][:8]}.json"
        return Response(
            content=json.dumps(envelope, default=str, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # Multiple reports — zip one .json per report.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for jid in job_ids:
            envelope = _serialize_report(by_id[jid], exported_by=from_email)
            zf.writestr(
                f"skorpio-report-{jid[:8]}.json",
                json.dumps(envelope, default=str, indent=2),
            )
    filename = f"skorpio-reports-{ts}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _parse_envelope(raw_bytes: bytes, source_name: str) -> dict:
    """Parse + minimally validate one report JSON envelope.

    We accept either a full envelope (with ``job`` / ``result`` keys) or a
    bare envelope where the job fields live at the top level — older
    backups, hand-edited files, etc. Any structural issue raises
    HTTPException 400 so the entire batch fails fast with a clear message
    rather than partially importing garbage.
    """
    try:
        text = raw_bytes.decode("utf-8-sig")
        parsed = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"{source_name}: not valid UTF-8 JSON ({e})",
        )
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=400,
            detail=f"{source_name}: top-level JSON must be an object",
        )

    # Normalise into a single shape: { job: {...}, result: ..., exported_by }
    job_section = parsed.get("job") if isinstance(parsed.get("job"), dict) else parsed
    result_section = parsed.get("result") if "result" in parsed else None
    exported_by = parsed.get("exported_by") or None

    if not job_section.get("job_id"):
        raise HTTPException(
            status_code=400,
            detail=f"{source_name}: missing required 'job_id'",
        )
    return {"job": job_section, "result": result_section, "exported_by": exported_by}


@router.post("/api/jobs/import-reports")
async def import_reports(
    files: list[UploadFile] = File(..., description="One or more report .json files."),
    strategies: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Import one or more report JSON files.

    Multipart form: any number of ``files[]`` entries, each a single
    report envelope. ``strategies`` is an optional JSON map
    ``{job_id: "skip"|"overwrite"|"new"}`` used to resolve collisions on
    re-POST after a 409. The 409 response has the same conflict shape as
    the legacy CSV import path so the existing resolution dialog still
    works.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    # Parse every envelope up-front. A single malformed file fails the
    # entire batch — partial imports across N files would leave the user
    # uncertain about what landed.
    #
    # Each uploaded file can be either a single .json envelope OR a .zip
    # containing N .json envelopes (matches the export shape — when the
    # user exports N>1 reports they get a .zip; this lets them hand that
    # same .zip straight to a coworker without unpacking it first).
    envelopes: list[dict] = []
    for f in files:
        raw = await f.read()
        source = f.filename or "<unnamed>"
        if zipfile.is_zipfile(io.BytesIO(raw)):
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for member in zf.namelist():
                    # Skip directories, dotfiles, and anything that isn't
                    # a .json — keeps stray macOS resource forks
                    # (__MACOSX/, .DS_Store) and incidental README.txt
                    # files from blowing up the parse.
                    if not member.lower().endswith(".json"):
                        continue
                    if member.startswith("__MACOSX/"):
                        continue
                    inner_bytes = zf.read(member)
                    envelopes.append(
                        _parse_envelope(inner_bytes, source_name=f"{source}/{member}")
                    )
        else:
            envelopes.append(_parse_envelope(raw, source_name=source))

    if not envelopes:
        raise HTTPException(
            status_code=400,
            detail="No JSON report envelopes found in the uploaded file(s)",
        )

    strats: dict[str, str] = {}
    if strategies:
        try:
            parsed_strats = json.loads(strategies)
            if not isinstance(parsed_strats, dict):
                raise ValueError("strategies must be an object")
            strats = {str(k): str(v) for k, v in parsed_strats.items()}
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid strategies: {e}")

    incoming_ids = [env["job"].get("job_id") for env in envelopes if env["job"].get("job_id")]
    existing = await crud.existing_job_ids(db, incoming_ids)

    unresolved = [
        {"job_id": env["job"]["job_id"], "workload_spec": env["job"].get("workload_spec", "")}
        for env in envelopes
        if env["job"].get("job_id") in existing
        and env["job"]["job_id"] not in strats
    ]
    if unresolved:
        logger.info(
            "Import: returning 409 with %d unresolved conflict(s) (envelopes=%d, existing=%d)",
            len(unresolved), len(envelopes), len(existing),
        )
        return JSONResponse(
            status_code=409,
            content={"detail": "Conflicts require resolution", "conflicts": unresolved},
        )

    counts = {"imported": 0, "overwritten": 0, "skipped": 0, "renamed": 0}
    for env in envelopes:
        job_data = env["job"]
        jid = job_data.get("job_id")
        if not jid:
            continue

        strategy = strats.get(jid)
        if jid in existing:
            if strategy == "skip":
                counts["skipped"] += 1
                continue
            elif strategy == "overwrite":
                pass
            elif strategy == "new":
                jid = str(uuid.uuid4())
                counts["renamed"] += 1
            else:
                counts["skipped"] += 1
                continue

        try:
            created_at = datetime.fromisoformat(job_data["created_at"])
        except (KeyError, ValueError, TypeError):
            created_at = datetime.utcnow()

        try:
            progress = float(job_data.get("progress") or 0.0)
        except (ValueError, TypeError):
            progress = 0.0

        await crud.upsert_imported_job(
            db,
            job_id=jid,
            workload_spec=job_data.get("workload_spec") or "(imported)",
            stage=job_data.get("stage") or "queued",
            progress=progress,
            pipeline_id=job_data.get("pipeline_id") or None,
            created_at=created_at,
            result_json=env["result"],
            imported_from_email=env.get("exported_by") or None,
            overwrite=strategy == "overwrite",
        )
        if strategy == "overwrite":
            counts["overwritten"] += 1
        elif strategy != "new":
            counts["imported"] += 1

    return counts
