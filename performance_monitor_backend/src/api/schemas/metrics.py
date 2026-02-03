from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class MetricValue(BaseModel):
    """A single metric data point."""

    ts: datetime = Field(..., description="UTC timestamp for the data point.")
    value: float = Field(..., description="Numeric value at the timestamp.")


class MetricsSummary(BaseModel):
    """A high-level snapshot summary for a MongoDB instance."""

    instance_id: str = Field(..., description="Instance ID the metrics correspond to.")
    as_of: datetime = Field(..., description="UTC timestamp representing when this summary was produced.")

    connections_current: int = Field(..., ge=0, description="Current number of open connections.")
    operations_per_sec: float = Field(..., ge=0, description="Approximate operations per second.")
    slow_ops_per_min: float = Field(..., ge=0, description="Approximate slow operations per minute.")
    avg_query_ms: float = Field(..., ge=0, description="Approximate average query latency in milliseconds.")
    cpu_pct: float = Field(..., ge=0, le=100, description="Approximate CPU percent (host or container).")
    memory_mb: float = Field(..., ge=0, description="Approximate memory usage (MB).")

    top_collections: List[str] = Field(
        default_factory=list,
        description="Stub list of 'hot' collections used for UI preview; real collector will fill later.",
    )
    tags: Dict[str, str] = Field(default_factory=dict, description="Optional labels/tags for the UI.")


class TimeseriesRequest(BaseModel):
    """Request body for fetching timeseries metrics."""

    metric: Literal[
        "connections_current",
        "operations_per_sec",
        "slow_ops_per_min",
        "avg_query_ms",
        "cpu_pct",
        "memory_mb",
    ] = Field(..., description="Metric key to fetch a timeseries for.")
    start: Optional[datetime] = Field(default=None, description="UTC start time (inclusive).")
    end: Optional[datetime] = Field(default=None, description="UTC end time (inclusive).")
    step_seconds: int = Field(60, ge=10, le=3600, description="Sampling granularity in seconds.")


class TimeseriesResponse(BaseModel):
    """Response model for timeseries metric data."""

    instance_id: str = Field(..., description="Instance ID the timeseries corresponds to.")
    metric: str = Field(..., description="Metric key.")
    points: List[MetricValue] = Field(..., description="Ordered list of points for charting.")
    unit: str = Field(..., description="Unit string for display (e.g., 'ms', '%', 'count').")

