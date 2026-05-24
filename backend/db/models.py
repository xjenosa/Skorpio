from datetime import datetime
from sqlalchemy import String, Float, DateTime, JSON, Text, Boolean, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """A Skorpio account. Created lazily on first successful login (Google or
    email-code) — there's no separate "sign up" step."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(254), nullable=True)

    # Google `sub` claim — stable Google user ID. Only set if the account was
    # created (or has logged in) via Google OAuth.
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EmailCode(Base):
    """A one-time 6-digit code emailed to a user during the magic-code login
    flow. Hashed at rest with HMAC-SHA256 of (salt, code) so a DB leak can't
    reveal in-flight codes."""
    __tablename__ = "email_codes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workload_spec: Mapped[str] = mapped_column(String(500), nullable=False)

    # Pipeline state
    stage: Mapped[str] = mapped_column(String(50), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Which pipeline ran this job. Nullable for legacy rows from before the
    # router was wired up; new rows from the router and CSV import always have it.
    pipeline_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # CSV-import provenance. `imported` is True iff this row arrived via
    # /api/jobs/import. `imported_from_email` carries the original exporter's
    # email so the UI can render "Imported from teammate@…" badges.
    imported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    imported_from_email: Mapped[str | None] = mapped_column(String(254), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Final siting plan stored as JSON blob
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Accumulated progress messages so the live log replays when a finished
    # report is reopened. Each entry: {"ts": "HH:MM:SS", "level": "info|ok|warn|error", "text": str}.
    # New runs start at []; legacy rows that pre-date this column are backfilled to [] by init_db().
    progress_log: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
