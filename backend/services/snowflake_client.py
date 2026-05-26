"""
Snowflake Site Intelligence — connection helper + DDL bootstrapper.

Optional layer: when Snowflake credentials are absent, ``is_available()``
returns ``False`` and every caller falls back to a no-op or the local
SQLite/Postgres path. The frontend treats the missing-Snowflake case as
"feature off" and hides the cross-run analytics tiles.

Two warehouse tables:
  * ``SITE_FEATURES``  — per-site scoring properties with a
    ``VECTOR(FLOAT, 9)`` embedding used by the "similar sites" panel.
  * ``SITING_PLANS``   — flattened ``SitingPlan`` text + a 768-d plan
    embedding for keyword / Cortex search.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from backend.config import settings
from backend.utils.logger import get_logger


logger = get_logger(__name__)


# ── Connector availability probe ──────────────────────────────────────── #

# We deliberately import ``snowflake.connector`` lazily — it pulls in a
# large native dependency tree and shouldn't fail the whole app at import
# time when Snowflake isn't configured.
try:
    import snowflake.connector  # type: ignore  # noqa: F401
    _CONNECTOR_PRESENT: bool = True
except ImportError:
    _CONNECTOR_PRESENT = False
    logger.warning(
        "snowflake-connector-python not installed; "
        "Snowflake Site Intelligence Layer disabled."
    )


# ── Environment lookup ────────────────────────────────────────────────── #
#
# Each required key has both an environment variable (the production
# path) and a fall-through to ``backend.config.settings`` (for the
# docker-compose path where .env is loaded via pydantic-settings).
# Names mirror Snowflake's official env-var conventions so this module
# works without modification in third-party deploy templates.

_REQUIRED_KEYS: tuple[str, ...] = (
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_SCHEMA",
)


def _resolve(env_key: str) -> str:
    """Fetch a single connector setting, env first then config."""
    return os.environ.get(env_key) or getattr(settings, env_key.lower(), "")


def _missing_keys() -> list[str]:
    """List of required keys that are still empty."""
    return [k for k in _REQUIRED_KEYS if not _resolve(k)]


def _connection_kwargs() -> dict[str, str] | None:
    """Build the connector kwargs dict, or ``None`` if anything is missing."""
    values = {key: _resolve(key) for key in _REQUIRED_KEYS}
    if any(not v for v in values.values()):
        return None
    return {
        "user":      values["SNOWFLAKE_USER"],
        "password":  values["SNOWFLAKE_PASSWORD"],
        "account":   values["SNOWFLAKE_ACCOUNT"],
        "warehouse": values["SNOWFLAKE_WAREHOUSE"],
        "database":  values["SNOWFLAKE_DATABASE"],
        "schema":    values["SNOWFLAKE_SCHEMA"],
    }


# ── Public availability + status ──────────────────────────────────────── #


def is_available() -> bool:
    """True when the connector library is importable *and* every required
    setting is non-empty. Used by routers / agents to skip Snowflake
    paths gracefully when the deployment hasn't configured it."""
    return _CONNECTOR_PRESENT and _connection_kwargs() is not None


def status() -> dict[str, Any]:
    """Surface readiness diagnostics without leaking credentials. Used by
    the ``/api/snowflake/status`` endpoint and by the debug panel."""
    available = is_available()
    out: dict[str, Any] = {
        "connector_installed": _CONNECTOR_PRESENT,
        "configured": _connection_kwargs() is not None,
        "available": available,
        "missing_keys": _missing_keys(),
        "connection_ok": False,
        "error": None,
    }
    if not available:
        return out
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT CURRENT_ACCOUNT(), CURRENT_REGION(), CURRENT_WAREHOUSE()"
            )
            row = cur.fetchone()
            cur.close()
        out["connection_ok"] = True
        if row is not None:
            out["account"], out["region"], out["warehouse"] = row
    except Exception as exc:
        out["error"] = str(exc)
    return out


# ── Connection context manager ────────────────────────────────────────── #


@contextmanager
def get_connection() -> Iterator[Any]:
    """Yield an open Snowflake connection; close it on exit.

    Caller is expected to manage transaction boundaries (``commit`` /
    ``rollback``) — the context manager only handles socket lifetime.
    """
    if not _CONNECTOR_PRESENT:
        raise RuntimeError("snowflake-connector-python not installed")
    kwargs = _connection_kwargs()
    if kwargs is None:
        raise RuntimeError(
            "Snowflake env vars incomplete. Set: " + ", ".join(_REQUIRED_KEYS)
        )

    # Imported again here (not at module scope) to keep the import cost
    # off the happy-path startup when Snowflake isn't actually used.
    import snowflake.connector  # type: ignore

    conn = snowflake.connector.connect(**kwargs)
    try:
        yield conn
    finally:
        conn.close()


# ── DDL ───────────────────────────────────────────────────────────────── #
#
# Both tables use ``CREATE TABLE IF NOT EXISTS`` so this can be re-run
# on every startup without side effects. The ``ALTER`` lists below add
# columns that were introduced after the initial create — also
# idempotent. New columns should be appended (not inserted into the
# middle of the list) so historical rows stay stable.

_DDL_CREATE_SITE_FEATURES = """
CREATE TABLE IF NOT EXISTS SITE_FEATURES (
    job_id              STRING,
    workload            STRING,
    region              STRING,
    site_id             STRING,
    site_name           STRING,
    capacity_mw         FLOAT,
    pue                 FLOAT,
    fiber_latency_ms    FLOAT,
    transmission_headroom_mw FLOAT,
    lcoe_usd_mwh        FLOAT,
    spot_lmp_usd_mwh    FLOAT,
    carbon_g_co2_kwh    FLOAT,
    deployment_months   FLOAT,
    water_l_per_mwh     FLOAT,
    generation_method   STRING,
    feature_vector      VECTOR(FLOAT, 9),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
"""

_DDL_CREATE_SITING_PLANS = """
CREATE TABLE IF NOT EXISTS SITING_PLANS (
    job_id              STRING,
    workload            STRING,
    plan_json           VARIANT,
    plan_text           STRING,
    region_summary      STRING,
    site_rationale      STRING,
    plan_embedding      VECTOR(FLOAT, 768),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
"""

_DDL_PATCH_SITE_FEATURES: tuple[str, ...] = (
    "ALTER TABLE SITE_FEATURES ADD COLUMN IF NOT EXISTS capacity_mw FLOAT",
    "ALTER TABLE SITE_FEATURES ADD COLUMN IF NOT EXISTS pue FLOAT",
    "ALTER TABLE SITE_FEATURES ADD COLUMN IF NOT EXISTS fiber_latency_ms FLOAT",
    "ALTER TABLE SITE_FEATURES ADD COLUMN IF NOT EXISTS transmission_headroom_mw FLOAT",
    "ALTER TABLE SITE_FEATURES ADD COLUMN IF NOT EXISTS deployment_months FLOAT",
    "ALTER TABLE SITE_FEATURES ADD COLUMN IF NOT EXISTS water_l_per_mwh FLOAT",
    "ALTER TABLE SITE_FEATURES ADD COLUMN IF NOT EXISTS generation_method STRING",
    "ALTER TABLE SITE_FEATURES ADD COLUMN IF NOT EXISTS feature_vector VECTOR(FLOAT, 9)",
)

_DDL_PATCH_SITING_PLANS: tuple[str, ...] = (
    "ALTER TABLE SITING_PLANS ADD COLUMN IF NOT EXISTS plan_embedding VECTOR(FLOAT, 768)",
)


def _run_optional_ddl(cursor, statements: tuple[str, ...]) -> None:
    """Execute a list of idempotent ALTERs, ignoring any that fail (e.g.
    if the column already exists and the warehouse rejects the ALTER)."""
    for stmt in statements:
        try:
            cursor.execute(stmt)
        except Exception:
            # ALTER … ADD COLUMN IF NOT EXISTS is supported on most
            # Snowflake editions, but legacy accounts may still throw.
            # The idempotency requirement matters more than the warning.
            continue


def init_snowflake_tables() -> None:
    """Bootstrap the two Site Intelligence tables on app startup.

    No-op when Snowflake is unavailable — the app still boots and the
    Site Intelligence tiles render their "not configured" state.
    """
    if not is_available():
        logger.info("Snowflake not configured — skipping table initialisation")
        return
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(_DDL_CREATE_SITE_FEATURES)
            cur.execute(_DDL_CREATE_SITING_PLANS)
            _run_optional_ddl(cur, _DDL_PATCH_SITE_FEATURES)
            _run_optional_ddl(cur, _DDL_PATCH_SITING_PLANS)
            cur.close()
        logger.info("Snowflake tables ready (SITE_FEATURES, SITING_PLANS)")
    except Exception as exc:
        logger.warning("Snowflake table init failed: %s", exc)
