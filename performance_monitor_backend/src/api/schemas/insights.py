from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from src.api.schemas.common import Severity


class Alert(BaseModel):
    """Alert model for UI integration."""

    id: str = Field(..., description="Alert identifier.")
    instance_id: str = Field(..., description="Instance ID this alert applies to.")
    title: str = Field(..., description="Short alert title.")
    description: str = Field(..., description="Detailed alert description.")
    severity: Severity = Field(..., description="Alert severity.")
    created_at: datetime = Field(..., description="UTC timestamp when the alert was created.")
    acknowledged: bool = Field(default=False, description="Whether the alert has been acknowledged.")


class AlertsResponse(BaseModel):
    """Envelope for listing alerts."""

    items: List[Alert] = Field(..., description="List of current alerts.")
    total: int = Field(..., ge=0, description="Total count of alerts returned.")


class Recommendation(BaseModel):
    """Recommendation model for UI integration."""

    id: str = Field(..., description="Recommendation identifier.")
    instance_id: Optional[str] = Field(
        default=None,
        description="Optional instance ID this recommendation applies to; null means global recommendation.",
    )
    title: str = Field(..., description="Short recommendation title.")
    rationale: str = Field(..., description="Why this recommendation is suggested.")
    severity: Severity = Field(..., description="Recommendation severity.")
    action_items: List[str] = Field(default_factory=list, description="Bulleted list of action items.")
    created_at: datetime = Field(..., description="UTC timestamp when recommendation was generated.")


class RecommendationsResponse(BaseModel):
    """Envelope for listing recommendations."""

    items: List[Recommendation] = Field(..., description="List of recommendations.")
    total: int = Field(..., ge=0, description="Total count of recommendations returned.")

