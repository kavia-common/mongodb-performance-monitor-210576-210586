from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.api.schemas.common import utc_now
from src.api.state import AppState

logger = logging.getLogger(__name__)


async def _run_in_thread(func, *args, **kwargs):
    """Run blocking pymongo calls in a worker thread."""
    return await asyncio.to_thread(func, *args, **kwargs)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _ops_sum(ops_per_sec: Dict[str, float]) -> float:
    return float(sum(_safe_float(v, 0.0) for v in (ops_per_sec or {}).values()))


def _select_instances_for_rule(inst_docs: List[dict], rule: dict) -> List[str]:
    scope = rule.get("instanceScope")
    if scope:
        # Rule scoped to a specific instanceId
        return [scope]
    # Global => apply to all active instances
    ids: List[str] = []
    for inst in inst_docs:
        iid = inst.get("id")
        if iid:
            ids.append(iid)
    return ids


async def _get_active_instance_docs(state: AppState) -> List[dict]:
    cols = state.mongo.collections()
    return await _run_in_thread(
        lambda: list(
            cols.instances.find(
                {"$or": [{"enabled": True}, {"isActive": True}]},
                projection={"_id": 0},
            )
        )
    )


async def _load_enabled_rules(state: AppState) -> List[dict]:
    cols = state.mongo.collections()
    return await _run_in_thread(lambda: list(cols.alert_rules.find({"enabled": True})))


async def _fetch_samples_in_window(
    state: AppState,
    instance_id: str,
    window_start: datetime,
    window_end: datetime,
) -> List[dict]:
    cols = state.mongo.collections()
    return await _run_in_thread(
        lambda: list(
            cols.metrics_samples.find(
                {"instanceId": instance_id, "ts": {"$gte": window_start, "$lte": window_end}},
                projection={"_id": 0},
            ).sort("ts", 1)
        )
    )


def _compute_signal(rule: dict, samples: List[dict]) -> Tuple[Optional[float], str]:
    """
    Compute a numeric signal value and unit-ish label for a rule based on samples.

    Returns (value, label). If not enough data, value=None.
    """
    rtype = rule.get("type")
    if not samples:
        return None, "no_data"

    if rtype == "high_connections":
        # Use max connections over window.
        vals = [_safe_float(s.get("connections"), 0.0) for s in samples]
        return (max(vals) if vals else None), "connections"

    if rtype == "slow_operations_rate":
        # Use average total ops/sec over window.
        vals = [_ops_sum(s.get("opsPerSec") or {}) for s in samples]
        return (sum(vals) / max(1, len(vals))), "ops_per_sec"

    if rtype == "high_ops_latency":
        # Not yet sampled; support forward-compat by looking for avgQueryMs.
        vals = [_safe_float(s.get("avgQueryMs"), 0.0) for s in samples if s.get("avgQueryMs") is not None]
        if not vals:
            return None, "avg_query_ms_missing"
        return (sum(vals) / max(1, len(vals))), "avg_query_ms"

    return None, "unknown_rule_type"


def _should_trigger(value: Optional[float], threshold: float) -> Optional[bool]:
    if value is None:
        return None
    return bool(value > threshold)


async def _latest_event_for_pair(state: AppState, instance_id: str, rule_id: str) -> Optional[dict]:
    cols = state.mongo.collections()
    return await _run_in_thread(
        lambda: cols.alert_events.find_one(
            {"instanceId": instance_id, "ruleId": rule_id},
            sort=[("createdAt", -1)],
        )
    )


def _within_cooldown(now: datetime, last_event: dict, cooldown_sec: int) -> bool:
    if cooldown_sec <= 0 or not last_event:
        return False
    ts = last_event.get("createdAt")
    if not isinstance(ts, datetime):
        return False
    return (now - ts).total_seconds() < float(cooldown_sec)


async def _insert_event(state: AppState, doc: dict) -> None:
    cols = state.mongo.collections()
    await _run_in_thread(cols.alert_events.insert_one, doc)


def _event_title(rule: dict, instance_id: str, is_trigger: bool) -> str:
    prefix = "Triggered" if is_trigger else "Resolved"
    return f"{prefix}: {rule.get('name', rule.get('type', 'rule'))} ({instance_id})"


def _event_message(rule: dict, instance_id: str, is_trigger: bool, value: Optional[float], label: str) -> str:
    thr = rule.get("threshold")
    win = int(rule.get("windowSec", 60))
    base = f"ruleType={rule.get('type')} windowSec={win} threshold={thr}"
    if value is None:
        return f"{'Trigger' if is_trigger else 'Resolve'} evaluation had insufficient data ({label}); {base}"
    return f"{'Trigger' if is_trigger else 'Resolve'}: value={value:.3f} ({label}) {base}"


async def _evaluate_one_rule_instance(
    state: AppState,
    rule: dict,
    rule_id: str,
    instance_id: str,
    now: datetime,
    cooldown_sec: int,
) -> None:
    window_sec = int(rule.get("windowSec", 60))
    window_start = now - timedelta(seconds=max(1, window_sec))
    samples = await _fetch_samples_in_window(state, instance_id, window_start, now)

    value, label = _compute_signal(rule, samples)
    threshold = float(rule.get("threshold", 0.0))
    should = _should_trigger(value, threshold)

    # If we don't have enough data to decide, do nothing.
    if should is None:
        return

    last = await _latest_event_for_pair(state, instance_id, rule_id)
    last_status = (last or {}).get("status")  # "triggered"|"ok"
    desired_status = "triggered" if should else "ok"

    # No state change => no event (dedup).
    if last_status == desired_status:
        return

    # Cooldown: avoid flip-flop noise (applied to any state change).
    if last and _within_cooldown(now, last, cooldown_sec):
        return

    is_trigger = desired_status == "triggered"
    event_doc = {
        "ruleId": rule_id,
        "instanceId": instance_id,
        "eventType": "triggered" if is_trigger else "resolved",
        "status": desired_status,
        "severity": rule.get("severity", "warning"),
        "title": _event_title(rule, instance_id, is_trigger),
        "message": _event_message(rule, instance_id, is_trigger, value, label),
        "value": value,
        "threshold": threshold,
        "windowSec": window_sec,
        "createdAt": now,
        "meta": {
            "signalLabel": label,
            "samplesCount": len(samples),
        },
    }
    await _insert_event(state, event_doc)


async def _evaluation_tick(state: AppState) -> None:
    now = utc_now()
    cooldown = int(state.config.alert_event_cooldown_sec)

    inst_docs = await _get_active_instance_docs(state)
    rules = await _load_enabled_rules(state)

    for rule in rules:
        rule_id = str(rule.get("_id") or "")
        if not rule_id:
            continue
        instance_ids = _select_instances_for_rule(inst_docs, rule)
        for instance_id in instance_ids:
            try:
                await _evaluate_one_rule_instance(state, rule, rule_id, instance_id, now, cooldown)
            except Exception:
                logger.exception("Alerts eval failed for ruleId=%s instanceId=%s", rule_id, instance_id)


# PUBLIC_INTERFACE
async def alerts_evaluator_loop(state: AppState, shutdown_event: asyncio.Event) -> None:
    """
    Background loop that evaluates alert rules against persisted metrics samples.

    - Reads enabled rules from perfmon.alert_rules
    - Uses metrics_samples in the last windowSec to compute a signal for each (rule, instance)
    - Writes events to perfmon.alert_events only on state change (triggered/resolved)
    - Applies a cooldown to avoid noisy flapping

    This loop is designed to run at a cadence similar to metrics sampling.
    """
    interval = max(1, int(state.config.alert_eval_interval_sec))
    logger.info(
        "Alerts evaluator started (interval=%ss, cooldown=%ss)", interval, state.config.alert_event_cooldown_sec
    )

    while not shutdown_event.is_set():
        tick_started = datetime.now(timezone.utc)
        try:
            await _evaluation_tick(state)
        except Exception:
            logger.exception("Alerts evaluator tick failed")

        elapsed = (datetime.now(timezone.utc) - tick_started).total_seconds()
        sleep_for = max(0.1, interval - elapsed)
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=sleep_for)
        except asyncio.TimeoutError:
            pass

    logger.info("Alerts evaluator stopped")
