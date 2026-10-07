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



def test_invalid_oos_race_excluded_from_clean_sensitivity(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    bad = row("R_OOS_BAD", "H2", "2024-01-06", 0, 0, 0, .8, .9, 1.0)
    bad["p_win_cal"] = "nan"
    src = put_rows(root, [
        row("R_OOS_BAD", "H1", "2024-01-06", 1, 1, 1, .6, .7, .8),
        bad,
        row("R_OOS_CLEAN", "H3", "2024-01-07", 1, 1, 1, .5, .7, .8),
        row("R_OOS_CLEAN", "H4", "2024-01-07", 0, 1, 1, .2, .4, .5),
    ])
    meta, windows = offline.provenance(root)
    output = offline.evaluate_csv(src, meta, windows)

    assert output["status"] == "PARTIAL_INVALID_ROWS"
    assert output["invalid_rows_total"] == 1
    assert output["invalid_row_reasons"]["INVALID_OR_NONMONOTONIC_PROBABILITIES"] == 1
    assert output["invalid_rows_by_split"]["OOS"] == 1
    assert output["known_invalid_test_oos_rows"] == 1
    clean = output["clean_race_sensitivity"]
    assert clean is not None
    assert clean["excluded_unique_race_ids"] == 1
    summary = next(
        item for item in clean["by_split_scope"]
        if item["split"] == "OOS" and item["organizer"] == "ALL"
    )
    assert summary["all_runners"] == 2
    assert summary["model_top1"] == 1
    assert summary["model_top1_rates"]["win"] == 1


def test_invalid_train_row_does_not_discard_holdout_cleanliness(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    bad = row("R_TRAIN", "H0", "2019-01-03", 1, 1, 1, .8, .9, 1.0)
    bad["label_win"] = ""
    src = put_rows(root, [
        bad,
        row("R_OOS", "H1", "2024-01-07", 1, 1, 1, .5, .7, .8),
    ])
    meta, windows = offline.provenance(root)
    output = offline.evaluate_csv(src, meta, windows)
    assert output["invalid_rows_total"] == 1
    assert output["invalid_rows_by_split"] == {"TRAIN": 1}
    assert output["known_invalid_test_oos_rows"] == 0
    assert output["clean_race_sensitivity"] is None
    assert output["status"] == "PARTIAL_INVALID_ROWS"


def test_invalid_unknown_date_requires_sensitivity(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    bad = row("R_DATE", "H1", "not-a-date", 1, 1, 1, .8, .9, 1.0)
    src = put_rows(root, [
        bad,
        row("R_DATE", "H2", "2024-01-08", 0, 0, 0, .2, .4, .6),
    ])
    meta, windows = offline.provenance(root)
    output = offline.evaluate_csv(src, meta, windows)
    assert output["invalid_rows_by_split"]["UNKNOWN_DATE"] == 1
    assert output["clean_race_sensitivity"]["excluded_unique_race_ids"] == 1
    assert output["clean_race_sensitivity"]["remaining_test_oos_races"] == 0
    assert output["status"] == "PARTIAL_INVALID_ROWS"



@pytest.mark.parametrize(
    ("column", "bad_value", "expected_reason"),
    [
        ("race_scope_cd", "", "INVALID_OR_MISSING_SCOPE"),
        ("label_win", "", "INVALID_OR_MISSING_OUTCOME_LABELS"),
        ("p_top3_cal", "", "INVALID_OR_NONMONOTONIC_PROBABILITIES"),
        ("p_win", "", "INVALID_RAW_WIN_SCORE"),
    ],
)
def test_invalid_input_reasons_are_safe_aggregates(
    tmp_path: Path,
    column: str,
    bad_value: str,
    expected_reason: str,
) -> None:
    root = make_root(tmp_path)
    invalid = row("R_BAD", "H0", "2024-01-06", 0, 0, 0, .3, .4, .5)
    invalid[column] = bad_value
    src = put_rows(root, [
        invalid,
        row("R_GOOD", "H1", "2024-01-07", 1, 1, 1, .5, .7, .8),
    ])
    meta, windows = offline.provenance(root)
    result = offline.evaluate_csv(src, meta, windows)
    assert result["invalid_row_reasons"] == {expected_reason: 1}
    assert result["invalid_rows_by_split"] == {"OOS": 1}
    assert result["status"] == "PARTIAL_INVALID_ROWS"
    assert result["safety"]["horse_rows_output"] is False



def test_scope_mix_standardization_decomposes_apparent_decline(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    rows: list[dict[str, str]] = []
    # TEST: 1 JRA and 3 NAR selected horses; all win.
    rows.append(row("TJ1", "H1", "2023-03-01", 1, 1, 1, .6, .8, .9, "1"))
    for i in range(3):
        rows.append(row(f"TN{i}", f"HN{i}", "2023-03-02", 1, 1, 1, .6, .8, .9, "2"))
    # OOS: 3 JRA selected horses lose, 1 NAR selected horse wins.
    for i in range(3):
        rows.append(row(f"OJ{i}", f"HJ{i}", "2024-03-02", 0, 0, 0, .6, .8, .9, "1"))
    rows.append(row("ON1", "HN1", "2024-03-02", 1, 1, 1, .6, .8, .9, "2"))
    src = put_rows(root, rows)
    meta, windows = offline.provenance(root)
    result = offline.evaluate_csv(src, meta, windows)
    comparison = result["scope_mix_comparison"]
    assert comparison["available"] is True
    assert comparison["test_top1_nar_share"] == pytest.approx(.75)
    assert comparison["oos_top1_nar_share"] == pytest.approx(.25)
    win = comparison["targets"]["win"]
    assert win["test_observed_rate"] == pytest.approx(1)
    assert win["oos_observed_rate"] == pytest.approx(.25)
    assert win["oos_at_test_scope_mix_rate"] == pytest.approx(.75)
    assert win["unadjusted_change_pp"] == pytest.approx(-75)
    assert win["scope_standardized_change_pp"] == pytest.approx(-25)
    assert win["scope_composition_contribution_pp"] == pytest.approx(-50)
    assert result["status"] == "HOLDOUT_CONTRACT_MATCHED"



def test_label_issue_subtypes_coverage_by_split_and_scope(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    blank_all = row("R1", "H1", "2024-01-10", 0, 0, 0, .3, .5, .7, "1")
    for col in ("label_win", "label_top2", "label_top3"):
        blank_all[col] = ""
    blank_one = row("R2", "H2", "2024-01-11", 0, 0, 0, .3, .5, .7, "2")
    blank_one["label_win"] = ""
    malformed = row("R3", "H3", "2023-01-12", 0, 0, 0, .3, .5, .7, "1")
    malformed["label_top2"] = "bad"
    nonbinary = row("R4", "H4", "2023-01-13", 0, 0, 0, .3, .5, .7, "2")
    nonbinary["label_top3"] = "2"
    contradictory = row("R5", "H5", "2024-01-14", 0, 0, 0, .3, .5, .7, "1")
    contradictory["label_win"] = "1"
    good = row("R6", "H6", "2024-01-15", 1, 1, 1, .4, .6, .8, "2")
    src = put_rows(root, [
        blank_all, blank_one, malformed, nonbinary, contradictory, good
    ])
    meta, windows = offline.provenance(root)
    result = offline.evaluate_csv(src, meta, windows)
    assert result["invalid_rows_total"] == 5
    assert result["label_issues_by_kind"] == {
        "ALL_THREE_LABELS_BLANK": 1,
        "ONE_LABEL_BLANK": 1,
        "NON_NUMERIC_LABEL": 1,
        "NON_BINARY_OR_NONFINITE_LABEL": 1,
        "NONMONOTONIC_TARGET_LABELS": 1,
    }
    assert result["label_issues_by_split"]["TEST"] == {
        "NON_BINARY_OR_NONFINITE_LABEL": 1,
        "NON_NUMERIC_LABEL": 1,
    }
    assert result["label_issues_by_split"]["OOS"] == {
        "ALL_THREE_LABELS_BLANK": 1,
        "NONMONOTONIC_TARGET_LABELS": 1,
        "ONE_LABEL_BLANK": 1,
    }
    assert result["label_issues_by_scope"]["JRA"] == {
        "ALL_THREE_LABELS_BLANK": 1,
        "NONMONOTONIC_TARGET_LABELS": 1,
        "NON_NUMERIC_LABEL": 1,
    }
    assert result["split_label_coverage"]["OOS"]["usable_row_coverage"] == pytest.approx(.25)
    assert result["split_label_coverage"]["TEST"]["usable_row_coverage"] == pytest.approx(0)
    assert result["invalid_affected_races_by_split"] == {"OOS": 3, "TEST": 2}
    assert result["status"] == "PARTIAL_INVALID_ROWS"


def test_two_missing_labels_not_misclassified_as_bad_value(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    missing = row("R7", "H7", "2024-01-17", 0, 0, 0, .3, .5, .7)
    missing["label_win"] = ""
    missing["label_top3"] = ""
    src = put_rows(root, [
        missing,
        row("R8", "H8", "2024-01-18", 1, 1, 1, .4, .6, .8),
    ])
    meta, windows = offline.provenance(root)
    result = offline.evaluate_csv(src, meta, windows)
    assert result["label_issues_by_kind"] == {"TWO_LABELS_BLANK": 1}



def test_only_all_three_blank_outcomes_are_quarantined_not_corruption(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    unlabelled = row("R_BLANK", "HB", "2024-04-02", 0, 0, 0, .20, .40, .60)
    for key in ("label_win", "label_top2", "label_top3"):
        unlabelled[key] = ""
    known = row("R_KNOWN", "HK", "2024-04-03", 1, 1, 1, .30, .50, .70)
    csv_file = put_rows(root, [known, unlabelled])
    original = csv_file.read_bytes()

    meta, windows = offline.provenance(root)
    report = offline.evaluate_csv(csv_file, meta, windows)

    assert report["status"] == "PARTIAL_UNLABELLED_OUTCOMES"
    assert report["unlabelled_outcome_rows"] == 1
    assert report["other_invalid_rows"] == 0
    assert report["outcome_status_known"] is False
    assert report["label_issues_by_kind"] == {"ALL_THREE_LABELS_BLANK": 1}
    assert report["clean_race_sensitivity"] is not None
    assert report["known_invalid_test_oos_rows"] == 1
    assert csv_file.read_bytes() == original
