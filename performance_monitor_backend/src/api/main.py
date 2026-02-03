from __future__ import annotations

import asyncio
import logging
import os
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.config import load_config
from src.api.routers import alerts, health, instances, metrics, recommendations
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
        "and runs a background sampler that polls serverStatus for active instances."
    ),
    version="0.3.0",
    openapi_tags=openapi_tags,
)

# Initialize typed app state (config + Mongo manager)
init_state(app, load_config())


@app.on_event("startup")
async def _on_startup() -> None:
    """Startup hook: connect to Mongo, ensure indexes, and start background metrics sampler."""
    state = get_state(app)
    state.mongo.connect_app()
    state.mongo.init_indexes()

    app.state._sampler_shutdown = asyncio.Event()
    state.sampler_task = asyncio.create_task(sampler_loop(state, app.state._sampler_shutdown))


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    """Shutdown hook: stop sampler and close Mongo connections."""
    state = get_state(app)
    shutdown_event = getattr(app.state, "_sampler_shutdown", None)
    if shutdown_event is not None:
        shutdown_event.set()
    task = state.sampler_task
    if task is not None:
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except Exception:
            logger.exception("Error stopping sampler task")

    state.mongo.close()

# CORS: allow local frontend by default, plus any explicit frontend URL provided via env.
# Env var list provided for this container includes REACT_APP_FRONTEND_URL.
allowed_origins: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
frontend_url = os.getenv("REACT_APP_FRONTEND_URL")
if frontend_url:
    allowed_origins.append(frontend_url)

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

