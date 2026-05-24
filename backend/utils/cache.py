"""
TTL-keyed disk cache for slow upstream API calls (NREL, EIA, arXiv, …).

Used as a politeness layer between Skorpio and upstream APIs: instead of
calling NREL for the same resource map every time the orchestrator boots,
we keep the JSON payload on disk for a configurable window and serve it
straight back on cache hits.

The on-disk layout is intentionally simple — one JSON file per cache
entry, named after the SHA-256 of the lookup key — so the cache can be
inspected, partially wiped, or backed up with ordinary shell tools.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# Schema marker so future format changes can detect (and discard) old
# files instead of crashing.
_CACHE_SCHEMA = 1


@dataclass(frozen=True, slots=True)
class _Entry:
    """In-memory view of a single on-disk cache record."""

    stored_at: datetime
    value: Any

    def is_fresh(self, ttl: timedelta, *, now: datetime | None = None) -> bool:
        ref = now or datetime.now(timezone.utc).replace(tzinfo=None)
        return (ref - self.stored_at) <= ttl

    @classmethod
    def from_dict(cls, blob: dict[str, Any]) -> "_Entry":
        return cls(
            stored_at=datetime.fromisoformat(blob["stored_at"]),
            value=blob["value"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _CACHE_SCHEMA,
            "stored_at": self.stored_at.isoformat(),
            "value": self.value,
        }


def _digest(key: str) -> str:
    """Hash the user-supplied cache key to a filesystem-safe filename."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class DiskCache:
    """Per-namespace TTL cache backed by JSON files in `settings.cache_dir`.

    Namespaces keep different upstreams from stepping on each other and
    make wiping (`rm -rf cache/<namespace>`) targeted instead of nuclear.
    """

    def __init__(self, namespace: str, *, ttl_hours: float = 24) -> None:
        self._dir: Path = settings.cache_dir / namespace
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl: timedelta = timedelta(hours=ttl_hours)

    # ── Path helpers ──────────────────────────────────────────────────

    def _path_for(self, key: str) -> Path:
        return self._dir / f"{_digest(key)}.json"

    # ── Sync API ──────────────────────────────────────────────────────

    def get(self, key: str) -> Any | None:
        path = self._path_for(key)
        if not path.is_file():
            return None
        try:
            entry = _Entry.from_dict(json.loads(path.read_text("utf-8")))
        except (OSError, ValueError, KeyError) as exc:
            logger.warning("Cache miss (unreadable record) key=%r err=%s", key, exc)
            return None
        if not entry.is_fresh(self._ttl):
            # Eagerly clear expired records so the cache dir doesn't bloat.
            path.unlink(missing_ok=True)
            return None
        return entry.value

    def set(self, key: str, value: Any) -> None:
        entry = _Entry(
            stored_at=datetime.now(timezone.utc).replace(tzinfo=None),
            value=value,
        )
        try:
            self._path_for(key).write_text(json.dumps(entry.to_dict()), encoding="utf-8")
        except OSError as exc:
            logger.warning("Cache write failed key=%r err=%s", key, exc)

    # ── Async wrappers ────────────────────────────────────────────────
    #
    # Offload to the default thread pool so a synchronous JSON read
    # doesn't stall the asyncio event loop on slow disks.

    async def aget(self, key: str) -> Any | None:
        return await asyncio.to_thread(self.get, key)

    async def aset(self, key: str, value: Any) -> None:
        await asyncio.to_thread(self.set, key, value)


# Pre-built caches per upstream. TTLs reflect how often the upstream's
# data actually changes — NREL resource maps move on a years scale while
# weather flips every few hours.
grid_cache = DiskCache("grid", ttl_hours=12)
eia_cache = DiskCache("eia", ttl_hours=24)
nrel_cache = DiskCache("nrel", ttl_hours=168)
weather_cache = DiskCache("weather", ttl_hours=3)
arxiv_cache = DiskCache("arxiv", ttl_hours=24)
scoring_cache = DiskCache("scoring", ttl_hours=72)
