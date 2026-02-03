from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from src.api.schemas.common import utc_now
from src.api.state import AppState

logger = logging.getLogger(__name__)


async def _run_in_thread(func, *args, **kwargs):
    """Run blocking pymongo calls in a worker thread."""
    return await asyncio.to_thread(func, *args, **kwargs)


def _floor_to_bucket(ts: datetime, bucket_seconds: int) -> datetime:
    """Floor a timezone-aware datetime to the start of its bucket."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    b = max(1, int(bucket_seconds))
    seconds = int(ts.timestamp())
    floored = (seconds // b) * b
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _ops_sum(ops_per_sec: Dict[str, float]) -> float:
    try:
        return float(sum(_safe_float(v, 0.0) for v in (ops_per_sec or {}).values()))
    except Exception:
        return 0.0


def _build_rollup_docs(instance_id: str, bucket: datetime, samples: List[dict]) -> List[dict]:
    """
    Produce rollup docs for a bucket.

    We store one doc per metric per (instanceId, bucket), keeping schema simple:
      {instanceId, bucket, metric, value, count, min, max, sum}

    This keeps metrics endpoints backward compatible by mapping rollups -> MetricValue.
    """
    if not samples:
        return []

    connections_vals = [_safe_float(s.get("connections"), 0.0) for s in samples]
    memory_vals = [_safe_float(s.get("memResidentMB"), 0.0) for s in samples]
    ops_vals = [_ops_sum(s.get("opsPerSec") or {}) for s in samples]

    def mk(metric: str, vals: List[float]) -> dict:
        c = int(len(vals))
        s = float(sum(vals))
        return {
            "instanceId": instance_id,
            "bucket": bucket,
            "metric": metric,
            "value": float(s / max(1, c)),
            "count": c,
            "min": float(min(vals) if vals else 0.0),
            "max": float(max(vals) if vals else 0.0),
            "sum": s,
        }

    return [
        mk("connections_current", connections_vals),
        mk("memory_mb", memory_vals),
        mk("operations_per_sec", ops_vals),
        # Future: slow_ops_per_min, avg_query_ms, cpu_pct when raw sampler collects them.
    ]


async def _fetch_active_instance_ids(state: AppState) -> List[str]:
    cols = state.mongo.collections()
    docs = await _run_in_thread(
        lambda: list(
            cols.instances.find(
                {"$or": [{"enabled": True}, {"isActive": True}]},
                projection={"_id": 0, "id": 1},
            )
        )
    )
    out: List[str] = []
    for d in docs:
        iid = d.get("id")
        if iid:
            out.append(str(iid))
    return out


async def _last_rollup_bucket(state: AppState, instance_id: str) -> Optional[datetime]:
    cols = state.mongo.collections()
    doc = await _run_in_thread(
        lambda: cols.metrics_rollups.find_one(
            {"instanceId": instance_id},
            sort=[("bucket", -1)],
            projection={"_id": 0, "bucket": 1},
        )
    )
    b = (doc or {}).get("bucket")
    return b if isinstance(b, datetime) else None


async def _rollup_instance_range(
    state: AppState,
    instance_id: str,
    start_bucket: datetime,
    end_exclusive: datetime,
    bucket_seconds: int,
) -> int:
    """
    Roll up raw samples for one instance in [start_bucket, end_exclusive) bucket by bucket.

    Returns number of rollup docs written.
    """
    cols = state.mongo.collections()
    written = 0
    b = start_bucket
    step = timedelta(seconds=max(1, int(bucket_seconds)))

    while b < end_exclusive:
        b_end = b + step

        samples = await _run_in_thread(
            lambda: list(
                cols.metrics_samples.find(
                    {"instanceId": instance_id, "ts": {"$gte": b, "$lt": b_end}},
                    projection={"_id": 0},
                )
            )
        )
        if samples:
            docs = _build_rollup_docs(instance_id, b, samples)
            # Upsert per (instanceId, bucket, metric) so reruns are idempotent.
            for d in docs:
                await _run_in_thread(
                    cols.metrics_rollups.update_one,
                    {"instanceId": d["instanceId"], "bucket": d["bucket"], "metric": d["metric"]},
                    {"$set": d},
                    True,
                )
                written += 1

        b = b_end

    return written


async def _rollup_tick(state: AppState) -> None:
    cfg = state.config
    if not cfg.metrics_rollup_enabled:
        return

    bucket_seconds = int(cfg.metrics_rollup_bucket_seconds)
    now = utc_now()

    # Only roll up "complete" buckets (exclude current in-progress bucket).
    end_exclusive = _floor_to_bucket(now, bucket_seconds)

    instance_ids = await _fetch_active_instance_ids(state)
    for instance_id in instance_ids:
        try:
            last = await _last_rollup_bucket(state, instance_id)
            if last is None:
                # Start from a bounded lookback to avoid scanning all history on first enable.
                # We rely on TTL / retention and typical usage where raw TTL is short.
                lookback = max(bucket_seconds * 2, 2 * 3600)  # at least 2 hours
                start_bucket = _floor_to_bucket(now - timedelta(seconds=lookback), bucket_seconds)
            else:
                start_bucket = last + timedelta(seconds=bucket_seconds)

            if start_bucket >= end_exclusive:
                continue

            await _rollup_instance_range(state, instance_id, start_bucket, end_exclusive, bucket_seconds, bucket_seconds)
        except Exception:
            # Keep logs minimal; do not include URIs or sensitive details.
            logger.exception("Metrics rollup tick failed for instanceId=%s", instance_id)


# PUBLIC_INTERFACE
async def rollup_loop(state: AppState, shutdown_event: asyncio.Event) -> None:
    """
    Background loop that compacts raw metrics_samples into metrics_rollups.

    Rollups are optional and controlled by:
      - METRICS_ROLLUP_ENABLED
      - METRICS_ROLLUP_BUCKET_SECONDS
      - METRICS_ROLLUP_TTL_SECONDS (index created at startup)
      - METRICS_ROLLUP_COMPACTION_INTERVAL_SEC

    The job is idempotent: it upserts per (instanceId, bucket, metric).
    """
    interval = max(5, int(state.config.metrics_rollup_compaction_interval_sec))
    bucket = int(state.config.metrics_rollup_bucket_seconds)

    # Minimal log to indicate status; avoids leaking config beyond these safe scalars.
    logger.info("Metrics rollup loop started (enabled=%s, interval=%ss, bucket=%ss)", state.config.metrics_rollup_enabled, interval, bucket)

    while not shutdown_event.is_set():
        tick_started = datetime.now(timezone.utc)
        try:
            await _rollup_tick(state)
        except Exception:
            logger.exception("Metrics rollup tick failed")

        elapsed = (datetime.now(timezone.utc) - tick_started).total_seconds()
        sleep_for = max(0.5, interval - elapsed)
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=sleep_for)
        except asyncio.TimeoutError:
            pass

    logger.info("Metrics rollup loop stopped")
