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
    "p_win", "p_win_cal", "p_top2_cal", "p_top3_cal",
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


def parse(row: dict[str, str]) -> tuple[date, str, str, str, tuple[int, int, int], tuple[float, float, float], float]:
    rid, horse = _value(row, "race_id"), _value(row, "race_horse_id")
    if not rid or not horse:
        raise ValueError("missing unique key")
    dt = date.fromisoformat(_value(row, "race_date")[:10])
    raw_scope = _value(row, "race_scope_cd")
    try:
        scope_number = float(raw_scope)
    except ValueError:
        raise ValueError("invalid race_scope_cd") from None
    scope = {1.0: "JRA", 2.0: "NAR"}.get(scope_number)
    if not scope:
        raise ValueError("invalid race_scope_cd")
    try:
        raw_labels = tuple(float(_value(row, f"label_{t}")) for t in TARGETS)
    except ValueError:
        raise ValueError("invalid target labels") from None
    if any(not math.isfinite(x) or x not in (0.0, 1.0) for x in raw_labels):
        raise ValueError("invalid target labels")
    labels = tuple(int(x) for x in raw_labels)
    if not labels[0] <= labels[1] <= labels[2]:
        raise ValueError("inconsistent outcome labels")
    try:
        probs = tuple(float(_value(row, f"p_{t}_cal")) for t in TARGETS)
    except ValueError:
        raise ValueError("invalid probability") from None
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in probs):
        raise ValueError("invalid probability")
    if not probs[0] <= probs[1] <= probs[2]:
        raise ValueError("non-monotonic predicted targets")
    try:
        ranking_score = float(_value(row, "p_win"))
    except ValueError:
        raise ValueError("invalid raw win score") from None
    if not math.isfinite(ranking_score) or not 0 <= ranking_score <= 1:
        raise ValueError("invalid raw win score")
    return dt, scope, rid, horse, labels, probs, ranking_score


def split_for_day(day: date, windows: list[tuple[str, date, date]]) -> str:
    for name, start, end in windows:
        if start <= day <= end:
            return name
    return "UNCLASSIFIED"


def _invalid_reason(exc: Exception) -> str:
    """Stable, aggregate-only categories; do not expose source rows."""
    detail = str(exc).lower()
    if "missing unique key" in detail:
        return "MISSING_RUNNER_KEY"
    if "isoformat" in detail or "invalid isoformat" in detail:
        return "INVALID_RACE_DATE"
    if "race_scope_cd" in detail:
        return "INVALID_OR_MISSING_SCOPE"
    if "label_win" in detail or "label_top2" in detail or "label_top3" in detail:
        return "INVALID_OR_MISSING_OUTCOME_LABELS"
    if "p_win" in detail or "p_top2" in detail or "p_top3" in detail:
        return "INVALID_OR_NONMONOTONIC_PROBABILITIES"
    if "inconsistent outcome labels" in detail:
        return "INCONSISTENT_OUTCOME_LABELS"
    if "invalid target labels" in detail:
        return "INVALID_OR_MISSING_OUTCOME_LABELS"
    if "invalid probability" in detail or "non-monotonic" in detail:
        return "INVALID_OR_NONMONOTONIC_PROBABILITIES"
    if "invalid raw win score" in detail:
        return "INVALID_RAW_WIN_SCORE"
    return "OTHER_INVALID_VALUE"


def _raw_split(row: dict[str, str], windows: list[tuple[str, date, date]]) -> str:
    try:
        return split_for_day(date.fromisoformat(_value(row, "race_date")[:10]), windows)
    except (ValueError, TypeError):
        return "UNKNOWN_DATE"


def _record_dimensions(
    aggregates: dict[tuple[str, int, str, str], Aggregate],
    part: str,
    year: int,
    scope: str,
    bucket: str,
    labels: tuple[int, int, int],
    probs: tuple[float, float, float],
) -> None:
    for dims in (
        (part, year, scope, bucket),
        (part, year, "ALL", bucket),
        (part, 0, scope, bucket),
        (part, 0, "ALL", bucket),
    ):
        aggregates[dims].add(labels, probs)


def _clean_race_sensitivity(
    path: Path,
    windows: list[tuple[str, date, date]],
    affected_race_ids: set[str],
) -> dict[str, Any]:
    """Separate sensitivity: exclude races containing any detected invalid row.

    Even this cannot prove absent/unrecorded horses, so "clean" means only
    no invalid row observed in the available CSV.
    """
    aggregates: dict[tuple[str, str, str], Aggregate] = defaultdict(Aggregate)
    leaders: dict[tuple[str, str], tuple[float, float, str, str, tuple[int, int, int], tuple[float, float, float]]] = {}
    race_ids: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            race_id = _value(row, "race_id")
            if not race_id or race_id in affected_race_ids:
                continue
            try:
                dt, scope, race, horse, labels, probs, raw_score = parse(row)
            except (ValueError, TypeError, OverflowError, KeyError):
                continue
            part = split_for_day(dt, windows)
            if part not in ("TEST", "OOS"):
                continue
            race_ids.add((part, race))
            for dims in ((part, scope, "ALL"), (part, "ALL", "ALL")):
                aggregates[dims].add(labels, probs)
            k = (part, race)
            current = leaders.get(k)
            if current is None or probs[0] > current[0] or (
                probs[0] == current[0] and (
                    raw_score > current[1] or
                    (raw_score == current[1] and horse < current[2])
                )
            ):
                leaders[k] = (probs[0], raw_score, horse, scope, labels, probs)

    for (part, _race), (_p, _raw, _horse, scope, labels, probs) in leaders.items():
        for dims in ((part, scope, "SELECTED_TOP1"), (part, "ALL", "SELECTED_TOP1")):
            aggregates[dims].add(labels, probs)

    summaries: list[dict[str, Any]] = []
    for part in ("TEST", "OOS"):
        for scope in ("ALL", "JRA", "NAR"):
            base = aggregates[(part, scope, "ALL")]
            top1 = aggregates[(part, scope, "SELECTED_TOP1")]
            summaries.append({
                "split": part,
                "organizer": scope,
                "all_runners": base.n,
                "model_top1": top1.n,
                "model_top1_rates": {
                    t: (top1.positives[i] / top1.n if top1.n else None)
                    for i, t in enumerate(TARGETS)
                },
                "model_top1_lift": {
                    t: _lift(top1, base, i) for i, t in enumerate(TARGETS)
                },
            })
    return {
        "interpretation": "Sensitivity excluding every race with any detected invalid row; missing/unrecorded entrants are not detectable",
        "excluded_unique_race_ids": len(affected_race_ids),
        "remaining_test_oos_races": len(race_ids),
        "by_split_scope": summaries,
    }


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
    leaders: dict[tuple[str, str], tuple[float, float, str, int, str, tuple[int, int, int], tuple[float, float, float]]] = {}
    seen: set[tuple[str, str]] = set()
    row_counts: dict[str, int] = defaultdict(int)
    invalid_types: dict[str, int] = defaultdict(int)
    invalid_reasons: dict[str, int] = defaultdict(int)
    invalid_by_split: dict[str, int] = defaultdict(int)
    invalid_race_ids: set[str] = set()
    invalid_missing_race_id = 0
    total_rows = 0

    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not REQUIRED.issubset(reader.fieldnames):
            missing = sorted(REQUIRED - set(reader.fieldnames or ()))
            raise ValueError("CORE-010 missing required columns: " + ", ".join(missing))
        for raw in reader:
            total_rows += 1
            try:
                dt, scope, race, horse, labels, probs, raw_score = parse(raw)
            except (ValueError, TypeError, OverflowError, KeyError) as exc:
                invalid_types[type(exc).__name__] += 1
                invalid_reasons[_invalid_reason(exc)] += 1
                invalid_by_split[_raw_split(raw, windows)] += 1
                raw_id = _value(raw, "race_id")
                if raw_id:
                    invalid_race_ids.add(raw_id)
                else:
                    invalid_missing_race_id += 1
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
                # Isotonic calibration can create ties; use the original
                # pre-calibration win score before deterministic runner ID.
                # Market/results are never used to decide a ranking.
                if current is None or probs[0] > current[0] or (
                    probs[0] == current[0] and (
                        raw_score > current[1]
                        or (raw_score == current[1] and horse < current[2])
                    )
                ):
                    leaders[rkey] = (probs[0], raw_score, horse, year, scope, labels, probs)

    for (part, _race), candidate in leaders.items():
        _, _, _, year, scope, labels, probs = candidate
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

    invalid_count = sum(invalid_reasons.values())
    known_invalid_eval_rows = sum(
        invalid_by_split.get(part, 0) for part in ("TEST", "OOS")
    )
    status = ("HOLDOUT_CONTRACT_MATCHED" if provenance_info["verified"] else "DIAGNOSTIC_ONLY")
    if invalid_count:
        status = "PARTIAL_INVALID_ROWS"
    if not any(item["base"]["n"] and item["split"] == "OOS" for item in report):
        status = "BLOCKED_NO_OOS"

    # A sensitivity run is triggered only if a known TEST/OOS row was invalid
    # or the split was unknown. The benchmark is NOT silently promoted to PASS.
    clean_sensitivity = None
    if known_invalid_eval_rows or invalid_by_split.get("UNKNOWN_DATE", 0):
        clean_sensitivity = _clean_race_sensitivity(
            csv_path, windows, invalid_race_ids
        )

    return {
        "mission": "NEO-JIZO-DIRT-EDGE-025",
        "probe": "CORE010-OFFLINE-001",
        "status": status,
        "assessment_scope": "ALL_SURFACES; NO_P7_9_OR_DIRT_SLICE",
        "model_top1_order": "p_win_cal desc, p_win desc, race_horse_id asc",
        "evaluation_type": "historical retrospective holdout diagnostics; not certified live pre-race predictions",
        "provenance": provenance_info,
        "input": {"size_bytes": csv_path.stat().st_size},
        "total_rows_read": total_rows,
        "rows_by_split": dict(sorted(row_counts.items())),
        "invalid_row_types": dict(sorted(invalid_types.items())),
        "invalid_row_reasons": dict(sorted(invalid_reasons.items())),
        "invalid_rows_by_split": dict(sorted(invalid_by_split.items())),
        "invalid_rows_total": invalid_count,
        "valid_rows_total": sum(row_counts.values()),
        "valid_row_fraction": (
            sum(row_counts.values()) / total_rows if total_rows else None
        ),
        "known_invalid_test_oos_rows": known_invalid_eval_rows,
        "invalid_rows_with_unknown_date": invalid_by_split.get("UNKNOWN_DATE", 0),
        "invalid_rows_without_race_id": invalid_missing_race_id,
        "affected_races_detected": len(invalid_race_ids),
        "clean_race_sensitivity": clean_sensitivity,
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
    print(
        f"Invalid rows: {result['invalid_rows_total']} "
        f"({(1 - result['valid_row_fraction']) * 100:.3f}% of input)"
    )
    print("Invalid reasons (aggregate only):")
    for reason, count in result["invalid_row_reasons"].items():
        print(f"  {reason}: {count}")
    print(f"Invalid rows by split: {result['invalid_rows_by_split']}")
    print(
        f"Known invalid TEST/OOS rows: {result['known_invalid_test_oos_rows']}, "
        f"unknown-date rows: {result['invalid_rows_with_unknown_date']}, "
        f"affected race IDs: {result['affected_races_detected']}"
    )
    if result["clean_race_sensitivity"] is not None:
        print("--- CLEAN-RACE SENSITIVITY (NO DETECTED INVALID ROWS) ---")
        for item in result["clean_race_sensitivity"]["by_split_scope"]:
            if item["organizer"] != "ALL":
                continue
            print(
                f"{item['split']}: runners={item['all_runners']} "
                f"top1={item['model_top1']} "
                f"win={item['model_top1_rates']['win']} "
                f"top2={item['model_top1_rates']['top2']} "
                f"top3={item['model_top1_rates']['top3']}"
            )
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
