from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from src.api.schemas.insights import AlertsResponse
from src.api.services import insights_service

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


@router.get(
    "",
    response_model=AlertsResponse,
    summary="List alerts",
    description="Return current alerts (stubbed sample data). Optionally filter by instanceId.",
    operation_id="list_alerts",
)
def list_alerts(instance_id: Optional[str] = Query(default=None, alias="instanceId")) -> AlertsResponse:
    """List current alerts (stub)."""
    items = insights_service.list_alerts(instance_id=instance_id)
    return AlertsResponse(items=items, total=len(items))

