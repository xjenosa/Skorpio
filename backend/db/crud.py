from datetime import datetime
from typing import Iterable, Optional
import uuid as _uuid

from sqlalchemy import and_, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import EmailCode, Job, User


async def create_job(
    db: AsyncSession,
    job_id: str,
    workload_spec: str,
    pipeline_id: Optional[str] = None,
) -> Job:
    now = datetime.utcnow()
    job = Job(
        id=job_id,
        workload_spec=workload_spec,
        stage="queued",
        progress=0.0,
        message="Queued",
        pipeline_id=pipeline_id,
        created_at=now,
        updated_at=now,
        progress_log=[{
            "ts": now.strftime("%H:%M:%S"),
            "level": "info",
            "text": "Queued",
        }],
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_job(db: AsyncSession, job_id: str) -> Optional[Job]:
    result = await db.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()


async def list_jobs(db: AsyncSession) -> list[Job]:
    result = await db.execute(select(Job).order_by(Job.created_at.desc()))
    return list(result.scalars().all())


def _level_for(stage: Optional[str]) -> str:
    if stage == "failed":
        return "error"
    if stage == "completed":
        return "ok"
    return "info"


def _append_log(existing: Optional[list], message: str, level: str) -> list:
    """Append a {ts, level, text} entry; dedupe consecutive identical text.

    Returns a *new* list rather than mutating in place, so SQLAlchemy notices
    the JSON column changed without needing MutableList wiring.
    """
    log = list(existing or [])
    if log and log[-1].get("text") == message:
        return log
    log.append({
        "ts": datetime.utcnow().strftime("%H:%M:%S"),
        "level": level,
        "text": message,
    })
    return log


async def update_progress(
    db: AsyncSession,
    job_id: str,
    message: str,
    progress: float,
    stage: Optional[str] = None,
    started_at: Optional[datetime] = None,
) -> None:
    job = await get_job(db, job_id)
    if job is None:
        return
    job.message = message
    job.progress = float(progress)
    job.updated_at = datetime.utcnow()
    if stage is not None:
        job.stage = stage
    if started_at is not None:
        job.started_at = started_at
    if message:
        job.progress_log = _append_log(job.progress_log, message, _level_for(stage))
    await db.commit()


async def complete_job(
    db: AsyncSession,
    job_id: str,
    result_json: dict,
    message: str = "Plan ready",
) -> None:
    """Persist the completed plan and stamp the job's status line.

    The `message` is what the UI shows in the live header ("Live · {message}")
    and is appended to the progress log. Each orchestrator path passes its own
    pipeline-specific phrasing (e.g. "Resilience plan ready") so reports don't
    all say "Siting plan ready" regardless of pipeline.
    """
    job = await get_job(db, job_id)
    if job is None:
        return
    job.stage = "completed"
    job.progress = 100.0
    job.message = message
    job.result = result_json
    job.updated_at = datetime.utcnow()
    job.progress_log = _append_log(job.progress_log, job.message, "ok")
    await db.commit()


async def set_pipeline_id(db: AsyncSession, job_id: str, pipeline_id: Optional[str]) -> Optional[Job]:
    """Manually re-tag a job's pipeline. Returns the updated job, or None if
    not found. The result blob is intentionally not touched — if the user
    re-tags a completed siting job as winter_peak, the report viewer will
    fail to render it; that's the user's call to make."""
    job = await get_job(db, job_id)
    if job is None:
        return None
    job.pipeline_id = pipeline_id
    job.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(job)
    return job


async def fail_job(db: AsyncSession, job_id: str, error: str) -> None:
    job = await get_job(db, job_id)
    if job is None:
        return
    job.stage = "failed"
    job.error = error
    job.message = f"Pipeline failed: {error}"
    job.updated_at = datetime.utcnow()
    job.progress_log = _append_log(job.progress_log, job.message, "error")
    await db.commit()


async def delete_job(db: AsyncSession, job_id: str) -> bool:
    """Remove a job (and its persisted result blob) from the DB.

    Returns True when a row was deleted, False if no row matched. Callers
    should treat False as "already gone" (idempotent delete is fine for the
    UI's Reports tab — the row's just no longer in the list).
    """
    result = await db.execute(delete(Job).where(Job.id == job_id))
    await db.commit()
    return (result.rowcount or 0) > 0


# ── CSV import / export support ─────────────────────────────────────────── #

async def existing_job_ids(db: AsyncSession, job_ids: Iterable[str]) -> set[str]:
    """Return the subset of `job_ids` that already exist in the DB."""
    ids = list(job_ids)
    if not ids:
        return set()
    result = await db.execute(select(Job.id).where(Job.id.in_(ids)))
    return {row[0] for row in result.all()}


# ── Auth: users ─────────────────────────────────────────────────────────── #

async def get_user_by_id(db: AsyncSession, user_id: str) -> Optional[User]:
    res = await db.execute(select(User).where(User.id == user_id))
    return res.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    res = await db.execute(select(User).where(User.email == email))
    return res.scalar_one_or_none()


async def upsert_user_by_email(db: AsyncSession, *, email: str, name: Optional[str] = None) -> User:
    """Create-or-touch a user row. Used by the email-code login flow — a
    successful code verification implicitly creates the account."""
    now = datetime.utcnow()
    user = await get_user_by_email(db, email)
    if user is None:
        user = User(
            id=str(_uuid.uuid4()),
            email=email,
            name=name,
            google_sub=None,
            created_at=now,
            last_seen_at=now,
        )
        db.add(user)
    else:
        user.last_seen_at = now
        if name and not user.name:
            user.name = name
    await db.commit()
    await db.refresh(user)
    return user


async def upsert_user_by_google(
    db: AsyncSession, *, email: str, name: Optional[str], google_sub: str,
) -> User:
    """Create-or-touch a user row from a Google OAuth callback. If a user
    already exists with the same email but no google_sub, we link them."""
    now = datetime.utcnow()
    res = await db.execute(select(User).where(User.google_sub == google_sub))
    user = res.scalar_one_or_none()
    if user is None:
        user = await get_user_by_email(db, email)
        if user is None:
            user = User(
                id=str(_uuid.uuid4()),
                email=email,
                name=name,
                google_sub=google_sub,
                created_at=now,
                last_seen_at=now,
            )
            db.add(user)
        else:
            user.google_sub = google_sub
            if name and not user.name:
                user.name = name
            user.last_seen_at = now
    else:
        user.last_seen_at = now
        if name and not user.name:
            user.name = name
    await db.commit()
    await db.refresh(user)
    return user


# ── Auth: email codes ───────────────────────────────────────────────────── #

async def create_email_code(
    db: AsyncSession,
    *,
    email: str,
    salt: str,
    code_hash: str,
    expires_at: datetime,
) -> EmailCode:
    """Insert a new pending code. Doesn't touch any older codes for this
    email — verify_code() always pulls the most-recent unconsumed one."""
    rec = EmailCode(
        id=str(_uuid.uuid4()),
        email=email,
        salt=salt,
        code_hash=code_hash,
        created_at=datetime.utcnow(),
        expires_at=expires_at,
        consumed_at=None,
        attempts=0,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return rec


async def get_active_email_code(db: AsyncSession, email: str) -> Optional[EmailCode]:
    """Most-recent unconsumed, unexpired code for this email."""
    now = datetime.utcnow()
    res = await db.execute(
        select(EmailCode)
        .where(
            and_(
                EmailCode.email == email,
                EmailCode.consumed_at.is_(None),
                EmailCode.expires_at > now,
            )
        )
        .order_by(EmailCode.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def bump_email_code_attempts(db: AsyncSession, code_id: str) -> None:
    await db.execute(
        update(EmailCode).where(EmailCode.id == code_id).values(attempts=EmailCode.attempts + 1)
    )
    await db.commit()


async def consume_email_code(db: AsyncSession, code_id: str) -> None:
    await db.execute(
        update(EmailCode).where(EmailCode.id == code_id).values(consumed_at=datetime.utcnow())
    )
    await db.commit()


# ── CSV import (continued) ─────────────────────────────────────────────── #

async def upsert_imported_job(
    db: AsyncSession,
    *,
    job_id: str,
    workload_spec: str,
    stage: str,
    progress: float,
    pipeline_id: Optional[str],
    created_at: datetime,
    result_json: Optional[dict],
    imported_from_email: Optional[str],
    overwrite: bool,
) -> Job:
    """Insert (or overwrite) an imported job row.

    `overwrite` controls whether a pre-existing row with the same id is
    replaced. When False, the caller should have already confirmed no row
    exists; we still defensively check here.
    """
    if overwrite:
        await db.execute(delete(Job).where(Job.id == job_id))
    now = datetime.utcnow()
    job = Job(
        id=job_id,
        workload_spec=workload_spec,
        stage=stage,
        progress=float(progress),
        message="Imported from CSV",
        pipeline_id=pipeline_id,
        imported=True,
        imported_from_email=imported_from_email,
        created_at=created_at,
        updated_at=now,
        result=result_json,
        progress_log=[{
            "ts": now.strftime("%H:%M:%S"),
            "level": "info",
            "text": "Imported from CSV",
        }],
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job
