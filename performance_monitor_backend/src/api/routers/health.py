from __future__ import annotations

import re
from typing import Any, Dict

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from src.api.schemas.common import HealthResponse, utc_now
from src.api.state import get_state

router = APIRouter(tags=["Health"])


def _sanitize_mongo_uri_for_response(uri: str) -> str:
    """Mask credentials in mongo URIs to avoid returning secrets to clients."""
    return re.sub(r"(mongodb(?:\+srv)?://)([^:@/]+):([^@/]+)@", r"\1\2:***@", uri)


class MongoConnectivityResponse(BaseModel):
    """Response model for backend↔Mongo connectivity diagnostics."""

    ok: bool = Field(..., description="Whether the backend can successfully ping MongoDB.")
    mongo_uri_source: str = Field(..., description="Which source provided the effective MongoDB URI.")
    mongo_db_connection_path: str | None = Field(
        default=None,
        description="Resolved path to mongodb_instance/db_connection.txt when present.",
    )
    mongo_uri_sanitized: str = Field(..., description="MongoDB URI with credentials masked.")
    timestamp: str = Field(..., description="UTC timestamp when the check was performed (ISO string).")
    meta: Dict[str, Any] = Field(default_factory=dict, description="Optional debug metadata.")


class MetricsStorageDiagnosticsResponse(BaseModel):
    """Diagnostics model describing metrics TTL/rollup configuration."""

    raw_ttl_seconds: int = Field(..., description="TTL (seconds) applied to raw metrics_samples (0 means disabled).")
    rollup_enabled: bool = Field(..., description="Whether background rollup/compaction is enabled.")
    rollup_bucket_seconds: int = Field(..., description="Rollup bucket size (seconds).")
    rollup_ttl_seconds: int = Field(..., description="TTL (seconds) applied to metrics_rollups (0 means disabled).")
    rollup_compaction_interval_sec: int = Field(..., description="How often the rollup job runs (seconds).")
    rollup_query_threshold_seconds: int = Field(
        ..., description="Timeframe threshold (seconds) at/above which metrics queries prefer rollups."
    )
    timestamp: str = Field(..., description="UTC timestamp when the diagnostics were produced (ISO string).")


@router.get(
    "/",
    response_model=HealthResponse,
    summary="Health check",
    description="Basic service liveness check used by deployment and the frontend.",
    operation_id="health_check",
)
def health_check() -> HealthResponse:
    """Return service liveness status."""
    return HealthResponse(status="ok", message="Healthy", timestamp=utc_now())


@router.get(
    "/api/health/mongo",
    response_model=MongoConnectivityResponse,
    summary="Mongo connectivity check",
    description=(
        "Pings the backend's configured MongoDB and returns diagnostics about how the URI was resolved "
        "(db_connection.txt vs env). Credentials are masked."
    ),
    operation_id="mongo_connectivity_check",
)
def mongo_connectivity_check(request: Request) -> MongoConnectivityResponse:
    """Connectivity check endpoint to validate backend↔Mongo and report which URI source/path is being used."""
    state = get_state(request.app)
    ok = state.mongo.ping()

    return MongoConnectivityResponse(
        ok=ok,
        mongo_uri_source=state.config.mongo_uri_source,
        mongo_db_connection_path=state.config.mongo_db_connection_path,
        mongo_uri_sanitized=_sanitize_mongo_uri_for_response(state.config.mongo_uri),
        timestamp=utc_now().isoformat(),
        meta={},
    )


@router.get(
    "/api/health/metrics-storage",
    response_model=MetricsStorageDiagnosticsResponse,
    summary="Metrics storage diagnostics",
    description="Reports raw TTL and rollup configuration (no secrets) for troubleshooting storage/retention behavior.",
    operation_id="metrics_storage_diagnostics",
)
def metrics_storage_diagnostics(request: Request) -> MetricsStorageDiagnosticsResponse:
    """Return metrics storage configuration diagnostics (TTL and rollup status)."""
    state = get_state(request.app)
    cfg = state.config
    return MetricsStorageDiagnosticsResponse(
        raw_ttl_seconds=int(cfg.metrics_raw_ttl_seconds),
        rollup_enabled=bool(cfg.metrics_rollup_enabled),
        rollup_bucket_seconds=int(cfg.metrics_rollup_bucket_seconds),
        rollup_ttl_seconds=int(cfg.metrics_rollup_ttl_seconds),
        rollup_compaction_interval_sec=int(cfg.metrics_rollup_compaction_interval_sec),
        rollup_query_threshold_seconds=int(cfg.metrics_rollup_query_threshold_seconds),
        timestamp=utc_now().isoformat(),
    )
