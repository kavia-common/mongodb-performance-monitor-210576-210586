from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """Parse an int env var with a default."""
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return int(default)


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a bool env var (true/false/1/0/yes/no/on/off)."""
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    val = raw.strip().lower()
    if val in ("1", "true", "yes", "y", "on"):
        return True
    if val in ("0", "false", "no", "n", "off"):
        return False
    return bool(default)


def _clamp_int(v: int, lo: int, hi: int) -> int:
    """Clamp integer to [lo, hi]."""
    return max(lo, min(hi, int(v)))


@dataclass(frozen=True)
class BackendConfig:
    """Runtime configuration loaded from env and optional workspace files."""

    mongo_uri: str
    metrics_sampling_interval_sec: int
    metrics_retention_days: int

    # Raw metrics TTL (Mongo TTL index on metrics_samples.ts).
    metrics_raw_ttl_seconds: int

    # Rollup/compaction controls.
    metrics_rollup_enabled: bool
    metrics_rollup_bucket_seconds: int
    metrics_rollup_ttl_seconds: int
    metrics_rollup_compaction_interval_sec: int

    # Threshold to switch reads to rollups for large timeframes (keeps API contract unchanged).
    metrics_rollup_query_threshold_seconds: int

    # Alerts engine tuning
    alert_eval_interval_sec: int
    alert_event_cooldown_sec: int

    # Recommendations engine tuning
    recs_default_ttl_days: int
    recs_max_return: int

    # Diagnostics: how mongo_uri was resolved
    mongo_uri_source: str
    mongo_db_connection_path: Optional[str]


def _db_connection_candidate_path() -> Path:
    """
    Return the expected absolute path to mongodb_instance/db_connection.txt.

    Note: backend and mongodb_instance are sibling workspaces under the same repo root.
    """
    # repo_root/.../performance_monitor_backend/src/api/config.py -> repo_root
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "mongodb-performance-monitor-210576-210587" / "mongodb_instance" / "db_connection.txt"


def _parse_mongo_uri_from_db_connection_text(text: str) -> Optional[str]:
    """
    Parse a MongoDB URI from db_connection.txt contents.

    Expected format (per platform convention):
      - 'mongosh mongodb://...'
      - or a raw 'mongodb://...' URI on the first line
      - or any line containing mongodb://... (we extract first match)
    """
    first_line = (text.splitlines()[0] if text else "").strip()
    if not first_line:
        return None

    if first_line.startswith("mongosh "):
        maybe_uri = first_line[len("mongosh ") :].strip()
        return maybe_uri or None

    m = re.search(r"(mongodb(?:\+srv)?://\S+)", first_line)
    return m.group(1) if m else None


def _read_mongo_uri_from_db_connection_file() -> Tuple[Optional[str], Optional[str]]:
    """
    Attempt to read a MongoDB URI from mongodb_instance/db_connection.txt.

    Returns:
      (uri, path_str) where path_str is included only when the file existed/read was attempted.
    """
    candidate = _db_connection_candidate_path()
    if not candidate.exists():
        return None, None

    try:
        raw = candidate.read_text(encoding="utf-8")
        uri = _parse_mongo_uri_from_db_connection_text(raw)
        return uri, str(candidate)
    except Exception:
        # If the file exists but can't be read/parsed, we still return the path for diagnostics.
        logger.exception("Failed reading/parsing mongodb db_connection.txt at %s", str(candidate))
        return None, str(candidate)


def _sanitize_mongo_uri_for_logs(uri: str) -> str:
    """Mask credentials in mongo URIs to avoid leaking secrets in logs."""
    # mongodb://user:pass@host -> mongodb://user:***@host
    return re.sub(r"(mongodb(?:\+srv)?://)([^:@/]+):([^@/]+)@", r"\1\2:***@", uri)


# PUBLIC_INTERFACE
def load_config() -> BackendConfig:
    """Load BackendConfig from db_connection.txt (preferred) and env vars (fallback)."""
    file_uri, file_path = _read_mongo_uri_from_db_connection_file()
    env_uri = os.getenv("BACKEND_MONGO_URI")

    mongo_uri_source = "mongodb_instance/db_connection.txt" if file_uri else ("BACKEND_MONGO_URI" if env_uri else "unset")
    mongo_uri = file_uri or env_uri

    if not mongo_uri:
        # Keep failure explicit and actionable; startup will log the exception.
        raise RuntimeError(
            "Mongo URI not configured. Provide BACKEND_MONGO_URI or ensure mongodb_instance/db_connection.txt is readable."
        )

    # Basic validation: pymongo will do deep validation on connect, but catch common misconfig early.
    if not re.match(r"^mongodb(\+srv)?://", mongo_uri):
        raise RuntimeError(
            f"Mongo URI appears invalid (must start with mongodb:// or mongodb+srv://). source={mongo_uri_source}"
        )

    logger.info(
        "Resolved backend Mongo URI source=%s path=%s uri=%s",
        mongo_uri_source,
        file_path,
        _sanitize_mongo_uri_for_logs(mongo_uri),
    )

    sampling_interval = _env_int("METRICS_SAMPLING_INTERVAL_SEC", 5)
    retention_days = _env_int("METRICS_RETENTION_DAYS", 7)

    # Raw TTL defaults to 7 days unless overridden; 0 disables TTL index.
    metrics_raw_ttl_seconds = _env_int("METRICS_RAW_TTL_SECONDS", 7 * 24 * 3600)

    metrics_rollup_enabled = _env_bool("METRICS_ROLLUP_ENABLED", False)
    metrics_rollup_bucket_seconds = _env_int("METRICS_ROLLUP_BUCKET_SECONDS", 60)
    metrics_rollup_ttl_seconds = _env_int("METRICS_ROLLUP_TTL_SECONDS", 30 * 24 * 3600)
    metrics_rollup_compaction_interval_sec = _env_int("METRICS_ROLLUP_COMPACTION_INTERVAL_SEC", 30)

    # If timeframe >= threshold, prefer rollups (when enabled).
    metrics_rollup_query_threshold_seconds = _env_int("METRICS_ROLLUP_QUERY_THRESHOLD_SECONDS", 6 * 3600)

    alert_eval_interval = _env_int("ALERT_EVAL_INTERVAL_SEC", 5)
    alert_event_cooldown = _env_int("ALERT_EVENT_COOLDOWN_SEC", 60)

    recs_default_ttl_days = _env_int("RECS_DEFAULT_TTL_DAYS", 14)
    recs_max_return = _env_int("RECS_MAX_RETURN", 50)

    sampling_interval = max(1, sampling_interval)
    retention_days = max(1, retention_days)

    # TTL seconds: allow 0 to mean "disabled"; otherwise enforce sane bounds.
    if metrics_raw_ttl_seconds != 0:
        metrics_raw_ttl_seconds = _clamp_int(metrics_raw_ttl_seconds, 60, 365 * 24 * 3600)

    # Rollups
    metrics_rollup_bucket_seconds = _clamp_int(metrics_rollup_bucket_seconds, 10, 3600)
    if metrics_rollup_ttl_seconds != 0:
        metrics_rollup_ttl_seconds = _clamp_int(metrics_rollup_ttl_seconds, metrics_rollup_bucket_seconds, 3650 * 24 * 3600)
    metrics_rollup_compaction_interval_sec = _clamp_int(metrics_rollup_compaction_interval_sec, 5, 3600)
    metrics_rollup_query_threshold_seconds = _clamp_int(metrics_rollup_query_threshold_seconds, 60, 365 * 24 * 3600)

    # Alerts: keep evaluation reasonably frequent, cooldown not too small.
    alert_eval_interval = max(1, alert_eval_interval)
    alert_event_cooldown = max(0, alert_event_cooldown)

    recs_default_ttl_days = max(1, recs_default_ttl_days)
    recs_max_return = max(1, min(500, recs_max_return))

    return BackendConfig(
        mongo_uri=mongo_uri,
        metrics_sampling_interval_sec=sampling_interval,
        metrics_retention_days=retention_days,
        metrics_raw_ttl_seconds=metrics_raw_ttl_seconds,
        metrics_rollup_enabled=metrics_rollup_enabled,
        metrics_rollup_bucket_seconds=metrics_rollup_bucket_seconds,
        metrics_rollup_ttl_seconds=metrics_rollup_ttl_seconds,
        metrics_rollup_compaction_interval_sec=metrics_rollup_compaction_interval_sec,
        metrics_rollup_query_threshold_seconds=metrics_rollup_query_threshold_seconds,
        alert_eval_interval_sec=alert_eval_interval,
        alert_event_cooldown_sec=alert_event_cooldown,
        recs_default_ttl_days=recs_default_ttl_days,
        recs_max_return=recs_max_return,
        mongo_uri_source=mongo_uri_source,
        mongo_db_connection_path=file_path,
    )
