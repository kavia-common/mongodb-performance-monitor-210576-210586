from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import RLock
from typing import Dict, Optional

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

logger = logging.getLogger(__name__)


APP_DB_NAME = "perfmon"


@dataclass(frozen=True)
class MongoCollections:
    """Convenience wrapper for app collections."""

    instances: Collection
    metrics_samples: Collection
    alerts: Collection
    recommendations: Collection


class MongoManager:
    """
    MongoDB connection manager.

    - Maintains one MongoClient for the app's own storage DB ("perfmon").
    - Maintains a cache of MongoClient objects for monitored target instances (keyed by instanceId).
    """

    def __init__(self, app_mongo_uri: str):
        self._app_mongo_uri = app_mongo_uri
        self._app_client: Optional[MongoClient] = None
        self._targets: Dict[str, MongoClient] = {}
        self._lock = RLock()

    def connect_app(self) -> None:
        """Initialize app Mongo client if needed."""
        with self._lock:
            if self._app_client is not None:
                return
            # MongoClient is thread-safe and manages internal pooling.
            self._app_client = MongoClient(self._app_mongo_uri, connect=True)

    def close(self) -> None:
        """Close app and target Mongo clients."""
        with self._lock:
            if self._app_client is not None:
                try:
                    self._app_client.close()
                except Exception:
                    logger.exception("Error closing app MongoClient")
                self._app_client = None

            for instance_id, client in list(self._targets.items()):
                try:
                    client.close()
                except Exception:
                    logger.exception("Error closing target MongoClient for instanceId=%s", instance_id)
                self._targets.pop(instance_id, None)

    def app_db(self) -> Database:
        """Return the perfmon database handle."""
        if self._app_client is None:
            self.connect_app()
        assert self._app_client is not None
        return self._app_client[APP_DB_NAME]

    def collections(self) -> MongoCollections:
        """Return app collections."""
        db = self.app_db()
        return MongoCollections(
            instances=db["instances"],
            metrics_samples=db["metrics_samples"],
            alerts=db["alerts"],
            recommendations=db["recommendations"],
        )

    def init_indexes(self) -> None:
        """Create minimal required indexes (idempotent)."""
        cols = self.collections()
        # metrics_samples on {instanceId:1, ts:-1}
        cols.metrics_samples.create_index([("instanceId", ASCENDING), ("ts", DESCENDING)], name="idx_instance_ts")
        # alerts on {instanceId:1, ts:-1}
        cols.alerts.create_index([("instanceId", ASCENDING), ("ts", DESCENDING)], name="idx_alerts_instance_ts")
        # instances unique by id for stable lookups
        cols.instances.create_index([("id", ASCENDING)], unique=True, name="idx_instances_id")

    def target_client(self, instance_id: str, uri: str) -> MongoClient:
        """Get (or create) a cached MongoClient for a monitored instance."""
        with self._lock:
            existing = self._targets.get(instance_id)
            if existing is not None:
                return existing
            client = MongoClient(uri, connect=True)
            self._targets[instance_id] = client
            return client
