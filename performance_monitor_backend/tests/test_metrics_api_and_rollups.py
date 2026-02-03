from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest


def _dt(hours_ago: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours_ago)


@pytest.mark.anyio
async def test_metrics_summary_uses_persisted_latest_sample(async_client: httpx.AsyncClient, mongo_db, create_test_instance: str):
    instance_id = create_test_instance

    # Seed a sample directly (sampler would do this, but we keep test deterministic)
    mongo_db["metrics_samples"].insert_one(
        {
            "instanceId": instance_id,
            "ts": _dt(0.01),
            "connections": 123,
            "opcounters": {"query": 10, "insert": 0, "update": 0, "delete": 0},
            "memResidentMB": 77.0,
            "opsPerSec": {"query": 5.0, "insert": 0.0, "update": 0.0, "delete": 0.0},
        }
    )

    res = await async_client.get(f"/api/metrics/{instance_id}/summary")
    assert res.status_code == 200
    body = res.json()

    assert body["instance_id"] == instance_id
    assert body["connections_current"] == 123
    assert body["operations_per_sec"] >= 5.0
    assert body["memory_mb"] == 77.0
    assert "as_of" in body


@pytest.mark.anyio
async def test_metrics_timeseries_returns_bucketed_points_from_raw(async_client: httpx.AsyncClient, mongo_db, create_test_instance: str):
    instance_id = create_test_instance

    # Seed multiple samples
    base = datetime.now(timezone.utc) - timedelta(minutes=30)
    for i in range(0, 20):
        mongo_db["metrics_samples"].insert_one(
            {
                "instanceId": instance_id,
                "ts": base + timedelta(seconds=i * 30),
                "connections": 10 + i,
                "memResidentMB": 50.0,
                "opsPerSec": {"query": float(i), "insert": 0.0, "update": 0.0, "delete": 0.0},
            }
        )

    payload = {
        "metric": "connections_current",
        "start": (base - timedelta(minutes=1)).isoformat(),
        "end": (base + timedelta(seconds=19 * 30 + 1)).isoformat(),
        "step_seconds": 60,
    }
    res = await async_client.post(f"/api/metrics/{instance_id}/timeseries", json=payload)
    assert res.status_code == 200
    body = res.json()

    assert body["instance_id"] == instance_id
    assert body["metric"] == "connections_current"
    assert body["unit"] == "count"
    assert isinstance(body["points"], list)
    assert len(body["points"]) > 0
    assert "ts" in body["points"][0] and "value" in body["points"][0]


@pytest.mark.anyio
async def test_metrics_timeseries_prefers_rollups_for_large_windows_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    async_client: httpx.AsyncClient,
    mongo_db,
    create_test_instance: str,
):
    """
    This asserts behavior of _should_use_rollups(): for large spans and when enabled,
    the endpoint should read from metrics_rollups instead of raw metrics_samples.

    We keep it deterministic by:
      - enabling rollups + setting query threshold low
      - seeding ONLY rollups (no raw samples)
    """
    monkeypatch.setenv("METRICS_ROLLUP_ENABLED", "true")
    monkeypatch.setenv("METRICS_ROLLUP_QUERY_THRESHOLD_SECONDS", "60")  # 1 minute threshold

    instance_id = create_test_instance
    start = datetime.now(timezone.utc) - timedelta(hours=12)
    end = datetime.now(timezone.utc) - timedelta(hours=11)

    # Seed rollup docs
    mongo_db["metrics_rollups"].insert_many(
        [
            {"instanceId": instance_id, "bucket": start, "metric": "connections_current", "value": 10.0},
            {"instanceId": instance_id, "bucket": start + timedelta(minutes=1), "metric": "connections_current", "value": 12.0},
        ]
    )

    payload = {
        "metric": "connections_current",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step_seconds": 60,
    }
    res = await async_client.post(f"/api/metrics/{instance_id}/timeseries", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert len(body["points"]) == 2
    assert body["points"][0]["value"] == 10.0
