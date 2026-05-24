"""Health-check endpoint. Used by docker-compose's healthcheck and any
external uptime monitor."""

from fastapi import APIRouter

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "skorpio-api", "version": "1.0.0"}
