from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request

from src.api.schemas.common import ErrorResponse
from src.api.schemas.insights import RecommendationOut, RecommendationsResponse, RecommendationStatusUpdate
from src.api.services import recommendations_service

router = APIRouter(prefix="/api/recommendations", tags=["Recommendations"])


@router.get(
    "",
    response_model=RecommendationsResponse,
    summary="List recommendations",
    description=(
        "Return latest persisted tuning recommendations. "
        "Optionally filter by instanceId. Sorted by created_at desc."
    ),
    operation_id="list_recommendations",
)
def list_recommendations(
    request: Request,
    instance_id: Optional[str] = Query(default=None, alias="instanceId"),
) -> RecommendationsResponse:
    """List latest recommendations from storage."""
    items = recommendations_service.list_recommendations(request, instance_id=instance_id)
    return RecommendationsResponse(items=items, total=len(items))


@router.post(
    "/refresh",
    response_model=RecommendationsResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Refresh recommendations",
    description=(
        "Trigger recomputation of recommendations for a given instanceId, "
        "persist the newly generated set, and return it."
    ),
    operation_id="refresh_recommendations",
)
def refresh_recommendations(
    request: Request,
    instance_id: str = Query(..., alias="instanceId", description="Instance identifier to recompute recommendations for."),
) -> RecommendationsResponse:
    """Recompute recommendations for an instance and persist them."""
    created = recommendations_service.refresh_recommendations(request, instance_id=instance_id)
    if not created:
        # Either instance not found or no heuristics produced anything. Treat missing instance as 404.
        # To avoid false 404 when heuristics yield empty, we check existence by attempting a list with limit=1.
        existing = recommendations_service.list_recommendations(request, instance_id=instance_id, limit=1)
        if not existing:
            raise HTTPException(status_code=404, detail="instance not found or no data available")
    return RecommendationsResponse(items=created, total=len(created))


@router.patch(
    "/{rec_id}",
    response_model=RecommendationOut,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Update recommendation status",
    description="Update status (open|applied|dismissed) and optional notes for a recommendation.",
    operation_id="update_recommendation_status",
)
def patch_recommendation(
    request: Request,
    payload: RecommendationStatusUpdate,
    rec_id: str = Path(..., description="Recommendation id (Mongo ObjectId string)."),
) -> RecommendationOut:
    """Update recommendation status and optional notes."""
    updated = recommendations_service.update_recommendation_status(request, rec_id=rec_id, payload=payload)
    if updated is None:
        # Ambiguous: could be invalid ObjectId or not found; return 404 for not found and 400 for invalid.
        # We infer invalid if it isn't a 24-char hex string.
        if len(rec_id) != 24:
            raise HTTPException(status_code=400, detail="invalid recommendation id")
        raise HTTPException(status_code=404, detail="recommendation not found")
    return updated
