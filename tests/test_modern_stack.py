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


def test_immutable_canonical_store_bootstrap_merge_and_rollback(tmp_path):
    mod = load("canonical_store")
    mod.ROOT = tmp_path
    mod.STORE = tmp_path / "CORE" / "canonical_store"
    mod.VERSIONS = mod.STORE / "versions"
    mod.CURRENT = mod.STORE / "current.json"
    mod.VERSIONS.mkdir(parents=True, exist_ok=True)

    cols = ["race_id","race_horse_id","horse_id","race_date","race_scope_cd","label_win","label_top2","label_top3","prior_start_count"]
    legacy = tmp_path / "legacy.csv"
    pd.DataFrame([
        ["R1","R1-H1","H1","2026-01-01",1,1,1,1,3],
        ["R1","R1-H2","H2","2026-01-01",1,0,1,1,4],
    ], columns=cols).to_csv(legacy,index=False)
    legacy_sha = mod.sha256_file(legacy)

    boot = mod.bootstrap_from_legacy(legacy)
    assert boot["mode"] == "BOOTSTRAP_LEGACY"
    assert boot["audit"]["status"] == "PASS"
    boot_version = boot["version_id"]
    assert mod.current_data_path().suffix == ".parquet"

    candidate = tmp_path / "candidate.csv"
    pd.DataFrame([
        ["R1","R1-H2","H2","2026-01-01",1,0,1,1,4],
        ["R2","R2-H3","H3","2026-01-02",2,1,1,1,2],
    ], columns=cols).to_csv(candidate,index=False)
    assert mod.overlap_count(mod.current_data_path(),candidate) == 1
    merged = mod.build_merged_version(mod.current_data_path(),[candidate])
    assert merged["audit"]["status"] == "PASS"
    assert merged["added_rows"] == 1
    assert merged["audit"]["stats"]["rows"] == 3
    assert merged["parent_version_id"] == boot_version
    assert mod.sha256_file(legacy) == legacy_sha

    mod.rollback(boot_version)
    assert mod.current_manifest()["version_id"] == boot_version
    assert mod.current_manifest()["audit"]["stats"]["rows"] == 2


def test_immutable_canonical_store_rejects_malformed_label(tmp_path):
    mod = load("canonical_store")
    mod.ROOT = tmp_path
    mod.STORE = tmp_path / "CORE" / "canonical_store"
    mod.VERSIONS = mod.STORE / "versions"
    mod.CURRENT = mod.STORE / "current.json"
    mod.VERSIONS.mkdir(parents=True, exist_ok=True)
    bad = tmp_path / "bad.csv"
    pd.DataFrame({
        "race_id":["R1"],"race_horse_id":["R1-H1"],"horse_id":["H1"],"race_date":["2026-01-01"],
        "race_scope_cd":[1],"label_win":["oops"],"label_top2":[1],"label_top3":[1],
    }).to_csv(bad,index=False)
    audit = mod.validate_dataset(bad)
    assert audit["status"] == "BLOCKED"
    assert any(x.startswith("invalid_win:") for x in audit["issues"])


def test_research_lab_python_files_parse():
    import ast
    for path in LAB.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
