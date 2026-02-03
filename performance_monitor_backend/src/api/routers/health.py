from __future__ import annotations

from fastapi import APIRouter

from src.api.schemas.common import HealthResponse, utc_now

router = APIRouter(tags=["Health"])


@router.get(
    "/",
    response_model=HealthResponse,
    summary="Health check",
    description="Basic service liveness check used by deployment and the frontend.",
    operation_id="health_check",
)
def health_check() -> HealthResponse:
    """Return service liveness status."""
    return HealthResponse(status="ok", message="Healthy", timestamp=utc_now())

