from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from src.api.schemas.metrics import MetricValue, MetricsSummary, TimeseriesRequest, TimeseriesResponse


def _unit_for(metric: str) -> str:
    if metric in ("avg_query_ms",):
        return "ms"
    if metric in ("cpu_pct",):
        return "%"
    if metric in ("memory_mb",):
        return "MB"
    if metric in ("operations_per_sec",):
        return "ops/s"
    if metric in ("slow_ops_per_min",):
        return "ops/min"
    return "count"


def _base_for(metric: str) -> float:
    return {
        "connections_current": 120.0,
        "operations_per_sec": 450.0,
        "slow_ops_per_min": 3.0,
        "avg_query_ms": 12.0,
        "cpu_pct": 35.0,
        "memory_mb": 1024.0,
    }.get(metric, 0.0)


def _wave(i: int) -> float:
    # Simple, deterministic pseudo-wave without importing numpy.
    return (i % 10) - 5


# PUBLIC_INTERFACE
def get_summary(instance_id: str) -> MetricsSummary:
    """Return a stubbed metrics summary for the given instance."""
    now = datetime.now(timezone.utc)
    return MetricsSummary(
        instance_id=instance_id,
        as_of=now,
        connections_current=128,
        operations_per_sec=475.2,
        slow_ops_per_min=2.4,
        avg_query_ms=14.8,
        cpu_pct=42.1,
        memory_mb=1536.0,
        top_collections=["users", "sessions", "events", "orders"],
        tags={"env": "dev", "region": "local"},
    )


def _compute_range(req: TimeseriesRequest) -> Tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    end = req.end or now
    start = req.start or (end - timedelta(hours=1))
    if start > end:
        start, end = end, start
    return start, end


# PUBLIC_INTERFACE
def get_timeseries(instance_id: str, req: TimeseriesRequest) -> TimeseriesResponse:
    """Return a stubbed timeseries dataset for chart rendering."""
    start, end = _compute_range(req)
    step = timedelta(seconds=req.step_seconds)

    points: List[MetricValue] = []
    i = 0
    ts = start
    base = _base_for(req.metric)

    while ts <= end and len(points) < 1000:
        # A small deterministic variation to look "live" on charts.
        val = base + _wave(i) * (0.8 if req.metric != "cpu_pct" else 1.2)
        if req.metric in ("cpu_pct",):
            val = max(0.0, min(100.0, val))
        points.append(MetricValue(ts=ts, value=float(val)))
        ts = ts + step
        i += 1

    return TimeseriesResponse(
        instance_id=instance_id,
        metric=req.metric,
        points=points,
        unit=_unit_for(req.metric),
    )

