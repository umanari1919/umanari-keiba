"""Adapter from existing NEO JIZO probability outputs to the 025 evaluator.

Prediction ranking is frozen from p_win before any market/result context is
joined.  Popularity and odds are evaluation-only variables.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any


PREDICTION_FIELDS = {
    "race_id",
    "race_horse_id",
    "race_date",
    "p_win_cal",
    "p_top2_cal",
    "p_top3_cal",
}

CONTEXT_FIELDS = {
    "race_id",
    "race_horse_id",
    "finish_position",
    "popularity",
    "odds",
    "surface",
    "organizer",
}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _required(row: dict[str, Any], name: str) -> str:
    value = _text(row.get(name))
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _probability(row: dict[str, Any], name: str) -> float:
    value = float(_required(row, name))
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _check_columns(rows: list[dict[str, Any]], required: set[str], label: str) -> None:
    if not rows:
        raise ValueError(f"{label} is empty")
    columns = set(rows[0])
    missing = sorted(required - columns)
    if missing:
        raise ValueError(f"{label} missing columns: {', '.join(missing)}")


def _unique_index(rows: list[dict[str, Any]], label: str) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (_required(row, "race_id"), _required(row, "race_horse_id"))
        if key in index:
            raise ValueError(f"{label} duplicate key: {key[0]}/{key[1]}")
        index[key] = row
    return index


def adapt_rows(
    prediction_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create evaluator rows without allowing market/result fields into ranking."""

    _check_columns(prediction_rows, PREDICTION_FIELDS, "prediction")
    _check_columns(context_rows, CONTEXT_FIELDS, "context")

    prediction_index = _unique_index(prediction_rows, "prediction")
    context_index = _unique_index(context_rows, "context")

    prediction_keys = set(prediction_index)
    context_keys = set(context_index)
    if prediction_keys != context_keys:
        missing_context = sorted(prediction_keys - context_keys)
        missing_prediction = sorted(context_keys - prediction_keys)
        detail = []
        if missing_context:
            detail.append(f"missing_context={len(missing_context)}")
        if missing_prediction:
            detail.append(f"missing_prediction={len(missing_prediction)}")
        raise ValueError("prediction/context key mismatch: " + ", ".join(detail))

    prepared_predictions: dict[tuple[str, str], dict[str, Any]] = {}
    by_race: dict[str, list[tuple[str, float]]] = defaultdict(list)

    for key, row in prediction_index.items():
        p_win = _probability(row, "p_win_cal")
        p_top2 = _probability(row, "p_top2_cal")
        p_top3 = _probability(row, "p_top3_cal")
        if not p_win <= p_top2 <= p_top3:
            raise ValueError(
                f"probability order violation: {key[0]}/{key[1]}"
            )

        prepared_predictions[key] = {
            "race_date": _required(row, "race_date"),
            "p_win": p_win,
            "p_top2": p_top2,
            "p_top3": p_top3,
        }
        by_race[key[0]].append((key[1], p_win))

    rank_by_key: dict[tuple[str, str], int] = {}
    for race_id, runners in by_race.items():
        # Market/result columns are unavailable here by construction.
        ordered = sorted(runners, key=lambda item: (-item[1], item[0]))
        for rank, (runner_id, _) in enumerate(ordered, start=1):
            rank_by_key[(race_id, runner_id)] = rank

    output: list[dict[str, Any]] = []
    for key in sorted(prediction_keys):
        prediction = prepared_predictions[key]
        context = context_index[key]
        output.append(
            {
                "race_id": key[0],
                "runner_id": key[1],
                "race_date": prediction["race_date"],
                "finish_position": _required(context, "finish_position"),
                "model_rank": rank_by_key[key],
                "p_win": prediction["p_win"],
                "p_top2": prediction["p_top2"],
                "p_top3": prediction["p_top3"],
                "popularity": _required(context, "popularity"),
                "odds": _required(context, "odds"),
                "surface": _required(context, "surface"),
                "organizer": _required(context, "organizer"),
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("no rows to write")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Adapt CORE-010 probabilities plus evaluation context for NEO-JIZO-DIRT-EDGE-025"
    )
    parser.add_argument("probabilities_csv", type=Path)
    parser.add_argument("context_csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = adapt_rows(_read_csv(args.probabilities_csv), _read_csv(args.context_csv))
    write_csv(args.output, rows)
    print(f"rows={len(rows)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
