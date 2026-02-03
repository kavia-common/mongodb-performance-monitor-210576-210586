from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from src.api.schemas.insights import RecommendationsResponse
from src.api.services import insights_service

router = APIRouter(prefix="/api/recommendations", tags=["Recommendations"])


@router.get(
    "",
    response_model=RecommendationsResponse,
    summary="List recommendations",
    description="Return tuning recommendations (stubbed sample data). Optionally filter by instanceId.",
    operation_id="list_recommendations",
)
def list_recommendations(
    instance_id: Optional[str] = Query(default=None, alias="instanceId"),
) -> RecommendationsResponse:
    """List recommendations (stub)."""
    items = insights_service.list_recommendations(instance_id=instance_id)
    return RecommendationsResponse(items=items, total=len(items))

