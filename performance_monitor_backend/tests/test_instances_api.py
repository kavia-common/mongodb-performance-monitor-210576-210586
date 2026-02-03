from __future__ import annotations

import httpx
import pytest


@pytest.mark.anyio
async def test_instances_crud_persists_in_mongo(async_client: httpx.AsyncClient):
    # Create
    payload = {
        "name": "My Instance",
        "host": "localhost",
        "port": 5000,
        "username": "appuser",
        "tls": False,
        "notes": "created by test",
    }
    res = await async_client.post("/api/instances", json=payload)
    assert res.status_code == 201
    created = res.json()
    assert created["name"] == payload["name"]
    assert created["host"] == payload["host"]
    assert created["port"] == payload["port"]
    assert created["username"] == payload["username"]
    assert created["tls"] is False
    assert created["notes"] == payload["notes"]
    assert created["enabled"] is True
    assert "id" in created and created["id"]
    assert "created_at" in created and "updated_at" in created

    instance_id = created["id"]

    # Read single
    res = await async_client.get(f"/api/instances/{instance_id}")
    assert res.status_code == 200
    fetched = res.json()
    assert fetched["id"] == instance_id

    # List contains it
    res = await async_client.get("/api/instances")
    assert res.status_code == 200
    listed = res.json()
    assert "items" in listed and isinstance(listed["items"], list)
    assert any(x["id"] == instance_id for x in listed["items"])

    # Update (PUT is supported by router; payload is InstanceUpdate => partial allowed)
    res = await async_client.put(f"/api/instances/{instance_id}", json={"notes": "updated", "enabled": False})
    assert res.status_code == 200
    updated = res.json()
    assert updated["notes"] == "updated"
    assert updated["enabled"] is False

    # Delete
    res = await async_client.delete(f"/api/instances/{instance_id}")
    assert res.status_code == 204

    # Gone
    res = await async_client.get(f"/api/instances/{instance_id}")
    assert res.status_code == 404


@pytest.mark.anyio
async def test_create_instance_validates_required_fields(async_client: httpx.AsyncClient):
    res = await async_client.post("/api/instances", json={"name": "", "host": "localhost"})
    assert res.status_code == 400
    assert "name" in res.text.lower()

    res = await async_client.post("/api/instances", json={"name": "x", "host": ""})
    assert res.status_code == 400
    assert "host" in res.text.lower()
