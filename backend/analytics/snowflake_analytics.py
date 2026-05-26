"""
Snowflake Site Intelligence — analytics & RAG search.

High-level operations exposed by :class:`SnowflakeAnalytics`:

  * ``store_sites(...)``       — batch ``SITE_FEATURES`` insert + ``VECTOR(9)``
                                  feature column.
  * ``store_plan(...)``        — persist a flattened ``SitingPlan`` for RAG
                                  search, with a 768-d Cortex embedding when
                                  the connector supports it.
  * ``similar_sites(...)``     — top-K nearest sites by L2 distance over the
                                  feature vector, with a Python NumPy
                                  fallback when the warehouse vector type
                                  isn't available.
  * ``site_space_pca(...)``    — PCA(3D) projection of all sites in a job,
                                  used by the Site Space Explorer.
  * ``cross_run_analytics()``  — generation-method / region / workload
                                  leaderboards.
  * ``search_plans(...)``      — semantic search (Cortex) with ILIKE
                                  fallback over the persisted plan text.

The class is intentionally a thin orchestration layer — SQL strings live
as module-level constants and DB-cursor lifecycle is centralised in
``_open_cursor`` so individual methods read top-to-bottom without the
usual SQLAlchemy-style ceremony.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

from backend.services.snowflake_client import get_connection, is_available
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# ── Feature columns (kept in one place — schema, vector, PCA all reuse) ─ #

# Order matters: the VECTOR(FLOAT, 9) column stores these in this exact
# sequence so the indices line up for VECTOR_L2_DISTANCE. Re-ordering
# this tuple is a breaking change to the warehouse schema.
FEATURE_COLUMNS: tuple[str, ...] = (
    "capacity_mw",
    "pue",
    "fiber_latency_ms",
    "transmission_headroom_mw",
    "lcoe_usd_mwh",
    "spot_lmp_usd_mwh",
    "carbon_g_co2_kwh",
    "deployment_months",
    "water_l_per_mwh",
)


# ── Small helpers ─────────────────────────────────────────────────────── #


def _to_float(value: Any, default: float = 0.0) -> float:
    """Tolerant float cast. ``None``, garbage strings, etc. fall back to
    ``default`` so a single bad upstream row doesn't break a whole
    batch."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _feature_vector(row: dict) -> list[float]:
    """Project a row dict onto the canonical feature ordering."""
    return [_to_float(row.get(col)) for col in FEATURE_COLUMNS]


def _similarity_from_distance(distance: float) -> float:
    """Convert an L2 distance into a 0..1 similarity score so the
    frontend can render a comparable bar across rows."""
    return round(1.0 / (1.0 + float(distance)), 4)


@contextmanager
def _open_cursor() -> Iterator[Any]:
    """Yield a Snowflake cursor bound to a fresh connection.

    Caller does NOT need to ``cur.close()`` or ``conn.close()`` — both
    happen automatically. Commits are still the caller's responsibility
    because some methods only read and committing would just churn the
    journal."""
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()


# ── SQL string library ────────────────────────────────────────────────── #
#
# Each query lives as a module-level constant rather than inline so:
#   1. The Python below is short and reads like a script.
#   2. Reviewers can diff query changes without scrolling past unrelated
#      Python.
#   3. If we ever migrate to .sql files on disk, this is the seam.

_SQL_INSERT_SITE_FEATURES = """
INSERT INTO SITE_FEATURES (
    job_id, workload, region, site_id, site_name,
    capacity_mw, pue, fiber_latency_ms, transmission_headroom_mw,
    lcoe_usd_mwh, spot_lmp_usd_mwh, carbon_g_co2_kwh,
    deployment_months, water_l_per_mwh,
    generation_method, feature_vector
) SELECT
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s,
    %s, TO_VECTOR(%s, FLOAT, 9)
"""


_SQL_INSERT_PLAN_WITH_EMBEDDING = """
INSERT INTO SITING_PLANS (
    job_id, workload, plan_json,
    plan_text, region_summary, site_rationale,
    plan_embedding
) SELECT %s, %s, PARSE_JSON(%s), %s, %s, %s,
    SNOWFLAKE.CORTEX.EMBED_TEXT_768('e5-base-v2', %s)
"""


_SQL_INSERT_PLAN_NO_EMBEDDING = """
INSERT INTO SITING_PLANS (
    job_id, workload, plan_json,
    plan_text, region_summary, site_rationale
) SELECT %s, %s, PARSE_JSON(%s), %s, %s, %s
"""


_SQL_SIMILAR_SITES_VECTOR = """
WITH query_site AS (
    SELECT feature_vector, site_name
    FROM SITE_FEATURES
    WHERE (site_id = %s OR site_name = %s)
      AND feature_vector IS NOT NULL
    LIMIT 1
)
SELECT
    m.site_id, m.site_name, m.workload, m.region,
    m.capacity_mw, m.lcoe_usd_mwh, m.generation_method,
    VECTOR_L2_DISTANCE(m.feature_vector, q.feature_vector) AS dist
FROM SITE_FEATURES m
CROSS JOIN query_site q
WHERE m.site_name != q.site_name
  AND m.feature_vector IS NOT NULL
ORDER BY dist ASC
LIMIT %s
"""


def _sql_select_all_features() -> str:
    """Composed at call time because the column list comes from the
    canonical ``FEATURE_COLUMNS`` tuple — keeps the SQL in lock-step
    with the warehouse schema."""
    return (
        "SELECT site_id, site_name, workload, region, "
        "capacity_mw, lcoe_usd_mwh, generation_method, "
        + ", ".join(FEATURE_COLUMNS)
        + " FROM SITE_FEATURES"
    )


_SQL_SITE_SPACE_FOR_JOB = """
SELECT
    site_id, site_name, workload, region,
    capacity_mw, pue, fiber_latency_ms,
    transmission_headroom_mw, lcoe_usd_mwh,
    spot_lmp_usd_mwh, carbon_g_co2_kwh,
    deployment_months, water_l_per_mwh, generation_method
FROM SITE_FEATURES
WHERE job_id = %s
"""


_SQL_LEADER_BY_GENERATION = """
SELECT
    generation_method,
    AVG(lcoe_usd_mwh)  AS avg_lcoe,
    AVG(pue)           AS avg_pue,
    COUNT(*)           AS site_count
FROM SITE_FEATURES
GROUP BY generation_method
ORDER BY avg_lcoe ASC
"""


_SQL_LEADER_BY_REGION = """
SELECT
    region,
    AVG(pue)          AS avg_pue,
    AVG(lcoe_usd_mwh) AS avg_lcoe,
    COUNT(*)          AS site_count
FROM SITE_FEATURES
GROUP BY region
ORDER BY avg_lcoe ASC
LIMIT 20
"""


_SQL_LEADER_BY_WORKLOAD = """
SELECT
    workload,
    MIN(lcoe_usd_mwh) AS best_lcoe,
    AVG(pue)          AS avg_pue,
    COUNT(*)          AS site_count
FROM SITE_FEATURES
GROUP BY workload
ORDER BY best_lcoe ASC
LIMIT 20
"""


def _sql_search_plans_semantic(limit: int) -> str:
    return f"""
WITH q AS (
    SELECT SNOWFLAKE.CORTEX.EMBED_TEXT_768('e5-base-v2', %s) AS embedding
)
SELECT
    r.job_id, r.workload, r.created_at,
    VECTOR_COSINE_SIMILARITY(r.plan_embedding, q.embedding) AS score,
    'semantic' AS matched_section,
    SUBSTR(r.plan_text, 1, 300) AS snippet
FROM SITING_PLANS r
CROSS JOIN q
WHERE r.plan_embedding IS NOT NULL
ORDER BY score DESC
LIMIT {int(limit)}
"""


def _sql_search_plans_ilike(limit: int) -> str:
    return f"""
SELECT
    job_id, workload, created_at,
    CASE
        WHEN plan_text       ILIKE %s THEN 'plan_text'
        WHEN region_summary  ILIKE %s THEN 'region_summary'
        WHEN site_rationale  ILIKE %s THEN 'site_rationale'
        ELSE 'plan_text'
    END AS matched_section,
    CASE
        WHEN plan_text ILIKE %s
            THEN SUBSTR(plan_text, 1, 300)
        WHEN region_summary ILIKE %s
            THEN SUBSTR(region_summary, 1, 300)
        ELSE SUBSTR(site_rationale, 1, 300)
    END AS snippet
FROM SITING_PLANS
WHERE
    plan_text       ILIKE %s
 OR region_summary  ILIKE %s
 OR site_rationale  ILIKE %s
ORDER BY created_at DESC
LIMIT {int(limit)}
"""


# ── Row-shape extractors ──────────────────────────────────────────────── #
#
# Each cursor returns rows as tuples in the SELECT's column order; these
# helpers translate them into the dicts the API contract returns.


def _row_to_leader_by_generation(row: Sequence[Any]) -> dict:
    return {
        "method":     row[0],
        "avg_lcoe":   round(_to_float(row[1]), 3),
        "avg_pue":    round(_to_float(row[2]), 3),
        "site_count": int(row[3] or 0),
    }


def _row_to_leader_by_region(row: Sequence[Any]) -> dict:
    return {
        "region":     row[0],
        "avg_pue":    round(_to_float(row[1]), 3),
        "avg_lcoe":   round(_to_float(row[2]), 3),
        "site_count": int(row[3] or 0),
    }


def _row_to_leader_by_workload(row: Sequence[Any]) -> dict:
    return {
        "workload":   row[0],
        "best_lcoe":  round(_to_float(row[1]), 3),
        "avg_pue":    round(_to_float(row[2]), 3),
        "site_count": int(row[3] or 0),
    }


def _row_to_similar_site(row: Sequence[Any]) -> dict:
    return {
        "site_id":           row[0],
        "site_name":         row[1],
        "workload":          row[2],
        "region":            row[3],
        "capacity_mw":       _to_float(row[4]),
        "lcoe_usd_mwh":      _to_float(row[5]),
        "generation_method": row[6],
        "similarity_score":  _similarity_from_distance(row[7]),
    }


# ── Class ─────────────────────────────────────────────────────────────── #


class SnowflakeAnalytics:
    """Holds no state — every method opens its own connection. Kept as a
    class (rather than a flat module) because callers historically use
    ``snowflake_analytics.method()`` and switching the surface would
    cascade. The bottom-of-file singleton makes the import work."""

    # ── Write: per-site features + vector ─────────────────────────────

    def store_sites(
        self,
        job_id: str,
        workload: str,
        scoring_results_per_region: dict[str, list[dict]],
    ) -> None:
        """Batch-insert every scored site into ``SITE_FEATURES``. Each
        row gets a ``TO_VECTOR`` feature vector built from the canonical
        ``FEATURE_COLUMNS`` ordering so the L2-distance similarity query
        works."""
        if not is_available():
            logger.info("Snowflake unavailable, skipping site storage")
            return

        rows = list(self._iter_site_rows(job_id, workload, scoring_results_per_region))
        if not rows:
            logger.info("No sites to store in Snowflake")
            return

        try:
            inserted = 0
            with _open_cursor() as cur:
                for row in rows:
                    cur.execute(_SQL_INSERT_SITE_FEATURES, (
                        row["job_id"], row["workload"], row["region"],
                        row["site_id"], row["site_name"],
                        row["capacity_mw"], row["pue"], row["fiber_latency_ms"],
                        row["transmission_headroom_mw"],
                        row["lcoe_usd_mwh"], row["spot_lmp_usd_mwh"],
                        row["carbon_g_co2_kwh"],
                        row["deployment_months"], row["water_l_per_mwh"],
                        row["generation_method"],
                        json.dumps(_feature_vector(row)),
                    ))
                    inserted += 1
                # cur.connection is the in-flight conn from _open_cursor
                cur.connection.commit()
            logger.info("Stored %d sites in Snowflake for job %s", inserted, job_id)
        except Exception as exc:
            logger.warning("Snowflake site store failed for job %s: %s", job_id, exc)

    @staticmethod
    def _iter_site_rows(
        job_id: str,
        workload: str,
        scoring_results_per_region: dict[str, list[dict]],
    ) -> Iterator[dict]:
        """Flatten the region→rows nested dict into row dicts ready for
        the INSERT. Yields lazily so a large scoring sweep doesn't
        materialise twice in memory."""
        for region_iso, results in scoring_results_per_region.items():
            for idx, r in enumerate(results):
                site = r.get("site") or {}
                profile = site.get("profile") or {}
                yield {
                    "job_id":            job_id,
                    "workload":          workload,
                    "region":            region_iso,
                    "site_id":           site.get("site_id") or f"{job_id[:8]}-{region_iso[:8]}-{idx:04d}",
                    "site_name":         site.get("name", ""),
                    "capacity_mw":       _to_float(profile.get("capacity_mw")),
                    "pue":               _to_float(profile.get("pue")),
                    "fiber_latency_ms":  _to_float(profile.get("fiber_latency_ms")),
                    "transmission_headroom_mw": _to_float(profile.get("transmission_headroom_mw")),
                    "lcoe_usd_mwh":      _to_float(r.get("levelized_cost_usd_mwh")),
                    "spot_lmp_usd_mwh":  _to_float(profile.get("spot_lmp_usd_mwh")),
                    "carbon_g_co2_kwh":  _to_float(r.get("carbon_g_co2_kwh")),
                    "deployment_months": _to_float(profile.get("deployment_months")),
                    "water_l_per_mwh":   _to_float(profile.get("water_l_per_mwh")),
                    "generation_method": site.get("generation_method", "unknown"),
                }

    # ── Write: persist the final SitingPlan ───────────────────────────

    def store_plan(self, job_id: str, workload: str, plan: dict) -> None:
        """Persist a SitingPlan into ``SITING_PLANS``, with a 768-d
        Cortex embedding when the warehouse edition supports it. The
        embedding path is tried first; on any failure the plan is still
        stored (without ``plan_embedding``) so the semantic search
        falls through to ILIKE rather than losing the row entirely."""
        if not is_available():
            logger.info("Snowflake unavailable, skipping plan storage")
            return
        try:
            plan_text, region_summary, site_rationale = self._flatten_plan(plan)
            embed_text = (plan_text or "")[:4000]
            with _open_cursor() as cur:
                self._insert_plan_row(
                    cur, job_id, workload, plan,
                    plan_text, region_summary, site_rationale, embed_text,
                )
                cur.connection.commit()
        except Exception as exc:
            logger.warning("Snowflake plan store failed for job %s: %s", job_id, exc)

    @staticmethod
    def _flatten_plan(plan: dict) -> tuple[str, str, str]:
        """Build the three search-corpus strings that get stored
        alongside the raw plan JSON."""
        executive_summary = plan.get("executive_summary", "")
        methodology_notes = plan.get("methodology_notes", "")
        safety_text = " | ".join(plan.get("safety_flags", []))
        limitations_text = " | ".join(plan.get("limitations", []))

        region_parts: list[str] = []
        rationale_parts: list[str] = []
        for insight in plan.get("region_insights", []):
            region_parts.append(insight.get("transmission_constraints", ""))
            region_parts.append(insight.get("market_outlook", ""))
            rationale_parts.append(insight.get("regulatory_context", ""))
        for candidate in plan.get("top_candidates", [])[:5]:
            rationale_parts.append(candidate.get("explanation", ""))

        plan_text = " ".join(filter(None, [
            executive_summary, methodology_notes, safety_text, limitations_text,
        ]))
        region_summary = " ".join(filter(None, region_parts))
        site_rationale = " ".join(filter(None, rationale_parts))
        return plan_text, region_summary, site_rationale

    @staticmethod
    def _insert_plan_row(
        cur,
        job_id: str,
        workload: str,
        plan: dict,
        plan_text: str,
        region_summary: str,
        site_rationale: str,
        embed_text: str,
    ) -> None:
        """Try the Cortex-embedding INSERT first; on any failure fall
        back to the no-embedding variant. Logs both outcomes so we know
        whether semantic search will work for this job."""
        try:
            cur.execute(_SQL_INSERT_PLAN_WITH_EMBEDDING, (
                job_id, workload, json.dumps(plan),
                plan_text, region_summary, site_rationale,
                embed_text,
            ))
            logger.info("Stored plan with Cortex embedding for job %s", job_id)
            return
        except Exception as cortex_exc:
            logger.warning(
                "Cortex embedding unavailable (%s); storing plan without vector",
                cortex_exc,
            )
        cur.execute(_SQL_INSERT_PLAN_NO_EMBEDDING, (
            job_id, workload, json.dumps(plan),
            plan_text, region_summary, site_rationale,
        ))
        logger.info("Stored plan (no embedding) for job %s", job_id)

    # ── Read: vector similarity ───────────────────────────────────────

    def similar_sites(
        self,
        job_id: str,
        site_id: str,
        top_k: int = 10,
        site_name: str = "",
    ) -> list[dict]:
        """Top-K nearest sites by L2 distance. Falls back to a pure
        Python computation when the warehouse vector type isn't
        available or the query returns nothing (e.g. legacy rows
        without ``feature_vector`` populated)."""
        if not is_available():
            return []
        try:
            with _open_cursor() as cur:
                cur.execute(
                    _SQL_SIMILAR_SITES_VECTOR,
                    (
                        site_id or "__NO_MATCH__",
                        site_name or "__NO_MATCH__",
                        min(top_k, 50),
                    ),
                )
                rows = cur.fetchall()
            if rows:
                return [_row_to_similar_site(r) for r in rows]
            logger.info("No vectorised rows found; falling back to Python L2 similarity")
        except Exception as exc:
            logger.warning(
                "Snowflake vector similarity failed (%s); falling back to Python", exc,
            )
        return self._similar_sites_python(site_id, top_k, site_name)

    def _similar_sites_python(
        self, site_id: str, top_k: int, site_name: str,
    ) -> list[dict]:
        """NumPy fallback for warehouses without ``VECTOR_L2_DISTANCE``."""
        if not is_available():
            return []
        try:
            import numpy as np
            with _open_cursor() as cur:
                cur.execute(_sql_select_all_features())
                cols = [d[0].lower() for d in cur.description]
                all_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            if not all_rows:
                return []

            query_row = self._pick_query_row(all_rows, site_id, site_name)
            if query_row is None:
                return []

            query_vec = np.array(_feature_vector(query_row), dtype=float)
            scored: list[dict] = []
            for r in all_rows:
                if r["site_name"] == query_row["site_name"]:
                    continue
                vec = np.array(_feature_vector(r), dtype=float)
                dist = float(np.linalg.norm(query_vec - vec))
                scored.append({
                    "site_id":           r["site_id"],
                    "site_name":         r["site_name"],
                    "workload":          r["workload"],
                    "region":            r["region"],
                    "capacity_mw":       _to_float(r.get("capacity_mw")),
                    "lcoe_usd_mwh":      _to_float(r.get("lcoe_usd_mwh")),
                    "generation_method": r["generation_method"],
                    "similarity_score":  _similarity_from_distance(dist),
                })
            scored.sort(key=lambda x: x["similarity_score"], reverse=True)
            return scored[:top_k]
        except Exception as exc:
            logger.warning("Python similarity fallback failed: %s", exc)
            return []

    @staticmethod
    def _pick_query_row(
        all_rows: list[dict], site_id: str, site_name: str,
    ) -> dict | None:
        """Locate the query row in the in-memory rowset: site_id first
        (preferred — exact match), site_name as fallback."""
        if site_id:
            for r in all_rows:
                if r.get("site_id") == site_id:
                    return r
        if site_name:
            for r in all_rows:
                if r.get("site_name") == site_name:
                    return r
        return None

    # ── Read: PCA(3D) site space ──────────────────────────────────────

    def site_space_pca(self, job_id: str) -> list[dict]:
        """3D PCA projection of all sites in a job. Returns ``[]`` for
        jobs with fewer than 3 sites (no meaningful projection) or when
        sklearn isn't installed."""
        if not is_available():
            return []
        try:
            with _open_cursor() as cur:
                cur.execute(_SQL_SITE_SPACE_FOR_JOB, (job_id,))
                cols = [d[0].lower() for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            if len(rows) < 3:
                return []
            return self._project_pca(rows, job_id)
        except Exception as exc:
            logger.warning("Snowflake PCA site space failed: %s", exc)
            return []

    @staticmethod
    def _project_pca(rows: list[dict], job_id: str) -> list[dict]:
        """Run the actual PCA. Split out so ``site_space_pca`` reads as
        a thin "fetch then project" pipeline."""
        try:
            import numpy as np
            from sklearn.decomposition import PCA
            from sklearn.preprocessing import StandardScaler
        except ImportError:
            return []

        X = np.array(
            [[_to_float(r.get(c)) for c in FEATURE_COLUMNS] for r in rows],
            dtype=float,
        )
        X_scaled = StandardScaler().fit_transform(X)
        n_components = min(3, X_scaled.shape[1], X_scaled.shape[0])
        coords = PCA(n_components=n_components).fit_transform(X_scaled)
        if coords.shape[1] < 3:
            coords = np.hstack([coords, np.zeros((coords.shape[0], 3 - coords.shape[1]))])

        points = [
            {
                "site_id":           r.get("site_id", ""),
                "x":                 round(float(coords[i, 0]), 4),
                "y":                 round(float(coords[i, 1]), 4),
                "z":                 round(float(coords[i, 2]), 4),
                "site_name":         r.get("site_name", ""),
                "capacity_mw":       _to_float(r.get("capacity_mw")),
                "lcoe_usd_mwh":      _to_float(r.get("lcoe_usd_mwh")),
                "generation_method": r.get("generation_method", ""),
                "region":            r.get("region", ""),
                "workload":          r.get("workload", ""),
            }
            for i, r in enumerate(rows)
        ]
        logger.info(
            "Generated PCA site space from Snowflake: %d points for job %s",
            len(points), job_id,
        )
        return points

    # ── Read: cross-run leaderboards ──────────────────────────────────

    def cross_run_analytics(self) -> dict[str, Any]:
        """Generation-method, region, and workload leaderboards across
        every job in ``SITE_FEATURES``."""
        empty: dict[str, Any] = {
            "generation_methods": [], "regions": [], "workloads": [],
        }
        if not is_available():
            logger.info("Snowflake unavailable, skipping analytics")
            return empty
        try:
            with _open_cursor() as cur:
                cur.execute(_SQL_LEADER_BY_GENERATION)
                gens = [_row_to_leader_by_generation(r) for r in cur.fetchall()]
                cur.execute(_SQL_LEADER_BY_REGION)
                regs = [_row_to_leader_by_region(r) for r in cur.fetchall()]
                cur.execute(_SQL_LEADER_BY_WORKLOAD)
                wls = [_row_to_leader_by_workload(r) for r in cur.fetchall()]
            return {"generation_methods": gens, "regions": regs, "workloads": wls}
        except Exception as exc:
            logger.warning("Snowflake analytics failed: %s", exc)
            return empty

    # ── Read: plan RAG / search ───────────────────────────────────────

    def search_plans(self, query: str, limit: int = 10) -> list[dict]:
        """Semantic search over ``SITING_PLANS`` with ILIKE keyword
        fallback for accounts without Cortex enabled or for plans
        stored before the embedding column existed."""
        if not is_available() or not (query and query.strip()):
            return []
        query = query.strip()
        try:
            with _open_cursor() as cur:
                semantic = self._search_plans_semantic(cur, query, limit)
                if semantic:
                    return semantic
                logger.info("No embedded plans found; falling back to ILIKE")
                return self._search_plans_ilike(cur, query, limit)
        except Exception as exc:
            logger.warning("Snowflake plan search failed: %s", exc)
            return []

    @staticmethod
    def _search_plans_semantic(cur, query: str, limit: int) -> list[dict]:
        try:
            cur.execute(_sql_search_plans_semantic(limit), (query,))
            rows = cur.fetchall()
        except Exception as cortex_exc:
            logger.warning(
                "Cortex semantic search failed (%s); falling back to ILIKE",
                cortex_exc,
            )
            return []
        return [
            {
                "job_id":          r[0],
                "workload":        r[1],
                "created_at":      str(r[2]) if r[2] else None,
                "score":           round(_to_float(r[3]), 4),
                "matched_section": r[4],
                "snippet":         r[5],
            }
            for r in rows
        ]

    @staticmethod
    def _search_plans_ilike(cur, query: str, limit: int) -> list[dict]:
        like = f"%{query}%"
        cur.execute(_sql_search_plans_ilike(limit), (like,) * 8)
        cols = [d[0].lower() for d in cur.description]
        results = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in results:
            if r.get("created_at"):
                r["created_at"] = str(r["created_at"])
        return results


# Module-level singleton consumed by routers + the orchestrator.
snowflake_analytics = SnowflakeAnalytics()
