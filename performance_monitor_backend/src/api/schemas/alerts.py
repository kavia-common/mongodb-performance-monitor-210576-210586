from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from src.api.schemas.common import Severity


AlertRuleType = Literal["high_connections", "high_ops_latency", "slow_operations_rate"]
AlertStatus = Literal["ok", "triggered"]
AlertEventType = Literal["triggered", "resolved"]


class AlertRuleBase(BaseModel):
    """Common fields for an alert rule."""

    name: str = Field(..., description="Human-friendly rule name.")
    type: AlertRuleType = Field(..., description="Rule type identifier.")
    enabled: bool = Field(True, description="Whether the rule is enabled for evaluation.")
    severity: Severity = Field(Severity.warning, description="Severity of the alert when triggered.")

    threshold: float = Field(
        ...,
        description="Threshold value used by the rule (meaning depends on rule type).",
        ge=0,
    )
    window_sec: int = Field(
        60,
        description="Lookback window (seconds) used for evaluation.",
        ge=1,
        le=24 * 3600,
    )

    instance_scope: Optional[str] = Field(
        default=None,
        description="InstanceId to scope this rule to; null means apply to all instances.",
        alias="instanceScope",
    )


class AlertRuleCreate(AlertRuleBase):
    """Request model for creating a rule."""


class AlertRuleUpdate(BaseModel):
    """Request model for full update (PUT) / partial update (PATCH)."""

    name: Optional[str] = Field(default=None, description="Human-friendly rule name.")
    type: Optional[AlertRuleType] = Field(default=None, description="Rule type identifier.")
    enabled: Optional[bool] = Field(default=None, description="Whether the rule is enabled.")
    severity: Optional[Severity] = Field(default=None, description="Severity of the alert when triggered.")

    threshold: Optional[float] = Field(
        default=None, description="Threshold value for the rule.", ge=0
    )
    window_sec: Optional[int] = Field(
        default=None, description="Lookback window (seconds).", ge=1, le=24 * 3600
    )
    instance_scope: Optional[str] = Field(
        default=None,
        description="InstanceId to scope this rule to; null means apply to all instances.",
        alias="instanceScope",
    )


class AlertRuleOut(AlertRuleBase):
    """Response model for an alert rule."""

    id: str = Field(..., description="Rule id (Mongo ObjectId string).")
    created_at: datetime = Field(..., description="UTC timestamp when the rule was created.", alias="createdAt")
    updated_at: datetime = Field(..., description="UTC timestamp when the rule was last updated.", alias="updatedAt")


class AlertRuleListResponse(BaseModel):
    """Envelope for listing rules."""

    items: List[AlertRuleOut] = Field(..., description="List of alert rules.")
    total: int = Field(..., ge=0, description="Total count of rules returned.")


class AlertEventOut(BaseModel):
    """Response model for an alert event."""

    id: str = Field(..., description="Event id (Mongo ObjectId string).")
    rule_id: str = Field(..., description="Rule id (Mongo ObjectId string).", alias="ruleId")
    instance_id: str = Field(..., description="Instance id this event applies to.", alias="instanceId")

    event_type: AlertEventType = Field(..., description="Whether this event is a trigger or resolve.", alias="eventType")
    status: AlertStatus = Field(..., description="Current status after this event.")

    severity: Severity = Field(..., description="Severity associated with the rule at time of event.")
    title: str = Field(..., description="Short title for the event.")
    message: str = Field(..., description="Human-readable event message.")

    value: Optional[float] = Field(default=None, description="Measured value (if available).")
    threshold: Optional[float] = Field(default=None, description="Threshold (if applicable).")
    window_sec: Optional[int] = Field(default=None, description="Rule window used (seconds).", alias="windowSec")

    created_at: datetime = Field(..., description="UTC event creation timestamp.", alias="createdAt")
    meta: Dict[str, Any] = Field(default_factory=dict, description="Additional structured metadata.")


class AlertEventListResponse(BaseModel):
    """Envelope for listing alert events."""

    items: List[AlertEventOut] = Field(..., description="List of alert events.")
    total: int = Field(..., ge=0, description="Total count returned.")


class AlertEventsQuery(BaseModel):
    """Filter/pagination model for listing alert events (used by router query params)."""

    instance_id: Optional[str] = Field(default=None, description="Filter by instanceId.", alias="instanceId")
    rule_id: Optional[str] = Field(default=None, description="Filter by ruleId.", alias="ruleId")
    status: Optional[AlertStatus] = Field(default=None, description="Filter by status (ok|triggered).")
    event_type: Optional[AlertEventType] = Field(default=None, description="Filter by event type.")
    start: Optional[datetime] = Field(default=None, description="Start time (inclusive) filter.")
    end: Optional[datetime] = Field(default=None, description="End time (inclusive) filter.")
    limit: int = Field(100, ge=1, le=500, description="Max number of events to return.")
    offset: int = Field(0, ge=0, le=100000, description="Offset for pagination (simple skip).")
