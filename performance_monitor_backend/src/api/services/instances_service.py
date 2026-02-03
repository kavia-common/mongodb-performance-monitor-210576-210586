from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from fastapi import Request

from src.api.schemas.common import utc_now
from src.api.schemas.instances import InstanceCreate, InstanceOut, InstanceUpdate
from src.api.state import get_state


def _doc_to_out(doc: dict) -> InstanceOut:
    return InstanceOut(
        id=doc["id"],
        name=doc["name"],
        host=doc["host"],
        port=int(doc.get("port", 27017)),
        username=doc.get("username"),
        tls=bool(doc.get("tls", False)),
        notes=doc.get("notes"),
        enabled=bool(doc.get("enabled", True)),
        created_at=doc["createdAt"],
        updated_at=doc["updatedAt"],
    )


# PUBLIC_INTERFACE
def list_instances(request: Request) -> List[InstanceOut]:
    """Return all instances from MongoDB (perfmon.instances)."""
    cols = get_state(request.app).mongo.collections()
    docs = list(cols.instances.find({}, projection={"_id": 0}).sort("createdAt", 1))
    return [_doc_to_out(d) for d in docs]


# PUBLIC_INTERFACE
def get_instance(request: Request, instance_id: str) -> Optional[InstanceOut]:
    """Get a single instance by id. Returns None if not found."""
    cols = get_state(request.app).mongo.collections()
    doc = cols.instances.find_one({"id": instance_id}, projection={"_id": 0})
    return _doc_to_out(doc) if doc else None


def _build_target_uri(payload: InstanceCreate | InstanceOut | dict) -> str:
    """
    Build a MongoDB connection URI for a monitored target instance.

    NOTE: This is a minimal builder to maintain backward compatibility with the existing schema
    (host/port/username/tls). If username is provided without password, the URI will omit credentials.
    """
    host = payload["host"] if isinstance(payload, dict) else payload.host
    port = payload.get("port", 27017) if isinstance(payload, dict) else payload.port
    username = payload.get("username") if isinstance(payload, dict) else payload.username
    tls = payload.get("tls", False) if isinstance(payload, dict) else payload.tls

    scheme = "mongodb"
    auth = f"{username}@" if username else ""
    # We intentionally do not store password in this work item.
    # authSource=admin is a reasonable default for many dev instances.
    params = []
    if tls:
        params.append("tls=true")
    # Always include authSource=admin so username-only cases can still work in many defaults.
    params.append("authSource=admin")
    query = "&".join(params)
    return f"{scheme}://{auth}{host}:{port}/?{query}"


# PUBLIC_INTERFACE
def create_instance(request: Request, payload: InstanceCreate) -> InstanceOut:
    """Create and store a new instance record in MongoDB."""
    cols = get_state(request.app).mongo.collections()
    now = utc_now()
    instance_id = str(uuid4())

    doc = {
        "id": instance_id,
        "name": payload.name,
        "host": payload.host,
        "port": payload.port,
        "username": payload.username,
        "tls": payload.tls,
        "notes": payload.notes,
        "enabled": True,
        "uri": _build_target_uri(payload.model_dump()),
        "createdAt": now,
        "updatedAt": now,
        "isActive": True,  # required by new persistence spec; maps from enabled
    }
    cols.instances.insert_one(doc)
    return _doc_to_out(doc)


# PUBLIC_INTERFACE
def update_instance(request: Request, instance_id: str, payload: InstanceUpdate) -> Optional[InstanceOut]:
    """Update an instance record in MongoDB. Returns None if not found."""
    cols = get_state(request.app).mongo.collections()
    existing = cols.instances.find_one({"id": instance_id}, projection={"_id": 0})
    if not existing:
        return None

    now = utc_now()
    updated = dict(existing)
    # Apply partials
    if payload.name is not None:
        updated["name"] = payload.name
    if payload.host is not None:
        updated["host"] = payload.host
    if payload.port is not None:
        updated["port"] = payload.port
    if payload.username is not None:
        updated["username"] = payload.username
    if payload.tls is not None:
        updated["tls"] = payload.tls
    if payload.notes is not None:
        updated["notes"] = payload.notes
    if payload.enabled is not None:
        updated["enabled"] = payload.enabled
        updated["isActive"] = bool(payload.enabled)

    updated["updatedAt"] = now
    updated["uri"] = _build_target_uri(updated)

    cols.instances.replace_one({"id": instance_id}, updated, upsert=False)
    return _doc_to_out(updated)


# PUBLIC_INTERFACE
def delete_instance(request: Request, instance_id: str) -> bool:
    """Delete an instance record. Returns True if deleted, False if not found."""
    cols = get_state(request.app).mongo.collections()
    res = cols.instances.delete_one({"id": instance_id})
    return res.deleted_count > 0


# PUBLIC_INTERFACE
def list_active_instance_docs(request: Request) -> List[dict]:
    """Return raw instance docs for enabled/active instances (used by sampler)."""
    cols = get_state(request.app).mongo.collections()
    # Backward compatible: treat enabled=True or isActive=True as active.
    cursor = cols.instances.find(
        {"$or": [{"enabled": True}, {"isActive": True}]},
        projection={"_id": 0},
    )
    return list(cursor)
