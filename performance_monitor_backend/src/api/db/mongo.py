from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import RLock
from typing import Dict, Optional

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)


APP_DB_NAME = "perfmon"


@dataclass(frozen=True)
class MongoCollections:
    """Convenience wrapper for app collections."""

    instances: Collection
    metrics_samples: Collection
    metrics_rollups: Collection

    # Legacy/stub collection used by earlier UI wiring (kept intact).
    alerts: Collection

    # New alerts engine collections.
    alert_rules: Collection
    alert_events: Collection

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

    # PUBLIC_INTERFACE
    def ping(self, timeout_ms: int = 1500) -> bool:
        """
        Ping the configured MongoDB to validate connectivity.

        This is used by startup validation and the connectivity-check endpoint.
        """
        try:
            if self._app_client is None:
                # Ensure client exists before pinging
                self.connect_app()
            assert self._app_client is not None
            self._app_client.admin.command("ping", maxTimeMS=int(max(250, timeout_ms)))
            return True
        except PyMongoError:
            logger.exception("Mongo ping failed (PyMongoError)")
            return False
        except Exception:
            logger.exception("Mongo ping failed (unexpected)")
            return False

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
            metrics_rollups=db["metrics_rollups"],
            alerts=db["alerts"],
            alert_rules=db["alert_rules"],
            alert_events=db["alert_events"],
            recommendations=db["recommendations"],
        )

    def init_indexes(self, *, raw_ttl_seconds: int = 0, rollup_ttl_seconds: int = 0) -> None:
        """
        Create required indexes (idempotent).

        TTL behavior:
        - raw_ttl_seconds == 0 disables TTL index creation on metrics_samples.ts
        - rollup_ttl_seconds == 0 disables TTL index creation on metrics_rollups.bucket

        Note: MongoDB TTL cleanup is performed by MongoDB's internal TTL monitor and is not immediate.
        """
        cols = self.collections()

        # ---- Metrics samples (raw) ----
        # Common query: instance + time range.
        cols.metrics_samples.create_index([("instanceId", ASCENDING), ("ts", DESCENDING)], name="idx_instance_ts")

        # TTL index: on ts (Date). Must be single-field index.
        if int(raw_ttl_seconds) > 0:
            cols.metrics_samples.create_index(
                [("ts", ASCENDING)],
                name="ttl_metrics_samples_ts",
                expireAfterSeconds=int(raw_ttl_seconds),
            )

        # ---- Metrics rollups ----
        # Common query: instance + bucket range.
        cols.metrics_rollups.create_index([("instanceId", ASCENDING), ("bucket", DESCENDING)], name="idx_rollups_instance_bucket")
        # Optional helpful index for per-metric rollup scans/aggregations.
        cols.metrics_rollups.create_index([("instanceId", ASCENDING), ("metric", ASCENDING), ("bucket", DESCENDING)], name="idx_rollups_instance_metric_bucket")

        if int(rollup_ttl_seconds) > 0:
            cols.metrics_rollups.create_index(
                [("bucket", ASCENDING)],
                name="ttl_metrics_rollups_bucket",
                expireAfterSeconds=int(rollup_ttl_seconds),
            )

        # ---- Legacy alerts collection ----
        cols.alerts.create_index([("instanceId", ASCENDING), ("ts", DESCENDING)], name="idx_alerts_instance_ts")

        # ---- Instances ----
        cols.instances.create_index([("id", ASCENDING)], unique=True, name="idx_instances_id")

        # ---- Alert rules ----
        cols.alert_rules.create_index([("enabled", ASCENDING)], name="idx_alert_rules_enabled")
        cols.alert_rules.create_index([("type", ASCENDING)], name="idx_alert_rules_type")
        cols.alert_rules.create_index([("instanceScope", ASCENDING)], name="idx_alert_rules_instanceScope")
        cols.alert_rules.create_index([("createdAt", DESCENDING)], name="idx_alert_rules_createdAt_desc")

        # ---- Alert events ----
        cols.alert_events.create_index([("instanceId", ASCENDING)], name="idx_alert_events_instance")
        cols.alert_events.create_index([("ruleId", ASCENDING)], name="idx_alert_events_rule")
        cols.alert_events.create_index([("status", ASCENDING)], name="idx_alert_events_status")
        cols.alert_events.create_index([("createdAt", DESCENDING)], name="idx_alert_events_createdAt_desc")
        cols.alert_events.create_index(
            [("instanceId", ASCENDING), ("ruleId", ASCENDING), ("createdAt", DESCENDING)],
            name="idx_alert_events_instance_rule_createdAt_desc",
        )

        # ---- Recommendations ----
        cols.recommendations.create_index([("instanceId", ASCENDING)], name="idx_recs_instance")
        cols.recommendations.create_index([("createdAt", DESCENDING)], name="idx_recs_createdAt_desc")
        cols.recommendations.create_index([("status", ASCENDING)], name="idx_recs_status")

    def target_client(self, instance_id: str, uri: str) -> MongoClient:
        """Get (or create) a cached MongoClient for a monitored instance."""
        with self._lock:
            existing = self._targets.get(instance_id)
            if existing is not None:
                return existing
            client = MongoClient(uri, connect=True)
            self._targets[instance_id] = client
            return client
