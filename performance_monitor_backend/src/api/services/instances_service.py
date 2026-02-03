from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4

from src.api.schemas.common import utc_now
from src.api.schemas.instances import InstanceCreate, InstanceOut, InstanceUpdate


@dataclass
class _InstanceRecord:
    id: str
    name: str
    host: str
    port: int
    username: Optional[str]
    tls: bool
    notes: Optional[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime


# Simple in-memory store to unblock frontend integration.
# NOTE: This will be replaced by persistent storage in a later work item.
_INSTANCE_STORE: Dict[str, _InstanceRecord] = {}


def _to_out(rec: _InstanceRecord) -> InstanceOut:
    return InstanceOut(
        id=rec.id,
        name=rec.name,
        host=rec.host,
        port=rec.port,
        username=rec.username,
        tls=rec.tls,
        notes=rec.notes,
        enabled=rec.enabled,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


# PUBLIC_INTERFACE
def list_instances() -> List[InstanceOut]:
    """Return all instances currently stored (stubbed in-memory)."""
    return [_to_out(r) for r in _INSTANCE_STORE.values()]


# PUBLIC_INTERFACE
def get_instance(instance_id: str) -> Optional[InstanceOut]:
    """Get a single instance by id. Returns None if not found."""
    rec = _INSTANCE_STORE.get(instance_id)
    return _to_out(rec) if rec else None


# PUBLIC_INTERFACE
def create_instance(payload: InstanceCreate) -> InstanceOut:
    """Create and store a new instance record (stubbed in-memory)."""
    now = utc_now()
    instance_id = str(uuid4())
    rec = _InstanceRecord(
        id=instance_id,
        name=payload.name,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        tls=payload.tls,
        notes=payload.notes,
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    _INSTANCE_STORE[instance_id] = rec
    return _to_out(rec)


# PUBLIC_INTERFACE
def update_instance(instance_id: str, payload: InstanceUpdate) -> Optional[InstanceOut]:
    """Update an instance record (stubbed in-memory). Returns None if not found."""
    rec = _INSTANCE_STORE.get(instance_id)
    if not rec:
        return None

    now = utc_now()
    rec.name = payload.name if payload.name is not None else rec.name
    rec.host = payload.host if payload.host is not None else rec.host
    rec.port = payload.port if payload.port is not None else rec.port
    rec.username = payload.username if payload.username is not None else rec.username
    rec.tls = payload.tls if payload.tls is not None else rec.tls
    rec.notes = payload.notes if payload.notes is not None else rec.notes
    rec.enabled = payload.enabled if payload.enabled is not None else rec.enabled
    rec.updated_at = now

    _INSTANCE_STORE[instance_id] = rec
    return _to_out(rec)


# PUBLIC_INTERFACE
def delete_instance(instance_id: str) -> bool:
    """Delete an instance record. Returns True if deleted, False if not found."""
    return _INSTANCE_STORE.pop(instance_id, None) is not None

