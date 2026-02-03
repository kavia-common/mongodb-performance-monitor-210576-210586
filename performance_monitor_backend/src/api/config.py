from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class BackendConfig:
    """Runtime configuration loaded from env and optional workspace files."""

    mongo_uri: str
    metrics_sampling_interval_sec: int
    metrics_retention_days: int

    # Recommendations engine tuning
    recs_default_ttl_days: int
    recs_max_return: int


def _read_mongo_uri_from_db_connection_file() -> Optional[str]:
    """
    Attempt to read a MongoDB URI from the mongodb_instance container's db_connection.txt.

    Expected format (per platform convention):
      - 'mongosh mongodb://...'
      - or a raw 'mongodb://...' URI on the first line
    """
    # The backend and mongodb_instance are sibling workspaces under the same base directory.
    # Using an absolute-ish relative walk from this file keeps it robust to cwd.
    # repo_root/.../performance_monitor_backend/src/api/config.py -> repo_root
    repo_root = Path(__file__).resolve().parents[4]

    candidate = repo_root / "mongodb-performance-monitor-210576-210587" / "mongodb_instance" / "db_connection.txt"
    if not candidate.exists():
        return None

    try:
        first_line = candidate.read_text(encoding="utf-8").splitlines()[0].strip()
    except Exception:
        return None

    if not first_line:
        return None

    # If line starts with "mongosh ", extract the following URI
    if first_line.startswith("mongosh "):
        maybe_uri = first_line[len("mongosh ") :].strip()
        return maybe_uri or None

    # Otherwise, search for a mongodb URI within the line.
    m = re.search(r"(mongodb(?:\+srv)?://\S+)", first_line)
    return m.group(1) if m else None


# PUBLIC_INTERFACE
def load_config() -> BackendConfig:
    """Load BackendConfig from db_connection.txt (if available) and env vars."""
    file_uri = _read_mongo_uri_from_db_connection_file()
    env_uri = os.getenv("BACKEND_MONGO_URI")

    mongo_uri = file_uri or env_uri
    if not mongo_uri:
        # Keep failure explicit and actionable; startup will log the exception.
        raise RuntimeError(
            "Mongo URI not configured. Provide BACKEND_MONGO_URI or ensure mongodb_instance/db_connection.txt is readable."
        )

    sampling_interval = int(os.getenv("METRICS_SAMPLING_INTERVAL_SEC", "5"))
    retention_days = int(os.getenv("METRICS_RETENTION_DAYS", "7"))

    recs_default_ttl_days = int(os.getenv("RECS_DEFAULT_TTL_DAYS", "14"))
    recs_max_return = int(os.getenv("RECS_MAX_RETURN", "50"))

    sampling_interval = max(1, sampling_interval)
    retention_days = max(1, retention_days)

    recs_default_ttl_days = max(1, recs_default_ttl_days)
    recs_max_return = max(1, min(500, recs_max_return))

    return BackendConfig(
        mongo_uri=mongo_uri,
        metrics_sampling_interval_sec=sampling_interval,
        metrics_retention_days=retention_days,
        recs_default_ttl_days=recs_default_ttl_days,
        recs_max_return=recs_max_return,
    )
