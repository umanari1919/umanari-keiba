from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import neo_jizo_core010_offline_evaluation_025 as offline


def make_root(tmp_path: Path, *, with_decisions: bool = True) -> Path:
    csv_dir = tmp_path / "CORE" / "data"
    csv_dir.mkdir(parents=True)
    reports = tmp_path / "CORE" / "reports"
    reports.mkdir()
    split_dates = {
        "TRAIN": ("2019-01-01", "2020-12-31"),
        "VALIDATION": ("2021-01-01", "2021-12-31"),
        "SELECTION": ("2022-01-01", "2022-12-31"),
        "TEST": ("2023-01-01", "2023-12-31"),
        "OOS": ("2024-01-01", "2026-10-08"),
    }
    plan = {
        "status": "PASS",
        "splits": {
            name: {"start_date": span[0], "end_date": span[1]}
            for name, span in split_dates.items()
        },
    }
    (reports / "TEMPORAL_SPLIT_plan.json").write_text(json.dumps(plan))
    if with_decisions:
        signature = offline.split_id(plan)
        for name in ("CORE-005_decision.json", "CORE-010_decision.json"):
            (reports / name).write_text(
                json.dumps({"status": "PASS", "split_id": signature})
            )
    return tmp_path


def put_rows(root: Path, rows: list[dict[str, str]]) -> Path:
    src = root / "CORE" / "data" / "CORE-010_calibrated_probabilities.csv"
    with src.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=sorted(offline.REQUIRED))
        writer.writeheader()
        writer.writerows(rows)
    return src


def row(race: str, horse: str, dt: str, win: int, top2: int, top3: int,
        pw: float, p2: float, p3: float, scope: str = "1") -> dict[str, str]:
    return {
        "race_id": race,
        "race_horse_id": horse,
        "race_date": dt,
        "race_scope_cd": scope,
        "label_win": f"{win}.0",
        "label_top2": f"{top2}.0",
        "label_top3": f"{top3}.0",
        "p_win": str(pw),
        "p_win_cal": str(pw),
        "p_top2_cal": str(p2),
        "p_top3_cal": str(p3),
    }


def test_reads_only_test_and_oos_and_aggregates_three_targets(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    src = put_rows(root, [
        row("R_TRAIN", "H0", "2019-01-04", 1, 1, 1, .98, .99, 1),
        row("R_TEST", "H1", "2023-01-04", 1, 1, 1, .7, .8, .9),
        row("R_TEST", "H2", "2023-01-04", 0, 1, 1, .3, .5, .6),
        row("R_OOS", "H3", "2024-02-05", 1, 1, 1, .4, .5, .6, "2"),
        row("R_OOS", "H4", "2024-02-05", 0, 0, 0, .6, .7, .8, "2"),
    ])

    meta, windows = offline.provenance(root)
    result = offline.evaluate_csv(src, meta, windows)

    assert result["status"] == "HOLDOUT_CONTRACT_MATCHED"
    assert result["rows_by_split"] == {"OOS": 2, "TEST": 2, "TRAIN": 1}
    assert result["races_with_top1"] == 2
    assert not result["safety"]["database_accessed"]
    assert not result["safety"]["horse_rows_output"]
    assert result["assessment_scope"] == "ALL_SURFACES; NO_P7_9_OR_DIRT_SLICE"
    assert "p_win desc" in result["model_top1_order"]

    by_key = {
        (item["split"], item["year"], item["organizer"]): item
        for item in result["by_split_year_scope"]
    }
    test = by_key["TEST", "ALL", "JRA"]
    assert test["base"]["win"]["actual_rate"] == .5
    assert test["base"]["top2"]["actual_rate"] == 1
    assert test["base"]["top3"]["actual_rate"] == 1
    assert test["model_top1"]["win"]["actual_rate"] == 1
    assert test["top1_lift_vs_all_runners"]["win"] == 2

    oos = by_key["OOS", "ALL", "NAR"]
    assert oos["base"]["win"]["actual_rate"] == .5
    assert oos["model_top1"]["win"]["actual_rate"] == 0
    assert oos["model_top1"]["top2"]["actual_rate"] == 0
    assert oos["model_top1"]["top3"]["actual_rate"] == 0
    assert oos["top1_lift_vs_all_runners"]["win"] == 0


def test_provenance_missing_is_not_promoted_to_holdout(tmp_path: Path) -> None:
    root = make_root(tmp_path, with_decisions=False)
    src = put_rows(root, [
        row("R1", "H1", "2024-01-03", 1, 1, 1, .8, .9, 1),
    ])
    meta, windows = offline.provenance(root)
    result = offline.evaluate_csv(src, meta, windows)

    assert meta["status"] == "DIAGNOSTIC_ONLY"
    assert result["status"] == "DIAGNOSTIC_ONLY"
    assert len(meta["reason"]) >= 1


def test_duplicate_runner_rejected(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    value = row("R1", "H1", "2024-01-03", 1, 1, 1, .8, .9, 1)
    src = put_rows(root, [value, value])
    meta, windows = offline.provenance(root)
    with pytest.raises(ValueError, match="duplicate race_id"):
        offline.evaluate_csv(src, meta, windows)


def test_non_monotonic_target_and_invalid_label_fail_partial(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    src = put_rows(root, [
        row("R1", "H1", "2024-01-03", 1, 1, 1, .8, .7, .9),
        row("R2", "H2", "2024-01-04", 1, 1, 1, .8, .9, 1),
    ])
    meta, windows = offline.provenance(root)
    result = offline.evaluate_csv(src, meta, windows)
    assert result["status"] == "PARTIAL_INVALID_ROWS"
    assert result["invalid_row_types"]["ValueError"] == 1


def test_no_oos_is_blocked(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    src = put_rows(root, [
        row("R1", "H1", "2023-01-03", 1, 1, 1, .8, .9, 1),
    ])
    meta, windows = offline.provenance(root)
    result = offline.evaluate_csv(src, meta, windows)
    assert result["status"] == "BLOCKED_NO_OOS"


def test_signature_mismatch_prevents_official_status(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    d = root / "CORE" / "reports" / "CORE-010_decision.json"
    d.write_text(json.dumps({"status": "PASS", "split_id": "WRONG"}))
    meta, _ = offline.provenance(root)
    assert not meta["verified"]
    assert "CORE-010 decision split signature mismatch" in meta["reason"]



def test_float_race_scope_and_raw_score_break_calibrated_ties(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    best = row("R_TIE", "H2", "2024-01-05", 1, 1, 1, .71, .8, .9, "1.0")
    worst = row("R_TIE", "H1", "2024-01-05", 0, 0, 0, .31, .8, .9, "1.0")
    best["p_win_cal"] = ".45"
    worst["p_win_cal"] = ".45"
    src = put_rows(root, [best, worst])
    meta, windows = offline.provenance(root)
    report = offline.evaluate_csv(src, meta, windows)
    oos = next(
        x for x in report["by_split_year_scope"]
        if x["split"] == "OOS" and x["year"] == "ALL"
        and x["organizer"] == "JRA"
    )
    assert oos["model_top1"]["win"]["actual_rate"] == 1
    assert report["status"] == "HOLDOUT_CONTRACT_MATCHED"
