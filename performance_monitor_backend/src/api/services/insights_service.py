from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4

from src.api.schemas.common import Severity
from src.api.schemas.insights import Alert, Recommendation


def _now() -> datetime:
    return datetime.now(timezone.utc)


# PUBLIC_INTERFACE
def list_alerts(instance_id: Optional[str] = None) -> List[Alert]:
    """Return stubbed alerts; optionally filter by instance_id."""
    base_time = _now()
    items = [
        Alert(
            id=str(uuid4()),
            instance_id="demo-instance-1",
            title="High connection count",
            description="Connections are above the configured threshold (stub).",
            severity=Severity.warning,
            created_at=base_time - timedelta(minutes=12),
            acknowledged=False,
        ),
        Alert(
            id=str(uuid4()),
            instance_id="demo-instance-2",
            title="Slow queries detected",
            description="Average query latency exceeded 50ms over 5 minutes (stub).",
            severity=Severity.critical,
            created_at=base_time - timedelta(minutes=35),
            acknowledged=False,
        ),
        Alert(
            id=str(uuid4()),
            instance_id="demo-instance-1",
            title="Replication lag (simulated)",
            description="Replica lag above 2s (stub for UI integration).",
            severity=Severity.info,
            created_at=base_time - timedelta(hours=2),
            acknowledged=True,
        ),
    ]
    if instance_id:
        items = [a for a in items if a.instance_id == instance_id]
    return items


# PUBLIC_INTERFACE
def list_recommendations(instance_id: Optional[str] = None) -> List[Recommendation]:
    """Return stubbed recommendations; optionally filter by instance_id."""
    base_time = _now()
    items = [
        Recommendation(
            id=str(uuid4()),
            instance_id=instance_id or "demo-instance-1",
            title="Add an index for frequent queries",
            rationale="A collection scan pattern is suspected based on latency (stub).",
            severity=Severity.warning,
            action_items=[
                "Identify the slow query pattern in logs/profiler.",
                "Create a compound index to support the query shape.",
                "Validate using explain() and monitor p95 latency.",
            ],
            created_at=base_time - timedelta(hours=4),
        ),
        Recommendation(
            id=str(uuid4()),
            instance_id=None,
            title="Enable connection pooling",
            rationale="Pooling reduces overhead when application creates many short-lived connections (stub).",
            severity=Severity.info,
            action_items=[
                "Use a single MongoClient per service.",
                "Set maxPoolSize appropriate to workload.",
                "Monitor connection churn and server connections.",
            ],
            created_at=base_time - timedelta(days=1),
        ),
        Recommendation(
            id=str(uuid4()),
            instance_id=instance_id or "demo-instance-2",
            title="Review TTL indexes for session collections",
            rationale="TTL helps control collection growth and reduce working set (stub).",
            severity=Severity.info,
            action_items=[
                "Confirm documents have a proper expiry field (Date).",
                "Create TTL index with expireAfterSeconds.",
                "Validate retention policy aligns with business requirements.",
            ],
            created_at=base_time - timedelta(days=2),
        ),
    ]
    if instance_id:
        items = [r for r in items if (r.instance_id in (None, instance_id))]
    return items

