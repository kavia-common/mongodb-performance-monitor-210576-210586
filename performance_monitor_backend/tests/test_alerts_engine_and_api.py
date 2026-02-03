from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.anyio
async def test_alerts_rule_crud_and_events_trigger_resolve(
    async_client: httpx.AsyncClient,
    mongo_db,
    create_test_instance: str,
):
    instance_id = create_test_instance

    # Create a rule that triggers when connections > 5 over 60s window.
    rule_payload = {
        "name": "High connections test",
        "type": "high_connections",
        "enabled": True,
        "severity": "warning",
        "threshold": 5,
        "window_sec": 60,
        "instanceScope": instance_id,
    }
    res = await async_client.post("/api/alerts/rules", json=rule_payload)
    assert res.status_code == 201
    rule = res.json()
    rule_id = rule["id"]
    assert rule["name"] == rule_payload["name"]

    # Seed metrics to trigger
    t0 = _now() - timedelta(seconds=30)
    mongo_db["metrics_samples"].insert_many(
        [
            {
                "instanceId": instance_id,
                "ts": t0,
                "connections": 10,
                "memResidentMB": 10.0,
                "opsPerSec": {"query": 0.0, "insert": 0.0, "update": 0.0, "delete": 0.0},
            },
            {
                "instanceId": instance_id,
                "ts": t0 + timedelta(seconds=10),
                "connections": 12,
                "memResidentMB": 10.0,
                "opsPerSec": {"query": 0.0, "insert": 0.0, "update": 0.0, "delete": 0.0},
            },
        ]
    )

    # Let evaluator loop tick at least once (configured to 1s interval in conftest)
    # We'll poll events feed for up to a short time.
    found = None
    for _ in range(20):
        ev_res = await async_client.get("/api/alerts/events", params={"instanceId": instance_id, "ruleId": rule_id})
        assert ev_res.status_code == 200
        data = ev_res.json()
        items = data["items"]
        if items:
            found = items[0]
            break
        await __import__("asyncio").sleep(0.2)

    assert found is not None, "Expected at least one alert event after seeding triggering samples"
    assert found["eventType"] == "triggered"
    assert found["status"] == "triggered"
    assert found["ruleId"] == rule_id
    assert found["instanceId"] == instance_id

    # Seed metrics to resolve (connections below threshold)
    mongo_db["metrics_samples"].insert_one(
        {
            "instanceId": instance_id,
            "ts": _now(),
            "connections": 1,
            "memResidentMB": 10.0,
            "opsPerSec": {"query": 0.0, "insert": 0.0, "update": 0.0, "delete": 0.0},
        }
    )

    resolved = None
    for _ in range(25):
        ev_res = await async_client.get("/api/alerts/events", params={"instanceId": instance_id, "ruleId": rule_id})
        items = ev_res.json()["items"]
        # newest first; once resolved exists it should be first
        if items and items[0]["eventType"] == "resolved":
            resolved = items[0]
            break
        await __import__("asyncio").sleep(0.2)

    assert resolved is not None, "Expected a resolved event after seeding low-connection sample"
    assert resolved["status"] == "ok"


@pytest.mark.anyio
async def test_alerts_dedup_no_duplicate_events_without_state_change(
    async_client: httpx.AsyncClient,
    mongo_db,
    create_test_instance: str,
):
    instance_id = create_test_instance
    rule_payload = {
        "name": "Dedup test",
        "type": "high_connections",
        "enabled": True,
        "severity": "warning",
        "threshold": 1,
        "window_sec": 60,
        "instanceScope": instance_id,
    }
    res = await async_client.post("/api/alerts/rules", json=rule_payload)
    assert res.status_code == 201
    rule_id = res.json()["id"]

    # Trigger once
    mongo_db["metrics_samples"].insert_one(
        {
            "instanceId": instance_id,
            "ts": _now(),
            "connections": 10,
            "memResidentMB": 10.0,
            "opsPerSec": {"query": 0.0, "insert": 0.0, "update": 0.0, "delete": 0.0},
        }
    )

    # Wait for event
    for _ in range(20):
        ev_res = await async_client.get("/api/alerts/events", params={"instanceId": instance_id, "ruleId": rule_id})
        items = ev_res.json()["items"]
        if items:
            break
        await __import__("asyncio").sleep(0.2)

    # Insert more triggering samples; should NOT create a new event (no state change)
    mongo_db["metrics_samples"].insert_one(
        {
            "instanceId": instance_id,
            "ts": _now() + timedelta(seconds=1),
            "connections": 11,
            "memResidentMB": 10.0,
            "opsPerSec": {"query": 0.0, "insert": 0.0, "update": 0.0, "delete": 0.0},
        }
    )

    await __import__("asyncio").sleep(1.2)
    ev_res = await async_client.get("/api/alerts/events", params={"instanceId": instance_id, "ruleId": rule_id})
    assert ev_res.status_code == 200
    items = ev_res.json()["items"]
    # We expect only 1 event (the initial trigger) since there was no resolve.
    assert len(items) == 1
    assert items[0]["eventType"] == "triggered"
