from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request, status

from src.api.schemas.alerts import (
    AlertEventListResponse,
    AlertEventsQuery,
    AlertRuleCreate,
    AlertRuleListResponse,
    AlertRuleOut,
    AlertRuleUpdate,
)
from src.api.schemas.common import ErrorResponse
from src.api.services import alerts_service

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


@router.get(
    "/rules",
    response_model=AlertRuleListResponse,
    summary="List alert rules",
    description="List alert rules. Optionally filter to rules applicable to a specific instanceId.",
    operation_id="list_alert_rules",
)
def list_rules(
    request: Request,
    instance_id: Optional[str] = Query(default=None, alias="instanceId", description="Optional instance filter."),
) -> AlertRuleListResponse:
    """List alert rules."""
    items = alerts_service.list_rules(request, instance_id=instance_id)
    return AlertRuleListResponse(items=items, total=len(items))


@router.post(
    "/rules",
    response_model=AlertRuleOut,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Create alert rule",
    description="Create a new alert rule definition.",
    operation_id="create_alert_rule",
)
def create_rule(request: Request, payload: AlertRuleCreate) -> AlertRuleOut:
    """Create an alert rule."""
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="name must not be empty")
    return alerts_service.create_rule(request, payload)


@router.get(
    "/rules/{rule_id}",
    response_model=AlertRuleOut,
    responses={404: {"model": ErrorResponse}},
    summary="Get alert rule",
    description="Fetch a single alert rule by ruleId.",
    operation_id="get_alert_rule",
)
def get_rule(
    request: Request,
    rule_id: str = Path(..., description="Rule id (Mongo ObjectId string)."),
) -> AlertRuleOut:
    """Get a rule by id."""
    rule = alerts_service.get_rule(request, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="rule not found")
    return rule


@router.put(
    "/rules/{rule_id}",
    response_model=AlertRuleOut,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Replace alert rule",
    description="Replace an existing alert rule by ruleId (full update).",
    operation_id="put_alert_rule",
)
def put_rule(
    request: Request,
    payload: AlertRuleCreate,
    rule_id: str = Path(..., description="Rule id (Mongo ObjectId string)."),
) -> AlertRuleOut:
    """Replace an alert rule."""
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="name must not be empty")
    updated = alerts_service.put_rule(request, rule_id, payload)
    if not updated:
        # Could be invalid id or not found; keep simple 404 for consumers.
        raise HTTPException(status_code=404, detail="rule not found")
    return updated


@router.patch(
    "/rules/{rule_id}",
    response_model=AlertRuleOut,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Update alert rule",
    description="Patch an existing alert rule by ruleId (partial update).",
    operation_id="patch_alert_rule",
)
def patch_rule(
    request: Request,
    payload: AlertRuleUpdate,
    rule_id: str = Path(..., description="Rule id (Mongo ObjectId string)."),
) -> AlertRuleOut:
    """Patch an alert rule."""
    if payload.name is not None and not payload.name.strip():
        raise HTTPException(status_code=400, detail="name must not be empty")
    updated = alerts_service.patch_rule(request, rule_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="rule not found")
    return updated


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Delete alert rule",
    description="Delete an alert rule by ruleId.",
    operation_id="delete_alert_rule",
)
def delete_rule(
    request: Request,
    rule_id: str = Path(..., description="Rule id (Mongo ObjectId string)."),
) -> None:
    """Delete an alert rule."""
    ok = alerts_service.delete_rule(request, rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="rule not found")
    return None


@router.get(
    "/events",
    response_model=AlertEventListResponse,
    summary="List alert events feed",
    description=(
        "List alert events (triggered/resolved) with filters: instanceId, ruleId, status, eventType, time range. "
        "Results sorted by createdAt desc."
    ),
    operation_id="list_alert_events",
)
def list_events(
    request: Request,
    instance_id: Optional[str] = Query(default=None, alias="instanceId"),
    rule_id: Optional[str] = Query(default=None, alias="ruleId"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="ok|triggered"),
    event_type: Optional[str] = Query(default=None, alias="eventType", description="triggered|resolved"),
    start: Optional[str] = Query(default=None, description="ISO datetime start (inclusive)"),
    end: Optional[str] = Query(default=None, description="ISO datetime end (inclusive)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100000),
) -> AlertEventListResponse:
    """List alert events with filters and pagination."""
    # Let Pydantic parse datetimes via the model (it accepts datetime, but also parses strings).
    filters = AlertEventsQuery(
        instanceId=instance_id,
        ruleId=rule_id,
        status=status_filter,
        eventType=event_type,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )
    items, total = alerts_service.list_events(request, filters)
    return AlertEventListResponse(items=items, total=total)
