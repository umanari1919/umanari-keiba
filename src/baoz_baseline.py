"""BAOZ-BASELINE-001 pure evaluation core.

This module intentionally has no dependency on BaoZ MDB files.
Local extraction is a separate read-only step.  The evaluator consumes a
small CSV contract so GitHub CI can test the research logic without private
or licensed data.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

MARK_ORDER = ("◎", "○", "▲", "△", "☆", "注", "無印")


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return int(float(text))


def normalize_mark(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return text or "無印"


def popularity_band(value: Any) -> str:
    popularity = _optional_int(value)
    if popularity is None or popularity <= 0:
        return "unknown"
    if popularity == 1:
        return "1"
    if popularity <= 3:
        return "2-3"
    if popularity <= 6:
        return "4-6"
    return "7+"


@dataclass
class Aggregate:
    starts: int = 0
    wins: int = 0
    top2: int = 0
    top3: int = 0
    win_return_yen: int = 0
    place_return_yen: int = 0
    win_bets: int = 0
    place_bets: int = 0

    def add(self, row: dict[str, Any]) -> None:
        finish = _optional_int(row.get("finish_position"))
        if finish is None or finish <= 0:
            raise ValueError("finish_position must be a positive integer")

        self.starts += 1
        self.wins += int(finish == 1)
        self.top2 += int(finish <= 2)
        self.top3 += int(finish <= 3)

        win_return = _optional_int(row.get("win_return_yen"))
        if win_return is not None:
            self.win_bets += 1
            self.win_return_yen += win_return

        place_return = _optional_int(row.get("place_return_yen"))
        if place_return is not None:
            self.place_bets += 1
            self.place_return_yen += place_return

    def to_dict(self) -> dict[str, int | float | None]:
        def rate(numerator: int) -> float:
            return numerator / self.starts if self.starts else 0.0

        def roi(total_return: int, bets: int) -> float | None:
            if not bets:
                return None
            return total_return / (bets * 100) * 100

        return {
            "starts": self.starts,
            "wins": self.wins,
            "top2": self.top2,
            "top3": self.top3,
            "win_rate": rate(self.wins),
            "top2_rate": rate(self.top2),
            "top3_rate": rate(self.top3),
            "win_roi_pct": roi(self.win_return_yen, self.win_bets),
            "place_roi_pct": roi(self.place_return_yen, self.place_bets),
            "win_bets": self.win_bets,
            "place_bets": self.place_bets,
        }


def validate_row(row: dict[str, Any]) -> None:
    required = ("race_id", "runner_id", "finish_position")
    missing = [name for name in required if not str(row.get(name, "")).strip()]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")


def evaluate_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    by_mark: dict[str, Aggregate] = defaultdict(Aggregate)
    by_mark_popularity: dict[tuple[str, str], Aggregate] = defaultdict(Aggregate)
    race_ids: set[str] = set()
    runner_count = 0

    for raw_row in rows:
        row = dict(raw_row)
        validate_row(row)
        mark = normalize_mark(row.get("mark"))
        band = popularity_band(row.get("popularity"))
        race_ids.add(str(row["race_id"]).strip())
        runner_count += 1
        by_mark[mark].add(row)
        by_mark_popularity[(mark, band)].add(row)

    ordered_marks = sorted(by_mark, key=lambda mark: (MARK_ORDER.index(mark) if mark in MARK_ORDER else 999, mark))

    return {
        "race_count": len(race_ids),
        "runner_count": runner_count,
        "by_mark": {mark: by_mark[mark].to_dict() for mark in ordered_marks},
        "by_mark_popularity": {
            f"{mark}|{band}": aggregate.to_dict()
            for (mark, band), aggregate in sorted(by_mark_popularity.items())
        },
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate BaoZ baseline marks from a research CSV")
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = evaluate_rows(read_csv(args.input_csv))
    payload = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
