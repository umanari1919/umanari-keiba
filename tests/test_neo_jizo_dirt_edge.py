from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neo_jizo_dirt_edge import evaluate_rows, normalize_surface, prepare_row


def row(
    race_id: str,
    runner_id: str,
    finish: int,
    rank: int,
    p_win: float,
    p_top2: float,
    p_top3: float,
    *,
    popularity: int,
    surface: str = "dirt",
    organizer: str = "NAR",
    race_date: str = "2024-01-01",
    odds: float = 20.0,
) -> dict[str, object]:
    return {
        "race_id": race_id,
        "runner_id": runner_id,
        "finish_position": finish,
        "model_rank": rank,
        "p_win": p_win,
        "p_top2": p_top2,
        "p_top3": p_top3,
        "popularity": popularity,
        "surface": surface,
        "organizer": organizer,
        "race_date": race_date,
        "odds": odds,
    }


def test_surface_aliases() -> None:
    assert normalize_surface("ダート") == "dirt"
    assert normalize_surface("芝") == "turf"
    assert normalize_surface("障害") == "jump"


def test_probability_contract_rejects_non_monotonic_targets() -> None:
    with pytest.raises(ValueError, match="p_win <= p_top2 <= p_top3"):
        prepare_row(
            row("R1", "H1", 1, 1, 0.30, 0.20, 0.60, popularity=7)
        )


def test_duplicate_runner_key_is_rejected() -> None:
    rows = [
        row("R1", "H1", 1, 1, 0.20, 0.40, 0.60, popularity=7),
        row("R1", "H1", 2, 2, 0.10, 0.30, 0.50, popularity=8),
    ]
    with pytest.raises(ValueError, match="duplicate race_id/runner_id"):
        evaluate_rows(rows)


def test_dirt_p7_9_contract_reports_three_targets_calibration_and_lift() -> None:
    rows = [
        row("R1", "H1", 1, 1, 0.20, 0.50, 0.70, popularity=7, race_date="2024-01-01"),
        row("R1", "H2", 2, 2, 0.10, 0.40, 0.60, popularity=8, race_date="2024-01-01"),
        row("R1", "H3", 4, 3, 0.05, 0.20, 0.30, popularity=9, race_date="2024-01-01"),
        row("R2", "H4", 3, 1, 0.15, 0.35, 0.55, popularity=8, race_date="2025-01-01"),
        row("R2", "H5", 5, 2, 0.08, 0.25, 0.40, popularity=7, race_date="2025-01-01"),
        row("R3", "H6", 1, 1, 0.25, 0.55, 0.75, popularity=6, race_date="2025-02-01"),
        row("R4", "H7", 1, 1, 0.30, 0.60, 0.80, popularity=7, surface="turf", race_date="2025-03-01"),
    ]

    result = evaluate_rows(
        rows,
        selected_rank=1,
        popularity_min=7,
        popularity_max=9,
        surface="dirt",
    )

    assert result["base"]["starts"] == 5
    assert result["selected"]["starts"] == 2

    assert result["base"]["wins"] == 1
    assert result["base"]["top2"] == 2
    assert result["base"]["top3"] == 3

    assert result["selected"]["wins"] == 1
    assert result["selected"]["top2"] == 1
    assert result["selected"]["top3"] == 2

    assert result["lift"]["win"] == pytest.approx(2.5)
    assert result["lift"]["top2"] == pytest.approx(1.25)
    assert result["lift"]["top3"] == pytest.approx(5 / 3)

    assert result["selected"]["avg_p_win"] == pytest.approx(0.175)
    assert result["selected"]["brier_win"] is not None
    assert result["selected"]["brier_top2"] is not None
    assert result["selected"]["brier_top3"] is not None

    assert set(result["by_year"]) == {2024, 2025}
    assert result["by_organizer"]["NAR"]["selected"]["starts"] == 2


def test_selection_odds_ratio_uses_nonselected_comparator() -> None:
    rows = []
    # Selected: 2 wins / 4 starts.
    for i, finish in enumerate([1, 1, 4, 5], start=1):
        rows.append(
            row(
                f"RS{i}",
                f"HS{i}",
                finish,
                1,
                0.20,
                0.40,
                0.60,
                popularity=7,
                race_date="2024-01-01",
            )
        )

    # Non-selected: 1 win / 6 starts.
    for i, finish in enumerate([1, 2, 3, 4, 5, 6], start=1):
        rows.append(
            row(
                f"RN{i}",
                f"HN{i}",
                finish,
                2,
                0.10,
                0.30,
                0.50,
                popularity=8,
                race_date="2024-01-01",
            )
        )

    result = evaluate_rows(rows, popularity_min=7, popularity_max=9, surface="dirt")
    # (2/2) / (1/5) = 5.0
    assert result["selection_win_odds_ratio"] == pytest.approx(5.0)
