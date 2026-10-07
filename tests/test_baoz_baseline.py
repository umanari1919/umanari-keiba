from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from baoz_baseline import evaluate_rows, normalize_mark, popularity_band


def test_normalize_mark_and_popularity_band() -> None:
    assert normalize_mark("") == "無印"
    assert normalize_mark(" ◎ ") == "◎"
    assert popularity_band("1") == "1"
    assert popularity_band("3") == "2-3"
    assert popularity_band("6") == "4-6"
    assert popularity_band("7") == "7+"
    assert popularity_band("") == "unknown"


def test_evaluate_rows_separates_prediction_quality_and_roi() -> None:
    rows = [
        {
            "race_id": "R1",
            "runner_id": "H1",
            "mark": "◎",
            "finish_position": "1",
            "popularity": "1",
            "win_return_yen": "250",
            "place_return_yen": "120",
        },
        {
            "race_id": "R2",
            "runner_id": "H2",
            "mark": "◎",
            "finish_position": "4",
            "popularity": "2",
            "win_return_yen": "0",
            "place_return_yen": "0",
        },
        {
            "race_id": "R1",
            "runner_id": "H3",
            "mark": "○",
            "finish_position": "2",
            "popularity": "3",
            "win_return_yen": "0",
            "place_return_yen": "160",
        },
    ]

    result = evaluate_rows(rows)

    assert result["race_count"] == 2
    assert result["runner_count"] == 3

    favorite = result["by_mark"]["◎"]
    assert favorite["starts"] == 2
    assert favorite["wins"] == 1
    assert favorite["top2"] == 1
    assert favorite["top3"] == 1
    assert favorite["win_rate"] == 0.5
    assert favorite["top2_rate"] == 0.5
    assert favorite["top3_rate"] == 0.5
    assert favorite["win_roi_pct"] == 125.0
    assert favorite["place_roi_pct"] == 60.0

    second = result["by_mark"]["○"]
    assert second["top2_rate"] == 1.0
    assert second["place_roi_pct"] == 160.0

    assert result["by_mark_popularity"]["◎|1"]["wins"] == 1
    assert result["by_mark_popularity"]["◎|2-3"]["wins"] == 0


def test_missing_payout_is_not_counted_as_a_bet() -> None:
    rows = [
        {
            "race_id": "R1",
            "runner_id": "H1",
            "mark": "▲",
            "finish_position": "3",
            "popularity": "",
            "win_return_yen": "",
            "place_return_yen": "",
        }
    ]

    result = evaluate_rows(rows)
    metrics = result["by_mark"]["▲"]

    assert metrics["top3_rate"] == 1.0
    assert metrics["win_roi_pct"] is None
    assert metrics["place_roi_pct"] is None
    assert metrics["win_bets"] == 0
    assert metrics["place_bets"] == 0
