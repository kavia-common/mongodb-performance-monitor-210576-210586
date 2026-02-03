from __future__ import annotations

import os
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import alerts, health, instances, metrics, recommendations

openapi_tags = [
    {"name": "Health", "description": "Service health and liveness."},
    {"name": "Instances", "description": "CRUD for configured MongoDB instances (stubbed in-memory)."},
    {"name": "Metrics", "description": "Metrics summary and timeseries endpoints (stubbed sample data)."},
    {"name": "Alerts", "description": "Performance and health alerts (stubbed sample data)."},
    {"name": "Recommendations", "description": "Tuning recommendations and best practices (stubbed sample data)."},
]

app = FastAPI(
    title="MongoDB Performance Monitor API",
    description=(
        "Backend API for the MongoDB performance monitoring app. "
        "This initial version returns stubbed sample data to unblock frontend development; "
        "real MongoDB connectivity and collectors will be added in later steps."
    ),
    version="0.2.0",
    openapi_tags=openapi_tags,
)

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

