from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from fastapi import Request
from pymongo.errors import PyMongoError

from src.api.schemas.metrics import MetricValue, MetricsSummary, TimeseriesRequest, TimeseriesResponse
from src.api.services.instances_service import list_active_instance_docs
from src.api.state import get_state

logger = logging.getLogger(__name__)


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


def _compute_range(req: TimeseriesRequest) -> Tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    end = req.end or now
    start = req.start or (end - timedelta(hours=1))
    if start > end:
        start, end = end, start
    return start, end


def _safe_get(d: dict, path: List[str], default=0):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def _ops_sum(ops_per_sec: Dict[str, float]) -> float:
    return float(sum(float(v or 0.0) for v in ops_per_sec.values()))


def _get_latest_sample(request: Request, instance_id: str) -> dict | None:
    cols = get_state(request.app).mongo.collections()
    return cols.metrics_samples.find_one(
        {"instanceId": instance_id},
        sort=[("ts", -1)],
        projection={"_id": 0},
    )


def _get_recent_samples(request: Request, instance_id: str, limit: int = 20) -> List[dict]:
    cols = get_state(request.app).mongo.collections()
    cur = cols.metrics_samples.find(
        {"instanceId": instance_id},
        projection={"_id": 0},
        sort=[("ts", -1)],
        limit=max(1, min(limit, 500)),
    )
    return list(cur)


def _server_status_snapshot(request: Request, instance_id: str) -> dict | None:
    """
    Fetch serverStatus from the monitored instance (best-effort).

    This is used to fill gaps if no samples exist yet.
    """
    # Find instance doc (includes stored uri)
    cols = get_state(request.app).mongo.collections()
    inst = cols.instances.find_one({"id": instance_id}, projection={"_id": 0})
    if not inst or not inst.get("uri"):
        return None

    uri = inst["uri"]
    mongo = get_state(request.app).mongo

    try:
        client = mongo.target_client(instance_id, uri)
        return client.admin.command("serverStatus")
    except PyMongoError:
        logger.exception("serverStatus failed for instanceId=%s", instance_id)
        return None
    except Exception:
        logger.exception("Unexpected error fetching serverStatus for instanceId=%s", instance_id)
        return None


# PUBLIC_INTERFACE
def get_summary(request: Request, instance_id: str) -> MetricsSummary:
    """Return a metrics summary derived from persisted samples and/or live serverStatus."""
    now = datetime.now(timezone.utc)

    latest = _get_latest_sample(request, instance_id)
    if latest:
        connections_current = int(latest.get("connections", 0))
        ops_per_sec = latest.get("opsPerSec") or {}
        total_ops_per_sec = _ops_sum(ops_per_sec)
        mem_mb = float(latest.get("memResidentMB") or 0.0)
        # These are not yet collected; keep stable defaults for UI.
        slow_ops_per_min = float(latest.get("slowOpsPerMin") or 0.0)
        avg_query_ms = float(latest.get("avgQueryMs") or 0.0)
        cpu_pct = float(latest.get("cpuPct") or 0.0)
        as_of = latest.get("ts") or now
    else:
        ss = _server_status_snapshot(request, instance_id) or {}
        connections_current = int(_safe_get(ss, ["connections", "current"], 0))
        opcounters = _safe_get(ss, ["opcounters"], {}) if isinstance(ss, dict) else {}
        # Without a prior sample, we can't diff counters; show 0 ops/s to avoid lying.
        total_ops_per_sec = 0.0
        mem_mb = float(_safe_get(ss, ["mem", "resident"], 0.0))
        slow_ops_per_min = 0.0
        avg_query_ms = 0.0
        cpu_pct = 0.0
        as_of = now

        # If mem.resident is in MB already (mongod reports MB), use as-is.
        # If missing, keep 0.

        _ = opcounters  # reserved for later enhancements

    return MetricsSummary(
        instance_id=instance_id,
        as_of=as_of,
        connections_current=connections_current,
        operations_per_sec=float(max(0.0, total_ops_per_sec)),
        slow_ops_per_min=float(max(0.0, slow_ops_per_min)),
        avg_query_ms=float(max(0.0, avg_query_ms)),
        cpu_pct=float(max(0.0, min(100.0, cpu_pct))),
        memory_mb=float(max(0.0, mem_mb)),
        top_collections=[],
        tags={},
    )


def _metric_from_sample(sample: dict, metric: str) -> float:
    if metric == "connections_current":
        return float(sample.get("connections") or 0)
    if metric == "operations_per_sec":
        return float(_ops_sum(sample.get("opsPerSec") or {}))
    if metric == "slow_ops_per_min":
        return float(sample.get("slowOpsPerMin") or 0.0)
    if metric == "avg_query_ms":
        return float(sample.get("avgQueryMs") or 0.0)
    if metric == "cpu_pct":
        return float(sample.get("cpuPct") or 0.0)
    if metric == "memory_mb":
        return float(sample.get("memResidentMB") or 0.0)
    return 0.0


# PUBLIC_INTERFACE
def get_timeseries(request: Request, instance_id: str, req: TimeseriesRequest) -> TimeseriesResponse:
    """
    Return timeseries points for charting from persisted metrics_samples.

    For now, we fetch raw samples in [start,end] and optionally bucket them by averaging within each bucket.
    """
    start, end = _compute_range(req)
    cols = get_state(request.app).mongo.collections()

    # Pull samples ascending by ts for stable bucketing
    docs = list(
        cols.metrics_samples.find(
            {"instanceId": instance_id, "ts": {"$gte": start, "$lte": end}},
            projection={"_id": 0},
        ).sort("ts", 1)
    )

    if not docs:
        return TimeseriesResponse(instance_id=instance_id, metric=req.metric, points=[], unit=_unit_for(req.metric))

    step = max(10, int(req.step_seconds))
    bucket_ms = step * 1000

    buckets: Dict[int, List[float]] = {}
    bucket_ts: Dict[int, datetime] = {}
    for d in docs:
        ts: datetime = d["ts"]
        key = int(ts.timestamp() * 1000) // bucket_ms
        buckets.setdefault(key, []).append(_metric_from_sample(d, req.metric))
        # Keep earliest ts in bucket for display
        bucket_ts.setdefault(key, ts)

    points: List[MetricValue] = []
    for key in sorted(buckets.keys()):
        vals = buckets[key]
        avg = float(sum(vals) / max(1, len(vals)))
        points.append(MetricValue(ts=bucket_ts[key], value=avg))

    return TimeseriesResponse(
        instance_id=instance_id,
        metric=req.metric,
        points=points,
        unit=_unit_for(req.metric),
    )


# PUBLIC_INTERFACE
def get_active_instances_for_sampling(request: Request) -> List[dict]:
    """Return active instance docs for background sampler."""
    return list_active_instance_docs(request)
