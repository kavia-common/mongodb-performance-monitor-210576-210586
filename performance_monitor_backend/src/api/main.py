from __future__ import annotations

import asyncio
import logging
import os
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.config import load_config
from src.api.routers import alerts, health, instances, metrics, recommendations
from src.api.services.alerts_evaluator import alerts_evaluator_loop
from src.api.services.metrics_rollup import rollup_loop
from src.api.services.metrics_sampler import sampler_loop
from src.api.state import get_state, init_state

openapi_tags = [
    {"name": "Health", "description": "Service health and liveness."},
    {"name": "Instances", "description": "CRUD for configured MongoDB instances (stubbed in-memory)."},
    {"name": "Metrics", "description": "Metrics summary and timeseries endpoints (stubbed sample data)."},
    {"name": "Alerts", "description": "Performance and health alerts (stubbed sample data)."},
    {"name": "Recommendations", "description": "Tuning recommendations and best practices (stubbed sample data)."},
]

logger = logging.getLogger(__name__)

app = FastAPI(
    title="MongoDB Performance Monitor API",
    description=(
        "Backend API for the MongoDB performance monitoring app. "
        "This version stores configuration and collected samples in MongoDB (perfmon DB) "
        "and runs background loops for sampling, alerts evaluation, and optional rollups/compaction."
    ),
    version="0.3.0",
    openapi_tags=openapi_tags,
)

# Initialize typed app state (config + Mongo manager)
init_state(app, load_config())


@app.on_event("startup")
async def _on_startup() -> None:
    """Startup hook: connect to Mongo, validate connectivity, ensure indexes, and start background loops."""
    state = get_state(app)

    # Connect + verify early so misconfigured Mongo doesn't silently break background tasks.
    state.mongo.connect_app()
    if not state.mongo.ping():
        raise RuntimeError(
            "Mongo connectivity check failed during startup. "
            "Verify mongodb_instance/db_connection.txt (preferred) or BACKEND_MONGO_URI."
        )

    # Initialize indexes with TTLs driven by env config.
    state.mongo.init_indexes(
        raw_ttl_seconds=int(state.config.metrics_raw_ttl_seconds),
        rollup_ttl_seconds=int(state.config.metrics_rollup_ttl_seconds),
    )

    app.state._sampler_shutdown = asyncio.Event()
    state.sampler_task = asyncio.create_task(sampler_loop(state, app.state._sampler_shutdown))

    app.state._alerts_shutdown = asyncio.Event()
    state.alerts_task = asyncio.create_task(alerts_evaluator_loop(state, app.state._alerts_shutdown))

    # Optional rollups/compaction task
    app.state._rollup_shutdown = asyncio.Event()
    state.rollup_task = asyncio.create_task(rollup_loop(state, app.state._rollup_shutdown))


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    """Shutdown hook: stop sampler/evaluator/rollups and close Mongo connections."""
    state = get_state(app)

    sampler_shutdown = getattr(app.state, "_sampler_shutdown", None)
    if sampler_shutdown is not None:
        sampler_shutdown.set()
    sampler_task = state.sampler_task
    if sampler_task is not None:
        try:
            await asyncio.wait_for(sampler_task, timeout=5.0)
        except Exception:
            logger.exception("Error stopping sampler task")

    alerts_shutdown = getattr(app.state, "_alerts_shutdown", None)
    if alerts_shutdown is not None:
        alerts_shutdown.set()
    alerts_task = state.alerts_task
    if alerts_task is not None:
        try:
            await asyncio.wait_for(alerts_task, timeout=5.0)
        except Exception:
            logger.exception("Error stopping alerts evaluator task")

    rollup_shutdown = getattr(app.state, "_rollup_shutdown", None)
    if rollup_shutdown is not None:
        rollup_shutdown.set()
    rollup_task = getattr(state, "rollup_task", None)
    if rollup_task is not None:
        try:
            await asyncio.wait_for(rollup_task, timeout=5.0)
        except Exception:
            logger.exception("Error stopping rollup task")

    state.mongo.close()


def _env_frontend_url() -> str | None:
    # Support both:
    # - standardized: FRONTEND_URL
    # - legacy (already used in this project/container env list): REACT_APP_FRONTEND_URL
    return os.getenv("FRONTEND_URL") or os.getenv("REACT_APP_FRONTEND_URL")


def _env_cors_extra_origins() -> List[str]:
    # Comma-separated list for preview deployments, etc.
    raw = os.getenv("CORS_ALLOW_ORIGINS") or ""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts


# CORS: allow local frontend by default, plus explicit frontend URL and optional extra origins.
allowed_origins: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
frontend_url = _env_frontend_url()
if frontend_url:
    allowed_origins.append(frontend_url)
allowed_origins.extend(_env_cors_extra_origins())

# De-dupe while preserving order
_seen = set()
allowed_origins = [o for o in allowed_origins if not (o in _seen or _seen.add(o))]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(instances.router)
app.include_router(metrics.router)
app.include_router(alerts.router)
app.include_router(recommendations.router)
