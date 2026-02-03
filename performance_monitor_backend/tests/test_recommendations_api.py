from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest


@pytest.mark.anyio
async def test_recommendations_refresh_list_and_patch_status(
    async_client: httpx.AsyncClient,
    mongo_db,
    create_test_instance: str,
):
    instance_id = create_test_instance

    # Seed a metrics sample that can produce pooling recommendation (connections high vs assumed pool max=100)
    mongo_db["metrics_samples"].insert_one(
        {
            "instanceId": instance_id,
            "ts": datetime.now(timezone.utc),
            "connections": 99,
            "memResidentMB": 100.0,
            "opsPerSec": {"query": 10.0, "insert": 0.0, "update": 0.0, "delete": 0.0},
        }
    )

    # Refresh should compute and persist
    res = await async_client.post("/api/recommendations/refresh", params={"instanceId": instance_id})
    assert res.status_code == 200
    body = res.json()
    assert "items" in body and isinstance(body["items"], list)
    assert body["total"] == len(body["items"])
    assert len(body["items"]) >= 1

    # List should return latest items
    res = await async_client.get("/api/recommendations", params={"instanceId": instance_id})
    assert res.status_code == 200
    listed = res.json()
    assert len(listed["items"]) >= 1

    rec = listed["items"][0]
    assert rec["instance_id"] == instance_id
    assert rec["status"] in ("open", "applied", "dismissed")
    assert rec["id"]

    # Patch status
    rec_id = rec["id"]
    patch_res = await async_client.patch(f"/api/recommendations/{rec_id}", json={"status": "dismissed", "notes": "nope"})
    assert patch_res.status_code == 200
    patched = patch_res.json()
    assert patched["id"] == rec_id
    assert patched["status"] == "dismissed"
    assert patched["notes"] == "nope"
