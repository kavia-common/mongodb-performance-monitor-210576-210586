from __future__ import annotations

from fastapi import APIRouter, Path, Request

from src.api.schemas.metrics import MetricsSummary, TimeseriesRequest, TimeseriesResponse
from src.api.services import metrics_service

router = APIRouter(prefix="/api/metrics", tags=["Metrics"])


@router.get(
    "/{instance_id}/summary",
    response_model=MetricsSummary,
    summary="Get metrics summary",
    description="Fetch a snapshot summary of key metrics for an instance (stubbed sample data).",
    operation_id="get_metrics_summary",
)
def get_metrics_summary(request: Request, instance_id: str = Path(..., description="Instance identifier")) -> MetricsSummary:
    """Return a snapshot summary of key metrics for an instance."""
    return metrics_service.get_summary(request, instance_id)


@router.post(
    "/{instance_id}/timeseries",
    response_model=TimeseriesResponse,
    summary="Get metrics timeseries",
    description="Fetch timeseries points for a requested metric (stubbed sample data).",
    operation_id="get_metrics_timeseries",
)
def get_metrics_timeseries(
    request: Request,
    payload: TimeseriesRequest,
    instance_id: str = Path(..., description="Instance identifier"),
) -> TimeseriesResponse:
    """Return timeseries points for charting."""
    return metrics_service.get_timeseries(request, instance_id, payload)

