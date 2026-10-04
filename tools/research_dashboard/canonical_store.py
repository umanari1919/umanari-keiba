from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("THE_JOCKEY_RESEARCH_ROOT", Path.home() / "Downloads" / "THE-JOCKEY-RESEARCH"))
STORE = ROOT / "CORE" / "canonical_store"
VERSIONS = STORE / "versions"
CURRENT = STORE / "current.json"
VERSIONS.mkdir(parents=True, exist_ok=True)

REQUIRED = {
    "race_id", "race_horse_id", "horse_id", "race_date", "race_scope_cd",
    "label_win", "label_top2", "label_top3",
}


def now() -> str:
    return datetime.now().astimezone().isoformat()


def _write_json_atomic(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _duckdb():
    import duckdb
    return duckdb


def _lit(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def relation_sql(path: Path) -> str:
    path = Path(path)
    if path.suffix.lower() == ".parquet":
        return f"read_parquet({_lit(path)})"
    return f"read_csv_auto({_lit(path)}, header=true, sample_size=-1)"


def dataset_columns(path: Path) -> list[str]:
    con = _duckdb().connect()
    try:
        return [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {relation_sql(path)}").fetchall()]
    finally:
        con.close()


def dataset_stats(path: Path) -> dict[str, Any]:
    cols = set(dataset_columns(path))
    races = "count(distinct cast(race_id as varchar))" if "race_id" in cols else "0"
    horses = "count(distinct cast(horse_id as varchar))" if "horse_id" in cols else "0"
    con = _duckdb().connect()
    try:
        row = con.execute(
            f"""
            SELECT count(*) AS row_count,
                   {races} AS race_count,
                   {horses} AS horse_count,
                   sum(case when cast(race_scope_cd as varchar) in ('1','1.0','JRA') then 1 else 0 end) AS jra_row_count,
                   sum(case when cast(race_scope_cd as varchar) in ('2','2.0','NAR') then 1 else 0 end) AS nar_row_count,
                   min(try_cast(race_date as date)) AS min_date,
                   max(try_cast(race_date as date)) AS max_date
            FROM {relation_sql(path)}
            """
        ).fetchone()
        return {
            "rows": int(row[0] or 0), "races": int(row[1] or 0), "horses": int(row[2] or 0),
            "jra_rows": int(row[3] or 0), "nar_rows": int(row[4] or 0),
            "min_date": str(row[5]) if row[5] else "", "max_date": str(row[6]) if row[6] else "",
        }
    finally:
        con.close()


def validate_dataset(path: Path, expected_columns: list[str] | None = None) -> dict[str, Any]:
    cols = dataset_columns(path)
    issues: list[str] = []
    if not REQUIRED.issubset(cols):
        issues.append("missing_required:" + ",".join(sorted(REQUIRED - set(cols))))
    if expected_columns is not None and cols != expected_columns:
        issues.append("schema_mismatch")
    if issues:
        return {"status": "BLOCKED", "issues": issues, "columns": cols}

    con = _duckdb().connect()
    try:
        row = con.execute(
            f"""
            SELECT
              count(*) FILTER (WHERE race_horse_id IS NULL) AS null_race_horse_id,
              count(*) - count(distinct cast(race_horse_id as varchar)) AS duplicate_race_horse_id,
              count(*) FILTER (WHERE try_cast(race_date as date) IS NULL) AS invalid_race_date,
              count(*) FILTER (
                WHERE race_scope_cd IS NULL
                   OR cast(race_scope_cd as varchar) NOT IN ('1','1.0','2','2.0','JRA','NAR')
              ) AS invalid_scope,
              count(*) FILTER (
                WHERE try_cast(label_win as double) IS NULL OR try_cast(label_win as double) NOT IN (0,1)
              ) AS invalid_win,
              count(*) FILTER (
                WHERE try_cast(label_top2 as double) IS NULL OR try_cast(label_top2 as double) NOT IN (0,1)
              ) AS invalid_top2,
              count(*) FILTER (
                WHERE try_cast(label_top3 as double) IS NULL OR try_cast(label_top3 as double) NOT IN (0,1)
              ) AS invalid_top3,
              count(*) FILTER (
                WHERE try_cast(label_win as double) > try_cast(label_top2 as double)
                   OR try_cast(label_top2 as double) > try_cast(label_top3 as double)
              ) AS label_monotonicity
            FROM {relation_sql(path)}
            """
        ).fetchone()
    finally:
        con.close()
    names = [
        "null_race_horse_id", "duplicate_race_horse_id", "invalid_race_date", "invalid_scope",
        "invalid_win", "invalid_top2", "invalid_top3", "label_monotonicity",
    ]
    checks = {k: int(v or 0) for k, v in zip(names, row)}
    issues.extend([f"{k}:{v}" for k, v in checks.items() if v])
    return {
        "status": "PASS" if not issues else "BLOCKED",
        "issues": issues, "checks": checks, "columns": cols, "stats": dataset_stats(path),
    }


def current_pointer() -> dict[str, Any] | None:
    if not CURRENT.exists():
        return None
    try:
        payload = json.loads(CURRENT.read_text(encoding="utf-8-sig"))
    except Exception as e:
        raise RuntimeError(f"invalid canonical current pointer: {e}") from e
    if not payload.get("version_id"):
        raise RuntimeError("canonical current pointer missing version_id")
    return payload


def current_manifest() -> dict[str, Any] | None:
    ptr = current_pointer()
    if ptr is None:
        return None
    path = VERSIONS / str(ptr["version_id"]) / "manifest.json"
    if not path.exists():
        raise RuntimeError(f"canonical manifest missing for current version: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        raise RuntimeError(f"invalid canonical manifest: {e}") from e
    if manifest.get("version_id") != ptr.get("version_id"):
        raise RuntimeError("canonical pointer/manifest version mismatch")
    return manifest


def current_data_path() -> Path | None:
    manifest = current_manifest()
    if manifest is None:
        return None
    path = Path(str(manifest.get("data_path") or ""))
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise RuntimeError(f"canonical data missing for current version: {path}")
    return path


def resolve_canonical_source(legacy_source: Path) -> Path:
    path = current_data_path()
    return path if path is not None else Path(legacy_source)


def canonical_source_signature(legacy_source: Path) -> str | None:
    manifest = current_manifest()
    if manifest is not None:
        path = current_data_path()
        return f"CANONICAL:{manifest.get('version_id')}:{manifest.get('data_sha256','')}:{path.name}"
    legacy = Path(legacy_source)
    if not legacy.exists():
        return None
    st = legacy.stat()
    return f"LEGACY:{st.st_size}:{st.st_mtime_ns}"


def read_pandas(path: Path):
    import pandas as pd
    return pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path, low_memory=False)


def _version_id(parts: list[str]) -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f%z")
    token = hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]
    return f"v{stamp}-{token}"


def _promote_build(build_dir: Path, final_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if final_dir.exists():
        raise RuntimeError(f"canonical version already exists: {final_dir}")
    _write_json_atomic(build_dir / "manifest.json", manifest)
    build_dir.replace(final_dir)
    previous = current_pointer()
    _write_json_atomic(CURRENT, {
        "version_id": manifest["version_id"], "updated": now(),
        "previous_version_id": (previous or {}).get("version_id"),
        "manifest": str((final_dir / "manifest.json").relative_to(ROOT)),
    })
    return manifest


def _active_fingerprint(path: Path) -> str:
    try:
        manifest = current_manifest()
        active = current_data_path()
        if manifest and active and Path(path).resolve() == active.resolve() and manifest.get("data_sha256"):
            return str(manifest["data_sha256"])
    except Exception:
        raise
    return sha256_file(path)


def bootstrap_from_legacy(source: Path) -> dict[str, Any] | None:
    existing = current_data_path()
    if existing is not None:
        return current_manifest()
    source = Path(source)
    if not source.exists():
        return None
    source_sha = sha256_file(source)
    version_id = _version_id(["BOOTSTRAP", source_sha])
    build_dir = VERSIONS / f".building-{version_id}"
    final_dir = VERSIONS / version_id
    shutil.rmtree(build_dir, ignore_errors=True)
    build_dir.mkdir(parents=True)
    dest = build_dir / "canonical.parquet"
    con = _duckdb().connect()
    try:
        con.execute(f"COPY (SELECT * FROM {relation_sql(source)}) TO {_lit(dest)} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)")
    finally:
        con.close()
    audit = validate_dataset(dest)
    if audit["status"] != "PASS":
        shutil.rmtree(build_dir, ignore_errors=True)
        raise RuntimeError(f"bootstrap canonical validation failed: {audit['issues']}")
    manifest = {
        "version_id": version_id, "created_at": now(), "parent_version_id": None,
        "mode": "BOOTSTRAP_LEGACY",
        "data_path": str((final_dir / "canonical.parquet").relative_to(ROOT)),
        "data_sha256": sha256_file(dest),
        "source_artifacts": [{"path": str(source), "sha256": source_sha}],
        "audit": audit,
        "policy": "immutable version; current pointer promoted only after complete validation",
    }
    return _promote_build(build_dir, final_dir, manifest)


def overlap_count(base: Path, candidate: Path) -> int:
    con = _duckdb().connect()
    try:
        row = con.execute(f"""
            SELECT count(*) AS overlap_count
            FROM {relation_sql(candidate)} c
            WHERE EXISTS (
              SELECT 1 FROM {relation_sql(base)} b
              WHERE cast(b.race_horse_id as varchar)=cast(c.race_horse_id as varchar)
            )
        """).fetchone()
        return int(row[0] or 0)
    finally:
        con.close()


def build_merged_version(base: Path, candidates: list[Path]) -> dict[str, Any]:
    base = Path(base)
    candidates = [Path(p) for p in candidates]
    if not candidates:
        raise ValueError("no candidates")
    base_cols = dataset_columns(base)
    base_audit = validate_dataset(base, base_cols)
    if base_audit["status"] != "PASS":
        raise RuntimeError(f"base validation failed: {base_audit['issues']}")

    fingerprints = [_active_fingerprint(base)]
    candidate_meta = []
    for p in candidates:
        audit = validate_dataset(p, base_cols)
        if audit["status"] != "PASS":
            raise RuntimeError(f"candidate validation failed {p}: {audit['issues']}")
        digest = sha256_file(p)
        fingerprints.append(digest)
        candidate_meta.append({"path": str(p), "sha256": digest, "audit": audit})

    version_id = _version_id(["MERGE", *fingerprints])
    build_dir = VERSIONS / f".building-{version_id}"
    final_dir = VERSIONS / version_id
    shutil.rmtree(build_dir, ignore_errors=True)
    build_dir.mkdir(parents=True)
    dest = build_dir / "canonical.parquet"

    pieces = [f"SELECT *, 0 AS __priority, 0 AS __source_order FROM {relation_sql(base)}"]
    for i, p in enumerate(candidates, start=1):
        pieces.append(f"SELECT *, 1 AS __priority, {i} AS __source_order FROM {relation_sql(p)}")
    projected = ", ".join('"' + c.replace('"', '""') + '"' for c in base_cols)
    merge_sql = f"""
      SELECT {projected}
      FROM ({' UNION ALL '.join(pieces)}) u
      QUALIFY row_number() OVER (
        PARTITION BY cast(race_horse_id as varchar)
        ORDER BY __priority, __source_order
      ) = 1
    """
    con = _duckdb().connect()
    try:
        con.execute(f"COPY ({merge_sql}) TO {_lit(dest)} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)")
    finally:
        con.close()

    audit = validate_dataset(dest, base_cols)
    if audit["status"] != "PASS":
        shutil.rmtree(build_dir, ignore_errors=True)
        raise RuntimeError(f"merged canonical validation failed: {audit['issues']}")
    base_rows = int(base_audit["stats"]["rows"])
    merged_rows = int(audit["stats"]["rows"])
    if merged_rows < base_rows:
        shutil.rmtree(build_dir, ignore_errors=True)
        raise RuntimeError(f"row regression: base={base_rows} merged={merged_rows}")

    parent = current_manifest()
    manifest = {
        "version_id": version_id, "created_at": now(),
        "parent_version_id": (parent or {}).get("version_id"), "mode": "MERGE",
        "data_path": str((final_dir / "canonical.parquet").relative_to(ROOT)),
        "data_sha256": sha256_file(dest),
        "base": {"path": str(base), "sha256": fingerprints[0], "rows": base_rows},
        "candidates": candidate_meta, "added_rows": merged_rows - base_rows,
        "audit": audit,
        "policy": "immutable version; base rows have precedence on duplicate race_horse_id; current pointer updates atomically after validation",
    }
    return _promote_build(build_dir, final_dir, manifest)


def rollback(version_id: str) -> dict[str, Any]:
    final_dir = VERSIONS / version_id
    manifest_path = final_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    data = final_dir / "canonical.parquet"
    audit = validate_dataset(data)
    if audit["status"] != "PASS":
        raise RuntimeError(f"rollback target invalid: {audit['issues']}")
    previous = current_pointer()
    _write_json_atomic(CURRENT, {
        "version_id": version_id, "updated": now(),
        "previous_version_id": (previous or {}).get("version_id"),
        "manifest": str(manifest_path.relative_to(ROOT)), "rollback": True,
    })
    return manifest
