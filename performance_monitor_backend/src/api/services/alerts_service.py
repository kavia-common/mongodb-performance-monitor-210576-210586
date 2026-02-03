from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from fastapi import Request

from src.api.schemas.alerts import (
    AlertEventOut,
    AlertEventsQuery,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
)
from src.api.schemas.common import utc_now
from src.api.state import get_state

logger = logging.getLogger(__name__)


def _oid_str(v: Any) -> str:
    try:
        return str(v)
    except Exception:
        return ""


def _doc_to_rule_out(doc: dict) -> AlertRuleOut:
    return AlertRuleOut(
        id=_oid_str(doc.get("_id")),
        name=doc["name"],
        type=doc["type"],
        enabled=bool(doc.get("enabled", True)),
        severity=doc.get("severity", "warning"),
        threshold=float(doc.get("threshold", 0.0)),
        window_sec=int(doc.get("windowSec", 60)),
        instanceScope=doc.get("instanceScope"),
        createdAt=doc["createdAt"],
        updatedAt=doc["updatedAt"],
    )


def _doc_to_event_out(doc: dict) -> AlertEventOut:
    return AlertEventOut(
        id=_oid_str(doc.get("_id")),
        ruleId=doc["ruleId"],
        instanceId=doc["instanceId"],
        eventType=doc["eventType"],
        status=doc["status"],
        severity=doc.get("severity", "warning"),
        title=doc.get("title", ""),
        message=doc.get("message", ""),
        value=doc.get("value"),
        threshold=doc.get("threshold"),
        windowSec=doc.get("windowSec"),
        createdAt=doc["createdAt"],
        meta=doc.get("meta") or {},
    )


def _build_rules_query(instance_id: Optional[str]) -> Dict[str, Any]:
    # A rule can be global (instanceScope=None) or specific to an instance.
    if not instance_id:
        return {}
    return {"$or": [{"instanceScope": None}, {"instanceScope": instance_id}]}


# PUBLIC_INTERFACE
def init_alerts_indexes(request: Request) -> None:
    """Ensure alerts collections indexes exist (delegates to MongoManager.init_indexes())."""
    get_state(request.app).mongo.init_indexes()


# PUBLIC_INTERFACE
def list_rules(request: Request, instance_id: Optional[str] = None) -> List[AlertRuleOut]:
    """List alert rules, optionally filtered to rules applicable to a given instance."""
    cols = get_state(request.app).mongo.collections()
    q = _build_rules_query(instance_id)
    docs = list(cols.alert_rules.find(q).sort("createdAt", -1))
    return [_doc_to_rule_out(d) for d in docs]


# PUBLIC_INTERFACE
def create_rule(request: Request, payload: AlertRuleCreate) -> AlertRuleOut:
    """Create a new alert rule."""
    cols = get_state(request.app).mongo.collections()
    now = utc_now()
    doc = {
        "name": payload.name.strip(),
        "type": payload.type,
        "enabled": bool(payload.enabled),
        "severity": payload.severity.value,
        "threshold": float(payload.threshold),
        "windowSec": int(payload.window_sec),
        "instanceScope": payload.instance_scope,
        "createdAt": now,
        "updatedAt": now,
    }
    res = cols.alert_rules.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _doc_to_rule_out(doc)


# PUBLIC_INTERFACE
def get_rule(request: Request, rule_id: str) -> Optional[AlertRuleOut]:
    """Fetch a rule by id; returns None if not found or id invalid."""
    cols = get_state(request.app).mongo.collections()
    try:
        oid = ObjectId(rule_id)
    except Exception:
        return None
    doc = cols.alert_rules.find_one({"_id": oid})
    return _doc_to_rule_out(doc) if doc else None


def _apply_rule_update(existing: dict, payload: AlertRuleUpdate) -> dict:
    updated = dict(existing)

    if payload.name is not None:
        updated["name"] = payload.name.strip()
    if payload.type is not None:
        updated["type"] = payload.type
    if payload.enabled is not None:
        updated["enabled"] = bool(payload.enabled)
    if payload.severity is not None:
        updated["severity"] = payload.severity.value
    if payload.threshold is not None:
        updated["threshold"] = float(payload.threshold)
    if payload.window_sec is not None:
        updated["windowSec"] = int(payload.window_sec)

    # NOTE: instance_scope explicitly set to None means "global".
    if payload.instance_scope is not None or "instanceScope" in payload.model_fields_set:
        updated["instanceScope"] = payload.instance_scope

    updated["updatedAt"] = utc_now()
    return updated


# PUBLIC_INTERFACE
def put_rule(request: Request, rule_id: str, payload: AlertRuleCreate) -> Optional[AlertRuleOut]:
    """Full replace of a rule's editable fields. Returns None if not found/invalid id."""
    cols = get_state(request.app).mongo.collections()
    try:
        oid = ObjectId(rule_id)
    except Exception:
        return None

    existing = cols.alert_rules.find_one({"_id": oid})
    if not existing:
        return None

    now = utc_now()
    doc = {
        "_id": oid,
        "name": payload.name.strip(),
        "type": payload.type,
        "enabled": bool(payload.enabled),
        "severity": payload.severity.value,
        "threshold": float(payload.threshold),
        "windowSec": int(payload.window_sec),
        "instanceScope": payload.instance_scope,
        "createdAt": existing.get("createdAt", now),
        "updatedAt": now,
    }
    cols.alert_rules.replace_one({"_id": oid}, doc, upsert=False)
    return _doc_to_rule_out(doc)


# PUBLIC_INTERFACE
def patch_rule(request: Request, rule_id: str, payload: AlertRuleUpdate) -> Optional[AlertRuleOut]:
    """Partial update of a rule. Returns None if not found/invalid id."""
    cols = get_state(request.app).mongo.collections()
    try:
        oid = ObjectId(rule_id)
    except Exception:
        return None

    existing = cols.alert_rules.find_one({"_id": oid})
    if not existing:
        return None

    updated = _apply_rule_update(existing, payload)
    cols.alert_rules.replace_one({"_id": oid}, updated, upsert=False)
    return _doc_to_rule_out(updated)


# PUBLIC_INTERFACE
def delete_rule(request: Request, rule_id: str) -> bool:
    """Delete a rule. Returns True if deleted, False if not found/invalid id."""
    cols = get_state(request.app).mongo.collections()
    try:
        oid = ObjectId(rule_id)
    except Exception:
        return False
    res = cols.alert_rules.delete_one({"_id": oid})
    return res.deleted_count > 0


def _events_query_from_filters(q: AlertEventsQuery) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if q.instance_id:
        query["instanceId"] = q.instance_id
    if q.rule_id:
        query["ruleId"] = q.rule_id
    if q.status:
        query["status"] = q.status
    if q.event_type:
        query["eventType"] = q.event_type

    if q.start or q.end:
        created: Dict[str, Any] = {}
        if q.start:
            created["$gte"] = q.start
        if q.end:
            created["$lte"] = q.end
        query["createdAt"] = created

    return query


# PUBLIC_INTERFACE
def list_events(request: Request, filters: AlertEventsQuery) -> Tuple[List[AlertEventOut], int]:
    """
    List alert events with filters and pagination.

    Returns (items, total_matching).
    """
    cols = get_state(request.app).mongo.collections()
    q = _events_query_from_filters(filters)

    total = int(cols.alert_events.count_documents(q))
    docs = list(
        cols.alert_events.find(q)
        .sort("createdAt", -1)
        .skip(int(filters.offset))
        .limit(int(filters.limit))
    )
    return ([_doc_to_event_out(d) for d in docs], total)
