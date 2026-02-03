from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from pymongo import MongoClient


def _parse_db_connection_uri(text: str) -> str | None:
    """
    Parse MongoDB URI from mongodb_instance/db_connection.txt.

    Expected formats:
      - 'mongosh mongodb://...'
      - or 'mongodb://...' / 'mongodb+srv://...'
    """
    if not text:
        return None
    first = (text.splitlines()[0] if text.splitlines() else "").strip()
    if not first:
        return None
    if first.startswith("mongosh "):
        return first[len("mongosh ") :].strip() or None
    m = re.search(r"(mongodb(?:\+srv)?://\S+)", first)
    return m.group(1) if m else None


def _load_repo_mongo_uri() -> str:
    """
    Resolve MongoDB URI for integration tests.

    Priority:
      1) mongodb_instance/db_connection.txt (repo convention)
      2) BACKEND_MONGO_URI env var (fallback)
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    db_path = os.path.join(
        repo_root,
        "mongodb-performance-monitor-210576-210587",
        "mongodb_instance",
        "db_connection.txt",
    )
    if os.path.exists(db_path):
        uri = _parse_db_connection_uri(open(db_path, encoding="utf-8").read())
        if uri:
            return uri

    env_uri = os.getenv("BACKEND_MONGO_URI")
    if env_uri:
        return env_uri

    raise RuntimeError(
        "No Mongo URI available for tests. Ensure mongodb_instance/db_connection.txt exists or set BACKEND_MONGO_URI."
    )


@pytest.fixture(scope="session")
def mongo_uri() -> str:
    """MongoDB URI for the running mongodb_instance (integration tests)."""
    return _load_repo_mongo_uri()


@pytest.fixture(scope="session")
def mongo_client(mongo_uri: str) -> Iterator[MongoClient]:
    """PyMongo client used by tests for direct DB inspection/cleanup."""
    client = MongoClient(mongo_uri, connect=True)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def mongo_db(mongo_client: MongoClient):
    """perfmon database handle (the backend uses DB name 'perfmon')."""
    return mongo_client["perfmon"]


@pytest.fixture(autouse=True)
def _clean_perfmon_collections(mongo_db) -> None:
    """
    Ensure collections are clean between tests.

    We keep a conservative list of collections used by the app to avoid leaking state
    across tests while not dropping indexes (dropping collections can remove indexes).
    """
    for name in [
        "instances",
        "metrics_samples",
        "metrics_rollups",
        "alerts",
        "alert_rules",
        "alert_events",
        "recommendations",
    ]:
        mongo_db[name].delete_many({})


@pytest.fixture(scope="session")
def app(monkeypatch: pytest.MonkeyPatch, mongo_uri: str):
    """
    FastAPI app fixture with env vars configured for deterministic tests.

    Important:
    - We let the app run its startup events (Mongo connect + index init + background loops).
    - We keep loops very fast (interval=1s) so we can observe outcomes quickly when needed.
    """
    monkeypatch.setenv("BACKEND_MONGO_URI", mongo_uri)

    # Keep loops responsive in tests
    monkeypatch.setenv("METRICS_SAMPLING_INTERVAL_SEC", "1")
    monkeypatch.setenv("ALERT_EVAL_INTERVAL_SEC", "1")
    monkeypatch.setenv("ALERT_EVENT_COOLDOWN_SEC", "0")

    # For rollup selection tests we will override per-test (monkeypatch) where needed.
    # Default: rollups disabled.
    monkeypatch.delenv("METRICS_ROLLUP_ENABLED", raising=False)

    from src.api.main import app as fastapi_app

    return fastapi_app


@pytest.fixture
async def async_client(app) -> AsyncIterator[httpx.AsyncClient]:
    """
    Async HTTP client bound to the FastAPI ASGI app.

    Uses httpx ASGITransport which triggers lifespan (startup/shutdown).
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def create_test_instance(async_client: httpx.AsyncClient) -> str:
    """
    Helper fixture to create an instance via the API and return its instanceId.

    Uses localhost:5000 because mongodb_instance exposes mongod internally on 5000
    (backend config already assumes/aligns this).
    """
    payload = {
        "name": "Test Instance",
        "host": "localhost",
        "port": 5000,
        "username": "appuser",
        "tls": False,
        "notes": "integration test",
        # password is accepted but not stored/returned
        "password": "dbuser123",
    }
    res = await async_client.post("/api/instances", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    assert "id" in data and data["id"]
    return data["id"]
