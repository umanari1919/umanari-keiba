from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "tools" / "research_dashboard"
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))


def load(name: str):
    path = LAB / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_modern_data_engine_contract():
    mod = load("modern_data_engine")
    caps = mod.capabilities()
    assert set(caps) == {"duckdb", "polars", "pyarrow"}
    assert all(isinstance(v, bool) for v in caps.values())


def test_dependency_guard_targets_are_stable_only():
    mod = load("dependency_guard")
    assert "polars" in mod.TARGETS
    assert "duckdb" in mod.TARGETS
    assert "numpy" in mod.TARGETS
    assert "pandas" in mod.TARGETS
    for meta in mod.TARGETS.values():
        version = meta["target"].lower()
        assert all(x not in version for x in ("rc", "alpha", "beta", "a1", "b1", "dev"))


def test_pydantic_and_pandera_contracts_accept_valid_canonical_data():
    mod = load("modern_contracts")
    contract = {
        "source_id": "TEST",
        "enabled": True,
        "domain": "MIXED",
        "provenance": "unit-test",
        "rights_status": "APPROVED_INTERNAL",
        "column_map": {"a": "race_id"},
        "defaults": {},
    }
    issues, engine = mod.validate_adapter_contract(contract)
    assert engine == "PYDANTIC"
    assert issues == []
    df = pd.DataFrame({
        "race_id": ["R1", "R1"],
        "race_horse_id": ["R1-H1", "R1-H2"],
        "horse_id": ["H1", "H2"],
        "race_date": ["2026-01-01", "2026-01-01"],
        "race_scope_cd": [1, 2],
        "label_win": [1, 0],
        "label_top2": [1, 1],
        "label_top3": [1, 1],
    })
    data_issues, data_engine = mod.validate_core003b_frame(df)
    assert data_engine == "PANDERA"
    assert data_issues == []


def test_optuna5_advisor_uses_selection_metric_only():
    mod = load("hypothesis_generator")
    rows=[]
    for i in range(12):
        rows.append({
            "status": "KEEP",
            "target": "label_win",
            "feature_set": "FIELD",
            "depth": 4 + (i % 4),
            "lr": 0.02 + i * 0.001,
            "l2": 4.0 + (i % 5),
            "iters": 600 + i * 20,
            "selection_logloss": 0.60 - i * 0.005,
            "test_logloss": 0.40 + i * 0.01,
            "oos_logloss_report_only": 0.30 + i * 0.02,
        })
    candidates = mod.build_optuna_candidates(pd.DataFrame(rows))
    assert candidates
    assert all(c["source"] == "OPTUNA5_TPE" for c in candidates)
    assert all(c["optimization_metric"] == "SELECTION_LOGLOSS_ONLY" for c in candidates)


def test_research_lab_python_files_parse():
    import ast
    for path in LAB.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
