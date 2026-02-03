from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from pymongo.errors import PyMongoError

from src.api.schemas.common import utc_now
from src.api.state import AppState

logger = logging.getLogger(__name__)


def _extract_server_status_fields(server_status: Dict[str, Any]) -> Dict[str, Any]:
    connections_current = int(((server_status.get("connections") or {}).get("current")) or 0)
    opc = server_status.get("opcounters") or {}
    mem = server_status.get("mem") or {}

    return {
        "connections": connections_current,
        "opcounters": {
            "query": int(opc.get("query") or 0),
            "insert": int(opc.get("insert") or 0),
            "update": int(opc.get("update") or 0),
            "delete": int(opc.get("delete") or 0),
        },
        # mongod reports resident in MB
        "memResidentMB": float(mem.get("resident") or 0.0),
    }


def _diff_ops_per_sec(prev: Optional[dict], cur: dict, interval_sec: int) -> Dict[str, float]:
    if not prev:
        return {"query": 0.0, "insert": 0.0, "update": 0.0, "delete": 0.0}

    prev_ops = prev.get("opcounters") or {}
    cur_ops = cur.get("opcounters") or {}

    def rate(k: str) -> float:
        try:
            return max(0.0, (float(cur_ops.get(k, 0)) - float(prev_ops.get(k, 0))) / max(1.0, float(interval_sec)))
        except Exception:
            return 0.0

    return {k: rate(k) for k in ("query", "insert", "update", "delete")}


async def _run_in_thread(func, *args, **kwargs):
    """Run blocking pymongo calls in a worker thread."""
    return await asyncio.to_thread(func, *args, **kwargs)


async def _fetch_server_status(mongo_client, instance_id: str) -> Optional[Dict[str, Any]]:
    try:
        return await _run_in_thread(mongo_client.admin.command, "serverStatus")
    except PyMongoError:
        logger.exception("Sampler serverStatus failed for instanceId=%s", instance_id)
        return None
    except Exception:
        logger.exception("Sampler unexpected error for instanceId=%s", instance_id)
        return None


async def _upsert_sample(state: AppState, sample_doc: dict) -> None:
    cols = state.mongo.collections()
    await _run_in_thread(cols.metrics_samples.insert_one, sample_doc)


async def _apply_retention(state: AppState) -> None:
    cols = state.mongo.collections()
    cutoff = utc_now() - timedelta(days=state.config.metrics_retention_days)
    try:
        await _run_in_thread(cols.metrics_samples.delete_many, {"ts": {"$lt": cutoff}})
    except Exception:
        logger.exception("Retention cleanup failed")


# PUBLIC_INTERFACE
async def sampler_loop(state: AppState, shutdown_event: asyncio.Event) -> None:
    """
    Background loop that periodically samples metrics from each active instance.

    For each active instance, it reads adminCommand serverStatus and stores a document in metrics_samples:
      {instanceId, ts, connections, opcounters, memResidentMB, opsPerSec:{...}}

    Errors are logged and non-fatal; failing instances are skipped until next tick.
    """
    interval = int(state.config.metrics_sampling_interval_sec)
    interval = max(1, interval)

    last_counters: Dict[str, dict] = {}

    logger.info("Metrics sampler started (interval=%ss, retention=%sd)", interval, state.config.metrics_retention_days)

    while not shutdown_event.is_set():
        tick_started = datetime.now(timezone.utc)
        try:
            cols = state.mongo.collections()
            # Active instances: enabled/isActive
            inst_docs = await _run_in_thread(
                lambda: list(
                    cols.instances.find(
                        {"$or": [{"enabled": True}, {"isActive": True}]},
                        projection={"_id": 0},
                    )
                )
            )

            for inst in inst_docs:
                instance_id = inst.get("id")
                uri = inst.get("uri")
                if not instance_id or not uri:
                    continue

                try:
                    target_client = state.mongo.target_client(instance_id, uri)
                except Exception:
                    logger.exception("Failed to create target client for instanceId=%s", instance_id)
                    continue

                ss = await _fetch_server_status(target_client, instance_id)
                if not ss:
                    continue

                cur = _extract_server_status_fields(ss)
                prev = last_counters.get(instance_id)
                ops_per_sec = _diff_ops_per_sec(prev, cur, interval)

                last_counters[instance_id] = cur

                sample_doc = {
                    "instanceId": instance_id,
                    "ts": utc_now(),
                    "connections": cur["connections"],
                    "opcounters": cur["opcounters"],
                    "memResidentMB": cur["memResidentMB"],
                    "opsPerSec": ops_per_sec,
                    # Placeholders for future improvements:
                    # - "slowOpsPerMin" (needs profiler/system.profile)
                    # - "avgQueryMs" (needs profiler/log parsing)
                    # - "cpuPct" (host/container metrics)
                }

                await _upsert_sample(state, sample_doc)

            await _apply_retention(state)

        except Exception:
            logger.exception("Sampler tick failed")

        # Sleep remaining interval (avoid drift, but keep simple)
        elapsed = (datetime.now(timezone.utc) - tick_started).total_seconds()
        sleep_for = max(0.1, interval - elapsed)
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=sleep_for)
        except asyncio.TimeoutError:
            pass

    logger.info("Metrics sampler stopped")
