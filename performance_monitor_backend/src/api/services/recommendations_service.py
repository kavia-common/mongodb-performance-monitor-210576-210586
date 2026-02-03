from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from bson import ObjectId
from fastapi import Request

from src.api.schemas.common import Severity, utc_now
from src.api.schemas.insights import RecommendationOut, RecommendationStatus, RecommendationStatusUpdate
from src.api.state import get_state

logger = logging.getLogger(__name__)

# Heuristic constants (kept intentionally simple / conservative)
_SLOW_QUERY_MS_WARNING = 50.0
_SLOW_QUERY_MS_CRITICAL = 200.0

_CONN_UTIL_WARNING = 0.80
_CONN_UTIL_CRITICAL = 0.95


def _oid_str(oid: Any) -> str:
    try:
        return str(oid)
    except Exception:
        return ""


def _doc_to_out(doc: dict) -> RecommendationOut:
    return RecommendationOut(
        id=_oid_str(doc.get("_id") or doc.get("id")),
        instance_id=doc.get("instanceId"),
        type=doc["type"],
        severity=Severity(doc["severity"]),
        title=doc["title"],
        description=doc["description"],
        suggested_action=doc["suggested_action"],
        created_at=doc["createdAt"],
        status=doc.get("status", "open"),
        notes=doc.get("notes"),
        metadata=doc.get("metadata") or {},
    )


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _recent_metrics(request: Request, instance_id: str, limit: int = 60) -> List[dict]:
    cols = get_state(request.app).mongo.collections()
    cur = cols.metrics_samples.find(
        {"instanceId": instance_id},
        projection={"_id": 0},
        sort=[("ts", -1)],
        limit=max(1, min(500, limit)),
    )
    return list(cur)


def _latest_metrics(request: Request, instance_id: str) -> Optional[dict]:
    cols = get_state(request.app).mongo.collections()
    return cols.metrics_samples.find_one({"instanceId": instance_id}, projection={"_id": 0}, sort=[("ts", -1)])


def _load_default_ttl_days_from_config(request: Request) -> int:
    # Prefer config value loaded from env; fall back to env; then default.
    try:
        return int(get_state(request.app).config.recs_default_ttl_days)
    except Exception:
        return max(1, int(os.getenv("RECS_DEFAULT_TTL_DAYS", "14")))


def _target_pool_max_from_instance_doc(inst: dict) -> Optional[int]:
    """
    Best-effort pool max extraction.

    At the moment we don't explicitly store client maxPoolSize in the instance schema.
    We keep this hook so future schema additions can feed the heuristic.
    """
    # Reserved for future fields, e.g., inst["poolMaxSize"].
    v = inst.get("poolMaxSize")
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def _pool_recommendation(instance_id: str, inst: dict, latest: Optional[dict]) -> Optional[dict]:
    if not latest:
        return None

    connections = _safe_int(latest.get("connections"), 0)
    ops_per_sec = latest.get("opsPerSec") or {}
    total_ops = sum(_safe_float(v, 0.0) for v in ops_per_sec.values())

    pool_max = _target_pool_max_from_instance_doc(inst)
    if pool_max is None:
        # Use a conservative assumption for "max pool" if unknown.
        # This helps generate a reasonable signal while clearly labeling it as heuristic.
        pool_max = 100

    util = connections / max(1, pool_max)
    if util >= _CONN_UTIL_CRITICAL:
        severity = Severity.critical
    elif util >= _CONN_UTIL_WARNING:
        severity = Severity.warning
    else:
        # Not enough evidence to recommend changes.
        return None

    # Simple formula-based hint: suggest increasing maxPoolSize so utilization ~60% under current peak.
    suggested_pool_max = int(max(pool_max, round(connections / 0.60)))
    suggested_wait_ms = int(max(5000, min(60000, round(10000 + (util * 20000)))))

    return {
        "instanceId": instance_id,
        "type": "pooling",
        "severity": severity.value,
        "title": "Tune MongoDB client connection pooling",
        "description": (
            f"Observed {connections} active connections with an estimated maxPoolSize={pool_max} "
            f"(utilization ~{util:.0%}). High utilization can cause queueing and timeouts, especially during spikes."
        ),
        "suggested_action": (
            f"Review application MongoClient settings. Consider maxPoolSize≈{suggested_pool_max} and "
            f"waitQueueTimeoutMS≈{suggested_wait_ms}. Also verify you reuse a single MongoClient per service."
        ),
        "metadata": {
            "connections_current": connections,
            "ops_per_sec": float(total_ops),
            "assumed_pool_max": pool_max,
            "utilization": util,
            "suggested_maxPoolSize": suggested_pool_max,
            "suggested_waitQueueTimeoutMS": suggested_wait_ms,
            "note": "Pool max is assumed unless stored in instance metadata.",
        },
    }


def _indexing_recommendation(instance_id: str, latest: Optional[dict], inst: dict) -> dict:
    """
    Produce an indexing recommendation.

    Today we don't have query shapes / profiler integration, so we rely on
    avgQueryMs / slow indicators if present; otherwise, provide guidance.
    """
    avg_query_ms = _safe_float(latest.get("avgQueryMs"), 0.0) if latest else 0.0
    slow_ops_per_min = _safe_float(latest.get("slowOpsPerMin"), 0.0) if latest else 0.0

    # If we don't have real fields, stay "info" and provide guidance.
    severity = Severity.info
    if avg_query_ms >= _SLOW_QUERY_MS_CRITICAL or slow_ops_per_min >= 30:
        severity = Severity.critical
    elif avg_query_ms >= _SLOW_QUERY_MS_WARNING or slow_ops_per_min >= 5:
        severity = Severity.warning

    hot_collections = inst.get("topCollections") or inst.get("top_collections") or []
    if not isinstance(hot_collections, list):
        hot_collections = []

    coll_hint = ""
    if hot_collections:
        coll_hint = f" Focus on these collections first: {', '.join(map(str, hot_collections[:5]))}."

    return {
        "instanceId": instance_id,
        "type": "indexing",
        "severity": severity.value,
        "title": "Review slow operations and add missing indexes",
        "description": (
            "Current sampling has limited query-pattern visibility. If you see elevated query latency or slow operations, "
            "a common cause is missing indexes leading to collection scans (COLLSCAN)."
            + coll_hint
        ),
        "suggested_action": (
            "Enable the profiler or review application query logs to identify slow query shapes, then add indexes on "
            "common filter/sort fields (often compound). Validate with explain() and monitor p95 latency afterwards."
        ),
        "metadata": {
            "avgQueryMs": float(avg_query_ms),
            "slowOpsPerMin": float(slow_ops_per_min),
            "limitations": "Query patterns/profiler not yet integrated; recommendation is heuristic.",
        },
    }


def _ttl_recommendations(instance_id: str, inst: dict, recent_samples: List[dict], default_ttl_days: int) -> List[dict]:
    """
    Suggest TTL index for time-series like collections.

    Since we don't inspect actual target DB collections yet, we use:
    - instance notes/name hints if available,
    - any "top collections" stubs (if later filled),
    - and growth heuristics (samples insertion rate) as a proxy signal.
    """
    name = str(inst.get("name") or "")
    notes = str(inst.get("notes") or "")
    candidates: List[str] = []
    for c in (inst.get("topCollections") or inst.get("top_collections") or []):
        if isinstance(c, str):
            candidates.append(c)

    # Include heuristic candidates from instance descriptive fields
    for token in ("logs", "events", "metrics", "sessions", "audit"):
        if token in name.lower() or token in notes.lower():
            candidates.append(token)

    # If metrics_samples are growing rapidly, we recommend ensuring retention/TTL on log-like data.
    # We approximate growth by "samples per hour" (this is app's own storage, but can correlate with workload).
    created_ts = [s.get("ts") for s in recent_samples if s.get("ts")]
    growth_signal = len(created_ts) >= 30  # ~30 samples ~= 2.5 minutes at 5s; conservative flag

    recs: List[dict] = []
    if not candidates and not growth_signal:
        return recs

    retention_days = int(max(1, default_ttl_days))
    expire_seconds = retention_days * 24 * 3600

    scope_hint = ""
    if candidates:
        unique = []
        for c in candidates:
            if c not in unique:
                unique.append(c)
        scope_hint = f" Candidate collections/patterns: {', '.join(unique[:8])}."

    recs.append(
        {
            "instanceId": instance_id,
            "type": "ttl",
            "severity": Severity.info.value,
            "title": "Consider TTL indexes for time-based collections",
            "description": (
                "Collections that store time-based data (logs/events/metrics) can grow quickly and inflate the working set."
                " TTL indexes help automatically expire old documents and keep storage predictable."
                + scope_hint
            ),
            "suggested_action": (
                f"For each time-based collection, add an index on an expiry Date field with "
                f"expireAfterSeconds={expire_seconds} (~{retention_days} days). Confirm retention policy with requirements."
            ),
            "metadata": {
                "default_retention_days": retention_days,
                "expireAfterSeconds": expire_seconds,
                "growth_signal": growth_signal,
                "limitations": "Target collection inspection not yet implemented; recommendation is heuristic.",
            },
        }
    )
    return recs


def _build_recommendations(request: Request, instance_id: str) -> List[dict]:
    cols = get_state(request.app).mongo.collections()
    inst = cols.instances.find_one({"id": instance_id}, projection={"_id": 0})
    if not inst:
        # No instance => no recommendations; caller should handle 404 if desired.
        return []

    latest = _latest_metrics(request, instance_id)
    recent = _recent_metrics(request, instance_id, limit=120)
    default_ttl_days = _load_default_ttl_days_from_config(request)

    recs: List[dict] = []

    # Indexing
    recs.append(_indexing_recommendation(instance_id, latest, inst))

    # Pooling (only if we have enough evidence)
    pool_rec = _pool_recommendation(instance_id, inst, latest)
    if pool_rec:
        recs.append(pool_rec)

    # TTL
    recs.extend(_ttl_recommendations(instance_id, inst, recent, default_ttl_days))

    return recs


def _persist_recommendations(request: Request, recs: List[dict]) -> List[RecommendationOut]:
    cols = get_state(request.app).mongo.collections()
    now = utc_now()

    docs = []
    for r in recs:
        docs.append(
            {
                "instanceId": r.get("instanceId"),
                "type": r["type"],
                "severity": r["severity"],
                "title": r["title"],
                "description": r["description"],
                "suggested_action": r["suggested_action"],
                "createdAt": now,
                "status": "open",
                "notes": None,
                "metadata": r.get("metadata") or {},
            }
        )

    if not docs:
        return []

    res = cols.recommendations.insert_many(docs)
    inserted_ids = list(res.inserted_ids or [])
    inserted = list(
        cols.recommendations.find({"_id": {"$in": inserted_ids}}).sort("createdAt", -1)
    )
    return [_doc_to_out(d) for d in inserted]


# PUBLIC_INTERFACE
def list_recommendations(request: Request, instance_id: Optional[str], limit: Optional[int] = None) -> List[RecommendationOut]:
    """List latest persisted recommendations, optionally filtered by instanceId."""
    cols = get_state(request.app).mongo.collections()

    max_default = int(get_state(request.app).config.recs_max_return)
    lim = limit if limit is not None else max_default
    lim = max(1, min(500, int(lim)))

    query: Dict[str, Any] = {}
    if instance_id:
        query["instanceId"] = instance_id

    cur = cols.recommendations.find(query).sort("createdAt", -1).limit(lim)
    return [_doc_to_out(d) for d in cur]


# PUBLIC_INTERFACE
def refresh_recommendations(request: Request, instance_id: str) -> List[RecommendationOut]:
    """Recompute recommendations for an instance and persist the newly generated set."""
    recs = _build_recommendations(request, instance_id)
    return _persist_recommendations(request, recs)


# PUBLIC_INTERFACE
def update_recommendation_status(
    request: Request, rec_id: str, payload: RecommendationStatusUpdate
) -> Optional[RecommendationOut]:
    """Update recommendation status/notes. Returns updated recommendation or None if not found/invalid id."""
    cols = get_state(request.app).mongo.collections()

    try:
        oid = ObjectId(rec_id)
    except Exception:
        return None

    update_doc: Dict[str, Any] = {"status": payload.status}
    if payload.notes is not None:
        update_doc["notes"] = payload.notes

    res = cols.recommendations.find_one_and_update(
        {"_id": oid},
        {"$set": update_doc},
        return_document=True,
    )
    if not res:
        return None
    return _doc_to_out(res)
