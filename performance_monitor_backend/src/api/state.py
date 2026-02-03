from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI

from src.api.config import BackendConfig
from src.api.db.mongo import MongoManager


@dataclass
class AppState:
    """Typed app.state container for shared singletons."""

    config: BackendConfig
    mongo: MongoManager
    sampler_task: Optional[object] = None  # asyncio.Task, but kept loose to avoid import cycles
    alerts_task: Optional[object] = None  # asyncio.Task, but kept loose to avoid import cycles
    rollup_task: Optional[object] = None  # asyncio.Task for metrics rollup loop


# PUBLIC_INTERFACE
def init_state(app: FastAPI, config: BackendConfig) -> None:
    """Initialize app.state with Mongo manager and config."""
    app.state.state = AppState(config=config, mongo=MongoManager(config.mongo_uri))


# PUBLIC_INTERFACE
def get_state(app: FastAPI) -> AppState:
    """Fetch typed AppState from a FastAPI app."""
    return app.state.state  # type: ignore[attr-defined]
