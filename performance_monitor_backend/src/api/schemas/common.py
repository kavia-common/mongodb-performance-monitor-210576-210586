from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Severity levels for alerts and recommendations."""

    info = "info"
    warning = "warning"
    critical = "critical"


class HealthResponse(BaseModel):
    """Response model for health endpoints."""

    status: str = Field(..., description="High-level health status string (e.g., 'ok').")
    message: str = Field(..., description="Human-readable status message.")
    timestamp: datetime = Field(..., description="UTC timestamp at time of response.")


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    detail: str = Field(..., description="Human-readable error details.")
    code: Optional[str] = Field(default=None, description="Optional machine-readable error code.")
    meta: Dict[str, Any] = Field(default_factory=dict, description="Optional metadata for debugging.")


# PUBLIC_INTERFACE
def utc_now() -> datetime:
    """Return a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)

