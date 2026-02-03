from __future__ import annotations

import httpx
import pytest


@pytest.mark.anyio
async def test_root_health_ok(async_client: httpx.AsyncClient):
    res = await async_client.get("/")
    assert res.status_code == 200
    body = res.json()
    # HealthResponse: {status, message, timestamp}
    assert body.get("status") == "ok"
    assert "timestamp" in body


@pytest.mark.anyio
async def test_mongo_connectivity_check_reports_source_and_masks_credentials(async_client: httpx.AsyncClient):
    res = await async_client.get("/api/health/mongo")
    assert res.status_code == 200
    body = res.json()

    assert body["ok"] is True
    assert body["mongo_uri_source"] in ("mongodb_instance/db_connection.txt", "BACKEND_MONGO_URI", "unset")
    assert body["mongo_uri_sanitized"].startswith("mongodb://") or body["mongo_uri_sanitized"].startswith("mongodb+srv://")
    # password must be masked if present
    assert "***" in body["mongo_uri_sanitized"] or "@" not in body["mongo_uri_sanitized"]


@pytest.mark.anyio
async def test_metrics_storage_diagnostics_has_expected_shape(async_client: httpx.AsyncClient):
    res = await async_client.get("/api/health/metrics-storage")
    assert res.status_code == 200
    body = res.json()

    assert isinstance(body["raw_ttl_seconds"], int)
    assert isinstance(body["rollup_enabled"], bool)
    assert isinstance(body["rollup_bucket_seconds"], int)
    assert isinstance(body["rollup_ttl_seconds"], int)
    assert isinstance(body["rollup_compaction_interval_sec"], int)
    assert isinstance(body["rollup_query_threshold_seconds"], int)
    assert "timestamp" in body
