"""ATLAS-DRIFT-001: sealed-result-only, race-grain River ADWIN monitor.

This is a research signal, NOT a certified prospective evaluation and NEVER
triggers model promotion or a database write. Input stays in local memory;
returned reports contain aggregate statistics only, not runner-level data.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Iterable

TARGETS = ("win", "top2", "top3")


def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field}: explicit timestamp with timezone required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field}: invalid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field}: timezone is required")
    return parsed


def _value(row: dict, key: str) -> float:
    raw = row.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{key}: missing/non-numeric")
    val = float(raw)
    if not math.isfinite(val) or not 0 <= val <= 1:
        raise ValueError(f"{key}: probability out of range")
    return val


def _validate(row: Any) -> tuple:
    if not isinstance(row, dict):
        raise ValueError("record must be an object")
    race_id, runner_id = row.get("race_id"), row.get("runner_id")
    if not isinstance(race_id, str) or not race_id:
        raise ValueError("race_id required")
    if not isinstance(runner_id, str) or not runner_id:
        raise ValueError("runner_id required")
    n = row.get("expected_runners")
    if type(n) is not int or not 1 <= n <= 30:
        raise ValueError("expected_runners must be an integer in [1,30]")
    captured = _time(row.get("prediction_at"), "prediction_at")
    scheduled = _time(row.get("race_start_at"), "race_start_at")
    verified = _time(row.get("result_verified_at"), "result_verified_at")
    if not captured < scheduled <= verified:
        raise ValueError("prediction/result temporal boundary violated")
    if row.get("result_finality") != "OFFICIAL":
        raise ValueError("official final outcome required")
    p = [_value(row, "p_" + t) for t in TARGETS]
    ys = []
    for t in TARGETS:
        y = row.get("label_" + t)
        if type(y) is not int or y not in (0, 1):
            raise ValueError("incomplete/invalid outcome label: " + t)
        ys.append(y)
    if not p[0] <= p[1] <= p[2] or not ys[0] <= ys[1] <= ys[2]:
        raise ValueError("win/top2/top3 monotonicity violated")
    return race_id, runner_id, n, captured, scheduled, verified, p, ys


def scan(
    rows: Iterable[dict],
    *,
    min_races: int = 64,
    delta: float = 0.002,
    detector_factory: Callable[..., Any] | None = None,
) -> dict:
    """Compute per-race Brier streams. No partial or invalid race is used."""
    if type(min_races) is not int or min_races < 2:
        raise ValueError("min_races must be >=2")
    if not isinstance(delta, (int, float)) or not 0 < delta < 1:
        raise ValueError("ADWIN delta must be between zero and one")
    if detector_factory is None:
        try:
            from river.drift import ADWIN
        except ImportError:
            return {
                "status": "DEPENDENCY_MISSING", "package": "river",
                "certified": False, "production_approved": False,
                "model_promoted": False,
            }
        detector_factory = ADWIN

    groups: dict[str, list[tuple]] = defaultdict(list)
    observed_keys: set[tuple[str, str]] = set()
    for row in rows:
        valid = _validate(row)
        key = valid[0], valid[1]
        if key in observed_keys:
            raise ValueError("duplicate race/runner pair")
        observed_keys.add(key)
        groups[valid[0]].append(valid)

    races: list[tuple[datetime, str, dict[str, float]]] = []
    for race_id, items in groups.items():
        n = items[0][2]
        race_start = items[0][4]
        if any(item[2] != n or item[4] != race_start for item in items):
            raise ValueError("race expected count/start mismatch")
        if len(items) != n:
            raise ValueError("race contains incomplete runner roster")
        losses = {
            target: sum(
                (item[6][idx] - item[7][idx]) ** 2 for item in items
            ) / n
            for idx, target in enumerate(TARGETS)
        }
        races.append((race_start, race_id, losses))
    races.sort(key=lambda item: (item[0], item[1]))

    if len(races) < min_races:
        return {
            "status": "INSUFFICIENT_RACES",
            "races": len(races),
            "required_races": min_races,
            "certified": False,
            "production_approved": False, "model_promoted": False,
        }

    monitors = {target: detector_factory(delta=delta) for target in TARGETS}
    changes = []
    totals = {t: 0.0 for t in TARGETS}
    for pos, (race_time, _, losses) in enumerate(races, 1):
        for target in TARGETS:
            loss = losses[target]
            totals[target] += loss
            detector = monitors[target]
            detector.update(loss)
            # River emits an observational alert; it never approves a model.
            if bool(detector.drift_detected):
                changes.append({
                    "race_index": pos,
                    "race_start_at": race_time.isoformat(),
                    "target": target,
                    "signal": "ADWIN_MEAN_BRIER_SHIFT",
                })
    return {
        "status": "DRIFT_SIGNAL" if changes else "NO_DRIFT_SIGNAL",
        "races": len(races),
        "brier_by_race_mean": {
            t: round(totals[t] / len(races), 8) for t in TARGETS
        },
        "changes": changes,
        "method": "RIVER_ADWIN_ON_RACE_MEAN_BRIER",
        "uses_only_official_postrace_labels": True,
        "certified": False,
        "production_approved": False,
        "model_promoted": False,
        "training_triggered": False,
    }
