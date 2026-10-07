"""NEO-JIZO-DIRT-EDGE-025 evaluation core.

This module is intentionally independent from PostgreSQL, BaoZ MDB files and
licensed/private data.  It evaluates already-materialized pre-race predictions
using a small CSV-like row contract.

The primary contract keeps three targets separate:
- win
- top-2
- top-3

Popularity and odds are evaluation variables.  They are not model inputs here.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable


TARGETS = ("win", "top2", "top3")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _required_text(row: dict[str, Any], name: str) -> str:
    value = _text(row.get(name))
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _int(value: Any, name: str) -> int:
    text = _text(value)
    if not text:
        raise ValueError(f"{name} is required")
    try:
        return int(float(text))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _optional_int(value: Any) -> int | None:
    text = _text(value)
    if not text:
        return None
    return int(float(text))


def _optional_float(value: Any) -> float | None:
    text = _text(value)
    if not text:
        return None
    return float(text)


def _probability(value: Any, name: str) -> float:
    text = _text(value)
    if not text:
        raise ValueError(f"{name} is required")
    try:
        result = float(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return result


def _year(value: Any) -> int | None:
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).year
    except ValueError:
        if len(text) >= 4 and text[:4].isdigit():
            return int(text[:4])
        raise ValueError("race_date must start with YYYY or be ISO formatted")


def normalize_surface(value: Any) -> str:
    text = _text(value).lower()
    aliases = {
        "d": "dirt",
        "dirt": "dirt",
        "ダ": "dirt",
        "ダート": "dirt",
        "t": "turf",
        "turf": "turf",
        "芝": "turf",
        "jump": "jump",
        "obstacle": "jump",
        "障害": "jump",
    }
    return aliases.get(text, text or "unknown")


@dataclass(frozen=True)
class PreparedRow:
    race_id: str
    runner_id: str
    finish_position: int
    model_rank: int
    p_win: float
    p_top2: float
    p_top3: float
    popularity: int | None
    odds: float | None
    surface: str
    organizer: str
    year: int | None

    @property
    def win(self) -> int:
        return int(self.finish_position == 1)

    @property
    def top2(self) -> int:
        return int(self.finish_position <= 2)

    @property
    def top3(self) -> int:
        return int(self.finish_position <= 3)


def prepare_row(row: dict[str, Any]) -> PreparedRow:
    prepared = PreparedRow(
        race_id=_required_text(row, "race_id"),
        runner_id=_required_text(row, "runner_id"),
        finish_position=_int(row.get("finish_position"), "finish_position"),
        model_rank=_int(row.get("model_rank"), "model_rank"),
        p_win=_probability(row.get("p_win"), "p_win"),
        p_top2=_probability(row.get("p_top2"), "p_top2"),
        p_top3=_probability(row.get("p_top3"), "p_top3"),
        popularity=_optional_int(row.get("popularity")),
        odds=_optional_float(row.get("odds")),
        surface=normalize_surface(row.get("surface")),
        organizer=_text(row.get("organizer")) or "unknown",
        year=_year(row.get("race_date")),
    )

    if prepared.finish_position <= 0:
        raise ValueError("finish_position must be positive")
    if prepared.model_rank <= 0:
        raise ValueError("model_rank must be positive")
    if prepared.popularity is not None and prepared.popularity <= 0:
        raise ValueError("popularity must be positive when supplied")
    if prepared.odds is not None and prepared.odds <= 0:
        raise ValueError("odds must be positive when supplied")
    if not (prepared.p_win <= prepared.p_top2 <= prepared.p_top3):
        raise ValueError("probabilities must satisfy p_win <= p_top2 <= p_top3")
    return prepared


@dataclass
class ProbabilityAggregate:
    starts: int = 0
    wins: int = 0
    top2: int = 0
    top3: int = 0
    sum_p_win: float = 0.0
    sum_p_top2: float = 0.0
    sum_p_top3: float = 0.0
    sum_brier_win: float = 0.0
    sum_brier_top2: float = 0.0
    sum_brier_top3: float = 0.0
    odds_count: int = 0
    sum_odds: float = 0.0

    def add(self, row: PreparedRow) -> None:
        self.starts += 1
        self.wins += row.win
        self.top2 += row.top2
        self.top3 += row.top3

        self.sum_p_win += row.p_win
        self.sum_p_top2 += row.p_top2
        self.sum_p_top3 += row.p_top3

        self.sum_brier_win += (row.p_win - row.win) ** 2
        self.sum_brier_top2 += (row.p_top2 - row.top2) ** 2
        self.sum_brier_top3 += (row.p_top3 - row.top3) ** 2

        if row.odds is not None:
            self.odds_count += 1
            self.sum_odds += row.odds

    def to_dict(self) -> dict[str, Any]:
        if not self.starts:
            return {
                "starts": 0,
                "wins": 0,
                "top2": 0,
                "top3": 0,
                "win_rate": None,
                "top2_rate": None,
                "top3_rate": None,
                "win_rate_ci95": None,
                "top2_rate_ci95": None,
                "top3_rate_ci95": None,
                "avg_p_win": None,
                "avg_p_top2": None,
                "avg_p_top3": None,
                "win_calibration_gap_pp": None,
                "top2_calibration_gap_pp": None,
                "top3_calibration_gap_pp": None,
                "brier_win": None,
                "brier_top2": None,
                "brier_top3": None,
                "avg_odds": None,
            }

        n = self.starts
        win_rate = self.wins / n
        top2_rate = self.top2 / n
        top3_rate = self.top3 / n
        avg_p_win = self.sum_p_win / n
        avg_p_top2 = self.sum_p_top2 / n
        avg_p_top3 = self.sum_p_top3 / n

        return {
            "starts": n,
            "wins": self.wins,
            "top2": self.top2,
            "top3": self.top3,
            "win_rate": win_rate,
            "top2_rate": top2_rate,
            "top3_rate": top3_rate,
            "win_rate_ci95": _wilson_interval(self.wins, n),
            "top2_rate_ci95": _wilson_interval(self.top2, n),
            "top3_rate_ci95": _wilson_interval(self.top3, n),
            "avg_p_win": avg_p_win,
            "avg_p_top2": avg_p_top2,
            "avg_p_top3": avg_p_top3,
            "win_calibration_gap_pp": (win_rate - avg_p_win) * 100,
            "top2_calibration_gap_pp": (top2_rate - avg_p_top2) * 100,
            "top3_calibration_gap_pp": (top3_rate - avg_p_top3) * 100,
            "brier_win": self.sum_brier_win / n,
            "brier_top2": self.sum_brier_top2 / n,
            "brier_top3": self.sum_brier_top3 / n,
            "avg_odds": self.sum_odds / self.odds_count if self.odds_count else None,
        }


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total <= 0:
        return None
    p = successes / total
    z2 = z * z
    denominator = 1 + z2 / total
    center = (p + z2 / (2 * total)) / denominator
    half = (
        z
        * math.sqrt((p * (1 - p) / total) + z2 / (4 * total * total))
        / denominator
    )
    return [max(0.0, center - half), min(1.0, center + half)]


def _odds_ratio_details(
    selected: ProbabilityAggregate, base: ProbabilityAggregate
) -> dict[str, float | None]:
    nonselected_n = base.starts - selected.starts
    nonselected_w = base.wins - selected.wins
    a = selected.wins
    b = selected.starts - selected.wins
    c = nonselected_w
    d = nonselected_n - nonselected_w
    if min(a, b, c, d) <= 0:
        return {"odds_ratio": None, "ci95_low": None, "ci95_high": None}

    odds_ratio = (a / b) / (c / d)
    log_se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return {
        "odds_ratio": odds_ratio,
        "ci95_low": math.exp(math.log(odds_ratio) - 1.96 * log_se),
        "ci95_high": math.exp(math.log(odds_ratio) + 1.96 * log_se),
    }


def _evaluate_prepared(rows: Iterable[PreparedRow]) -> ProbabilityAggregate:
    aggregate = ProbabilityAggregate()
    for row in rows:
        aggregate.add(row)
    return aggregate


def evaluate_rows(
    rows: Iterable[dict[str, Any]],
    *,
    selected_rank: int = 1,
    popularity_min: int | None = None,
    popularity_max: int | None = None,
    surface: str | None = None,
) -> dict[str, Any]:
    prepared: list[PreparedRow] = []
    seen: set[tuple[str, str]] = set()

    target_surface = normalize_surface(surface) if surface is not None else None

    for raw in rows:
        row = prepare_row(dict(raw))
        key = (row.race_id, row.runner_id)
        if key in seen:
            raise ValueError(f"duplicate race_id/runner_id: {row.race_id}/{row.runner_id}")
        seen.add(key)

        if popularity_min is not None:
            if row.popularity is None or row.popularity < popularity_min:
                continue
        if popularity_max is not None:
            if row.popularity is None or row.popularity > popularity_max:
                continue
        if target_surface is not None and row.surface != target_surface:
            continue

        prepared.append(row)

    base = _evaluate_prepared(prepared)
    selected_rows = [row for row in prepared if row.model_rank == selected_rank]
    selected = _evaluate_prepared(selected_rows)

    base_metrics = base.to_dict()
    selected_metrics = selected.to_dict()

    lifts = {
        "win": _safe_ratio(selected_metrics["win_rate"], base_metrics["win_rate"]),
        "top2": _safe_ratio(selected_metrics["top2_rate"], base_metrics["top2_rate"]),
        "top3": _safe_ratio(selected_metrics["top3_rate"], base_metrics["top3_rate"]),
    }

    by_year: dict[int, dict[str, Any]] = {}
    years = sorted({row.year for row in prepared if row.year is not None})
    for year in years:
        year_rows = [row for row in prepared if row.year == year]
        year_base = _evaluate_prepared(year_rows)
        year_selected = _evaluate_prepared([row for row in year_rows if row.model_rank == selected_rank])
        year_base_metrics = year_base.to_dict()
        year_selected_metrics = year_selected.to_dict()
        by_year[year] = {
            "base": year_base_metrics,
            "selected": year_selected_metrics,
            "lift": {
                "win": _safe_ratio(year_selected_metrics["win_rate"], year_base_metrics["win_rate"]),
                "top2": _safe_ratio(year_selected_metrics["top2_rate"], year_base_metrics["top2_rate"]),
                "top3": _safe_ratio(year_selected_metrics["top3_rate"], year_base_metrics["top3_rate"]),
            },
        }

    by_organizer: dict[str, dict[str, Any]] = {}
    organizer_rows: dict[str, list[PreparedRow]] = defaultdict(list)
    for row in prepared:
        organizer_rows[row.organizer].append(row)
    for organizer, group in sorted(organizer_rows.items()):
        group_base = _evaluate_prepared(group)
        group_selected = _evaluate_prepared([row for row in group if row.model_rank == selected_rank])
        b = group_base.to_dict()
        s = group_selected.to_dict()
        by_organizer[organizer] = {
            "base": b,
            "selected": s,
            "lift": {
                "win": _safe_ratio(s["win_rate"], b["win_rate"]),
                "top2": _safe_ratio(s["top2_rate"], b["top2_rate"]),
                "top3": _safe_ratio(s["top3_rate"], b["top3_rate"]),
            },
        }

    odds_ratio = _odds_ratio_details(selected, base)

    return {
        "contract_version": "NEO-JIZO-DIRT-EDGE-025/v1",
        "filters": {
            "selected_rank": selected_rank,
            "popularity_min": popularity_min,
            "popularity_max": popularity_max,
            "surface": target_surface,
        },
        "base": base_metrics,
        "selected": selected_metrics,
        "lift": lifts,
        "selection_win_odds_ratio": odds_ratio["odds_ratio"],
        "selection_win_odds_ratio_ci95": [
            odds_ratio["ci95_low"],
            odds_ratio["ci95_high"],
        ]
        if odds_ratio["odds_ratio"] is not None
        else None,
        "by_year": by_year,
        "by_organizer": by_organizer,
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate NEO JIZO pre-race probability outputs")
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--selected-rank", type=int, default=1)
    parser.add_argument("--popularity-min", type=int)
    parser.add_argument("--popularity-max", type=int)
    parser.add_argument("--surface")
    args = parser.parse_args()

    result = evaluate_rows(
        read_csv(args.input_csv),
        selected_rank=args.selected_rank,
        popularity_min=args.popularity_min,
        popularity_max=args.popularity_max,
        surface=args.surface,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
