"""Router modules — each declares its own ``APIRouter`` and is mounted by
``backend/main.py`` via ``app.include_router``. Splitting endpoints by
responsibility (pipelines, jobs, chat, live telemetry, snowflake, …) keeps
``main.py`` thin and lets reviewers find handlers without scrolling 2000+
lines.
"""
