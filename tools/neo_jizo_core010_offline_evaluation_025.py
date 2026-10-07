"""Offline 3-target NEO JIZO evaluation from CORE-010 (no database).

Input: existing CORE-010_calibrated_probabilities.csv, read-only.
Output: aggregate-only JSON in a TEMP directory.
No horse records, labels, original probabilities, or licensed data are copied
to GitHub or printed. Official TEST/OOS status requires matching split
provenance; absent proof is explicitly diagnostic-only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

TARGETS = ("win", "top2", "top3")
REQUIRED = {
    "race_id", "race_horse_id", "race_date", "race_scope_cd",
    "label_win", "label_top2", "label_top3",
    "p_win_cal", "p_top2_cal", "p_top3_cal",
}
SPLITS = ("TRAIN", "VALIDATION", "SELECTION", "TEST", "OOS")


def resolve_root(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("THE_JOCKEY_RESEARCH_ROOT"):
        candidates.append(Path(os.environ["THE_JOCKEY_RESEARCH_ROOT"]))
    candidates += [
        Path.home() / "Downloads" / "THE-JOCKEY-RESEARCH",
        Path.home() / "Documents" / "THE-JOCKEY-RESEARCH",
    ]
    for root in candidates:
        if (root / "CORE" / "data" / "CORE-010_calibrated_probabilities.csv").is_file():
            return root
    raise FileNotFoundError("CORE-010 CSV not found in known read-only locations")


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError, UnicodeError):
        return None
    return obj if isinstance(obj, dict) else None


def split_id(plan: dict[str, Any]) -> str:
    """Exact signature used by probability_director.split_id."""
    parts: list[str] = []
    for name in SPLITS:
        window = plan["splits"][name]
        parts += [name, str(window.get("start_date")), str(window.get("end_date"))]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def provenance(root: Path) -> tuple[dict[str, Any], list[tuple[str, date, date]]]:
    plan = read_json(root / "CORE" / "reports" / "TEMPORAL_SPLIT_plan.json")
    decision = read_json(root / "CORE" / "reports" / "CORE-010_decision.json")
    model = read_json(root / "CORE" / "reports" / "CORE-005_decision.json")
    result: dict[str, Any] = {
        "verified": False,
        "status": "DIAGNOSTIC_ONLY",
        "reason": [],
        "split_signature": None,
        "plan_status": plan.get("status") if plan else None,
        "calibration_status": decision.get("status") if decision else None,
        "model_status": model.get("status") if model else None,
    }
    if not plan or not isinstance(plan.get("splits"), dict):
        result["reason"].append("TEMPORAL_SPLIT_plan.json missing or invalid")
        return result, []
    windows: list[tuple[str, date, date]] = []
    try:
        for name in SPLITS:
            window = plan["splits"][name]
            start, end = date.fromisoformat(window["start_date"]), date.fromisoformat(window["end_date"])
            if start > end:
                raise ValueError(f"{name} start>end")
            windows.append((name, start, end))
        for index in range(1, len(windows)):
            if windows[index][1] <= windows[index - 1][2]:
                raise ValueError("overlapping or non-chronological splits")
        expected = split_id(plan)
    except (TypeError, ValueError, KeyError) as exc:
        result["reason"].append(f"invalid chronological split: {type(exc).__name__}")
        return result, []

    result["split_signature"] = expected
    if plan.get("status") not in ("PASS", "WARN"):
        result["reason"].append("temporal plan status not PASS/WARN")
    if not decision or decision.get("status") != "PASS":
        result["reason"].append("CORE-010 decision not PASS")
    elif decision.get("split_id") != expected:
        result["reason"].append("CORE-010 decision split signature mismatch")
    if not model or model.get("status") != "PASS":
        result["reason"].append("CORE-005 model decision not PASS")
    elif model.get("split_id") != expected:
        result["reason"].append("CORE-005 model split signature mismatch")

    # Passing decisions are evidence of pipeline provenance, not independent
    # certification of no leakage in the upstream feature computation.
    result["verified"] = not result["reason"]
    if result["verified"]:
        result["status"] = "HOLDOUT_CONTRACT_MATCHED"
    return result, windows


class Aggregate:
    def __init__(self) -> None:
        self.n = 0
        self.positives = [0, 0, 0]
        self.sums = [0.0, 0.0, 0.0]
        self.sq = [0.0, 0.0, 0.0]

    def add(self, labels: tuple[int, int, int], probs: tuple[float, float, float]) -> None:
        self.n += 1
        for i in range(3):
            self.positives[i] += labels[i]
            self.sums[i] += probs[i]
            self.sq[i] += (probs[i] - labels[i]) ** 2

    def result(self) -> dict[str, Any]:
        output: dict[str, Any] = {"n": self.n}
        for i, target in enumerate(TARGETS):
            n = self.n
            output[target] = {
                "positives": self.positives[i],
                "actual_rate": self.positives[i] / n if n else None,
                "mean_prediction": self.sums[i] / n if n else None,
                "calibration_gap_pp": (self.positives[i] - self.sums[i]) / n * 100 if n else None,
                "brier": self.sq[i] / n if n else None,
            }
        return output


def _value(row: dict[str, str], name: str) -> str:
    return str(row.get(name) or "").strip()


def parse(row: dict[str, str]) -> tuple[date, str, str, str, tuple[int, int, int], tuple[float, float, float]]:
    rid, horse = _value(row, "race_id"), _value(row, "race_horse_id")
    if not rid or not horse:
        raise ValueError("missing unique key")
    dt = date.fromisoformat(_value(row, "race_date")[:10])
    scope = {"1": "JRA", "2": "NAR"}.get(_value(row, "race_scope_cd"))
    if not scope:
        raise ValueError("invalid race_scope_cd")
    raw_labels = tuple(float(_value(row, f"label_{t}")) for t in TARGETS)
    if any(not math.isfinite(x) or x not in (0.0, 1.0) for x in raw_labels):
        raise ValueError("invalid target labels")
    labels = tuple(int(x) for x in raw_labels)
    if not labels[0] <= labels[1] <= labels[2]:
        raise ValueError("inconsistent outcome labels")
    probs = tuple(float(_value(row, f"p_{t}_cal")) for t in TARGETS)
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in probs):
        raise ValueError("invalid probability")
    if not probs[0] <= probs[1] <= probs[2]:
        raise ValueError("non-monotonic predicted targets")
    return dt, scope, rid, horse, labels, probs


def split_for_day(day: date, windows: list[tuple[str, date, date]]) -> str:
    for name, start, end in windows:
        if start <= day <= end:
            return name
    return "UNCLASSIFIED"


def _lift(selected: Aggregate, base: Aggregate, target_index: int) -> float | None:
    if selected.n == 0 or base.n == 0 or base.positives[target_index] == 0:
        return None
    return (selected.positives[target_index] / selected.n) / (
        base.positives[target_index] / base.n
    )


def evaluate_csv(csv_path: Path, provenance_info: dict[str, Any], windows: list[tuple[str, date, date]]) -> dict[str, Any]:
    # The only official evaluation splits. Diagnostics are never upgraded to
    # official OOS regardless of apparent accuracy.
    aggregate: dict[tuple[str, int, str, str], Aggregate] = defaultdict(Aggregate)
    leaders: dict[tuple[str, str], tuple[float, str, int, str, tuple[int, int, int], tuple[float, float, float]]] = {}
    seen: set[tuple[str, str]] = set()
    row_counts: dict[str, int] = defaultdict(int)
    invalid_types: dict[str, int] = defaultdict(int)
    total_rows = 0

    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not REQUIRED.issubset(reader.fieldnames):
            missing = sorted(REQUIRED - set(reader.fieldnames or ()))
            raise ValueError("CORE-010 missing required columns: " + ", ".join(missing))
        for raw in reader:
            total_rows += 1
            try:
                dt, scope, race, horse, labels, probs = parse(raw)
            except (ValueError, TypeError, OverflowError, KeyError) as exc:
                invalid_types[type(exc).__name__] += 1
                continue
            key = (race, horse)
            if key in seen:
                raise ValueError("duplicate race_id + race_horse_id found; refusing evaluation")
            seen.add(key)
            part = split_for_day(dt, windows)
            row_counts[part] += 1

            # Before market input or result labels can influence ranking,
            # model rank is frozen by win probability and horse ID tie break.
            if part in ("TEST", "OOS"):
                year = dt.year
                for dimensions in ((part, year, scope, "ALL"),
                                   (part, year, "ALL", "ALL"),
                                   (part, 0, scope, "ALL"),
                                   (part, 0, "ALL", "ALL")):
                    aggregate[dimensions].add(labels, probs)
                rkey = (part, race)
                current = leaders.get(rkey)
                # Tie-break deterministic by runner ID, never by popularity/outcome.
                if current is None or probs[0] > current[0] or (
                    probs[0] == current[0] and horse < current[1]
                ):
                    leaders[rkey] = (probs[0], horse, year, scope, labels, probs)

    for (part, _race), candidate in leaders.items():
        _, _, year, scope, labels, probs = candidate
        for dimensions in ((part, year, scope, "SELECTED_TOP1"),
                           (part, year, "ALL", "SELECTED_TOP1"),
                           (part, 0, scope, "SELECTED_TOP1"),
                           (part, 0, "ALL", "SELECTED_TOP1")):
            aggregate[dimensions].add(labels, probs)

    report: list[dict[str, Any]] = []
    for key in sorted(aggregate):
        part, year, scope, bucket = key
        if bucket != "ALL":
            continue
        selected_key = (part, year, scope, "SELECTED_TOP1")
        base = aggregate[key]
        selected = aggregate[selected_key]
        report.append({
            "split": part,
            "year": year if year else "ALL",
            "organizer": scope,
            "surface": "UNKNOWN_NO_TRACK_CONTEXT",
            "popularity_band": "UNKNOWN_NO_MARKET_CONTEXT",
            "base": base.result(),
            "model_top1": selected.result(),
            "top1_lift_vs_all_runners": {
                t: _lift(selected, base, i) for i, t in enumerate(TARGETS)
            },
        })

    status = ("HOLDOUT_CONTRACT_MATCHED" if provenance_info["verified"] else "DIAGNOSTIC_ONLY")
    if sum(invalid_types.values()):
        status = "PARTIAL_INVALID_ROWS"
    if not any(item["base"]["n"] and item["split"] == "OOS" for item in report):
        status = "BLOCKED_NO_OOS"

    return {
        "mission": "NEO-JIZO-DIRT-EDGE-025",
        "probe": "CORE010-OFFLINE-001",
        "status": status,
        "assessment_scope": "ALL_SURFACES; NO_P7_9_OR_DIRT_SLICE",
        "evaluation_type": "historical retrospective holdout diagnostics; not certified live pre-race predictions",
        "provenance": provenance_info,
        "input": {"size_bytes": csv_path.stat().st_size},
        "total_rows_read": total_rows,
        "rows_by_split": dict(sorted(row_counts.items())),
        "invalid_row_types": dict(sorted(invalid_types.items())),
        "races_with_top1": len(leaders),
        "by_split_year_scope": report,
        "safety": {
            "database_accessed": False,
            "database_modified": False,
            "source_csv_modified": False,
            "horse_rows_output": False,
            "market_data_used_in_ranking": False,
        },
        "next_gate": "Need true dirt/odds/popularity context for BaoZ P7-9 comparison",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate CORE-010 offline, without PostgreSQL")
    parser.add_argument("--root")
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        root = resolve_root(args.root)
        source = root / "CORE" / "data" / "CORE-010_calibrated_probabilities.csv"
        meta, windows = provenance(root)
        result = evaluate_csv(source, meta, windows)
    except (ValueError, OSError, KeyError) as exc:
        print(f"OFFLINE_EVALUATION_BLOCKED: {type(exc).__name__}: {exc}")
        return 2

    output = (Path(args.output) if args.output else
              Path(os.environ.get("TEMP", str(Path.home())))
              / "JIZO" / "NEO-JIZO-DIRT-EDGE-025" / "core010_offline_evaluation.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                      encoding="utf-8")

    print("=" * 65)
    print(" NEO JIZO 025 - CORE-010 OFFLINE EVALUATION")
    print("=" * 65)
    print(f"Rows read: {result['total_rows_read']}")
    print(f"Status: {result['status']}")
    print(f"Temporal provenance: {meta['status']}")
    if meta["reason"]:
        for item in meta["reason"]:
            print("  CONTRACT_WARNING:", item)
    print("No dirt / 7-9 popularity segment is claimed (market data unavailable).")
    print("--- TEST / OOS THREE-TARGET METRICS ---")
    for entry in result["by_split_year_scope"]:
        if entry["year"] != "ALL":
            continue
        part, scope = entry["split"], entry["organizer"]
        b, s = entry["base"], entry["model_top1"]
        print(f"{part}/{scope}: runners={b['n']} model_top1={s['n']}")
        for target in TARGETS:
            v = b[target]
            k = s[target]
            print(
                f"  {target}: base={v['actual_rate']:.4f} "
                f"top1={k['actual_rate'] if k['actual_rate'] is not None else 'NA'} "
                f"brier={v['brier']:.6f} calGap={v['calibration_gap_pp']:.3f}pt "
                f"lift={entry['top1_lift_vs_all_runners'][target]}"
            )
    print(f"Output (aggregates only): {output}")
    print("Source CSV and PostgreSQL untouched.")
    print("=" * 65)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
