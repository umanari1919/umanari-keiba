from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "tools" / "research_dashboard"


def load(name: str):
    path = LAB / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
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
    for meta in mod.TARGETS.values():
        version = meta["target"].lower()
        assert all(x not in version for x in ("rc", "alpha", "beta", "a1", "b1"))


def test_research_lab_python_files_parse():
    import ast
    for path in LAB.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
