from __future__ import annotations

from fastapi import APIRouter, Path

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
def get_metrics_summary(instance_id: str = Path(..., description="Instance identifier")) -> MetricsSummary:
    """Return a snapshot summary of key metrics for an instance (stub)."""
    return metrics_service.get_summary(instance_id)


@router.post(
    "/{instance_id}/timeseries",
    response_model=TimeseriesResponse,
    summary="Get metrics timeseries",
    description="Fetch timeseries points for a requested metric (stubbed sample data).",
    operation_id="get_metrics_timeseries",
)
def get_metrics_timeseries(
    payload: TimeseriesRequest,
    instance_id: str = Path(..., description="Instance identifier"),
) -> TimeseriesResponse:
    """Return timeseries points for charting (stub)."""
    return metrics_service.get_timeseries(instance_id, payload)

