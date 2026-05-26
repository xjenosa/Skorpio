"""
Export the 5 demo jobs from the live database to static JSON files that
ship with the frontend. The Vercel deploy reads these files instead of
calling the live backend.

What gets exported
------------------
For each entry in `DEMO_PREFIXES` (8-char prefix → pipeline_id), we find
the matching full-UUID job and write its complete record to:

    frontend/src/demo/fixtures/<prefix>.json

The JSON shape mirrors what `api.getJob()` + `api.getResults()` return so
the frontend demo intercept layer can drop the file in without any
reshape work:

    {
      "prefix": "f01f3b45",
      "pipeline_id": "datacenter-siting",
      "job_list_item": { ... shape of frontend/JobListItem ... },
      "job_status":    { ... shape of frontend/JobStatus    ... },
      "result":        { ... full plan blob ... }
    }

Usage
-----
Run from inside the api container (it has DB credentials baked in via
the compose environment, and the fixtures dir is bind-mounted so the
files appear on the host):

    docker compose exec api python -m backend.scripts.export_demo_fixtures

Re-run any time you re-execute a demo prompt; old fixtures are
overwritten in place.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from backend.db.models import Job
from backend.db.session import AsyncSessionLocal


# Mirrors frontend/src/demo/jobs.ts::DEMO_JOB_PREFIXES. Keep in sync when
# the operator re-runs a demo prompt and rotates a prefix.
DEMO_PREFIXES: list[tuple[str, str]] = [
    ("f01f3b45", "datacenter-siting"),
    ("0801f572", "datacenter-expansion"),
    ("476a2f1a", "winter-peak-stress"),
    ("331e1dbc", "electrification-readiness"),
    ("a06b5cda", "grid-investment-optimizer"),
]


# Inside docker, the repo root is /app; the volume mount in
# docker-compose.yml pins frontend/src/demo/fixtures to the host's copy
# so files written here show up on the developer's filesystem.
OUTPUT_DIR = Path("/app/frontend/src/demo/fixtures")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _to_job_list_item(job: Job) -> dict[str, Any]:
    """Shape that matches frontend/src/api/types.ts::JobListItem."""
    return {
        "job_id": job.id,
        "workload_spec": job.workload_spec,
        "stage": job.stage,
        "progress": float(job.progress),
        "created_at": _iso(job.created_at) or "",
        "pipeline_id": job.pipeline_id,
        "imported": bool(job.imported),
        "imported_from_email": job.imported_from_email,
    }


def _to_job_status(job: Job) -> dict[str, Any]:
    """Shape that matches frontend/src/api/types.ts::JobStatus."""
    return {
        "job_id": job.id,
        "workload_spec": job.workload_spec,
        "stage": job.stage,
        "progress": float(job.progress),
        "message": job.message,
        "started_at": _iso(job.started_at),
        "updated_at": _iso(job.updated_at) or "",
        "error": job.error,
        "has_results": job.result is not None,
        "pipeline_id": job.pipeline_id,
        "paused": False,
        "progress_log": list(job.progress_log or []),
    }


async def _find_job_by_prefix(session, prefix: str) -> Job | None:
    """Find a single Job whose id starts with `prefix`. Errors if more
    than one match (the prefix isn't unique enough — rerun with a longer
    prefix). Returns None if zero matches."""
    result = await session.execute(
        select(Job).where(Job.id.like(f"{prefix}%"))
    )
    rows = list(result.scalars().all())
    if not rows:
        return None
    if len(rows) > 1:
        ids = ", ".join(r.id for r in rows)
        raise SystemExit(
            f"[fatal] prefix {prefix!r} matched {len(rows)} jobs: {ids}\n"
            f"        rotate the prefix in DEMO_PREFIXES to something longer"
        )
    return rows[0]


async def export_one(session, prefix: str, pipeline_id: str) -> dict[str, Any] | None:
    job = await _find_job_by_prefix(session, prefix)
    if job is None:
        print(f"  [skip] {prefix} ({pipeline_id}): no job with this prefix in DB")
        return None
    if job.result is None:
        print(f"  [warn] {prefix} ({pipeline_id}): job exists but has no result blob — "
              f"the run may not have completed. Exporting anyway.")
    if job.pipeline_id and job.pipeline_id != pipeline_id:
        print(f"  [warn] {prefix}: expected pipeline_id={pipeline_id!r}, "
              f"got {job.pipeline_id!r}. Using the DB value.")
        pipeline_id = job.pipeline_id

    payload = {
        "prefix": prefix,
        "pipeline_id": pipeline_id,
        "job_list_item": _to_job_list_item(job),
        "job_status": _to_job_status(job),
        "result": job.result,
    }
    return payload


async def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[..] Exporting {len(DEMO_PREFIXES)} demo jobs to {OUTPUT_DIR}\n")
    async with AsyncSessionLocal() as session:
        for prefix, pipeline_id in DEMO_PREFIXES:
            payload = await export_one(session, prefix, pipeline_id)
            if payload is None:
                continue
            out_path = OUTPUT_DIR / f"{prefix}.json"
            out_path.write_text(
                json.dumps(payload, indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )
            size_kb = out_path.stat().st_size / 1024
            print(f"  [ok] {prefix} ({pipeline_id}) → {out_path.name} ({size_kb:.0f} KB)")

    print("\n[done] Re-run any time after re-executing a demo prompt.")
    print("       Static fixtures are auto-loaded by the frontend when demo mode is on.")


if __name__ == "__main__":
    asyncio.run(main())
