from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neo_jizo_dirt_edge_adapter import adapt_rows


def prediction(
    race: str,
    runner: str,
    p_win: float,
    p_top2: float,
    p_top3: float,
    *,
    race_date: str = "2025-01-01",
    **extra: object,
) -> dict[str, object]:
    row = {
        "race_id": race,
        "race_horse_id": runner,
        "race_date": race_date,
        "p_win_cal": p_win,
        "p_top2_cal": p_top2,
        "p_top3_cal": p_top3,
    }
    row.update(extra)
    return row


def context(
    race: str,
    runner: str,
    finish: int,
    popularity: int,
    odds: float,
    *,
    surface: str = "dirt",
    organizer: str = "NAR",
) -> dict[str, object]:
    return {
        "race_id": race,
        "race_horse_id": runner,
        "finish_position": finish,
        "popularity": popularity,
        "odds": odds,
        "surface": surface,
        "organizer": organizer,
    }


def test_model_rank_is_frozen_from_probability_not_popularity_or_result() -> None:
    predictions = [
        prediction("R1", "H1", 0.10, 0.30, 0.50, label_win=1),
        prediction("R1", "H2", 0.30, 0.50, 0.70, label_win=0),
        prediction("R1", "H3", 0.20, 0.40, 0.60, label_win=0),
    ]
    contexts = [
        context("R1", "H1", 1, 1, 2.0),
        context("R1", "H2", 5, 9, 80.0),
        context("R1", "H3", 3, 5, 10.0),
    ]

    rows = adapt_rows(predictions, contexts)
    ranks = {row["runner_id"]: row["model_rank"] for row in rows}

    assert ranks == {"H1": 3, "H2": 1, "H3": 2}


def test_tie_break_is_deterministic_and_independent_of_market_context() -> None:
    predictions = [
        prediction("R1", "H2", 0.20, 0.40, 0.60),
        prediction("R1", "H1", 0.20, 0.40, 0.60),
    ]
    contexts = [
        context("R1", "H2", 1, 1, 2.0),
        context("R1", "H1", 2, 9, 70.0),
    ]

    rows = adapt_rows(predictions, contexts)
    ranks = {row["runner_id"]: row["model_rank"] for row in rows}

    assert ranks == {"H1": 1, "H2": 2}


def test_key_mismatch_is_rejected() -> None:
    predictions = [prediction("R1", "H1", 0.20, 0.40, 0.60)]
    contexts = [context("R1", "OTHER", 1, 7, 20.0)]

    with pytest.raises(ValueError, match="key mismatch"):
        adapt_rows(predictions, contexts)


def test_duplicate_prediction_key_is_rejected() -> None:
    predictions = [
        prediction("R1", "H1", 0.20, 0.40, 0.60),
        prediction("R1", "H1", 0.21, 0.41, 0.61),
    ]
    contexts = [context("R1", "H1", 1, 7, 20.0)]

    with pytest.raises(ValueError, match="prediction duplicate key"):
        adapt_rows(predictions, contexts)


def test_probability_order_violation_is_rejected() -> None:
    predictions = [prediction("R1", "H1", 0.30, 0.20, 0.60)]
    contexts = [context("R1", "H1", 1, 7, 20.0)]

    with pytest.raises(ValueError, match="probability order violation"):
        adapt_rows(predictions, contexts)
