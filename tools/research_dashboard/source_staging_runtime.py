from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from source_adapter_runtime import canonical_mapping_from_contract, qualified_table, quote_ident, validate_identifier

REQUIRED_CANONICAL = [
    "race_id",
    "race_horse_id",
    "horse_id",
    "race_date",
    "race_scope_cd",
    "label_win",
    "label_top2",
    "label_top3",
]


def now() -> str:
    return datetime.now().astimezone().isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def validate_export_contract(contract: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if contract.get("enabled") is not True:
        issues.append("contract_disabled")
    if contract.get("rights_status") not in {"APPROVED", "APPROVED_INTERNAL"}:
        issues.append("rights_not_approved")
    source = contract.get("source") or {}
    if str(source.get("engine") or "").upper() not in {"POSTGRES", "MYSQL"}:
        issues.append("unsupported_engine")
    for key in ("schema", "table"):
        if not source.get(key):
            issues.append(f"missing_source_{key}")
        else:
            try:
                validate_identifier(str(source[key]))
            except Exception:
                issues.append(f"unsafe_source_{key}")
    mapping = canonical_mapping_from_contract(contract)
    for target in REQUIRED_CANONICAL:
        if target not in mapping:
            issues.append(f"missing_mapping:{target}")
    for src in mapping.values():
        try:
            validate_identifier(src)
        except Exception:
            issues.append(f"unsafe_column:{src}")
    if contract.get("export_enabled") is False:
        issues.append("export_disabled")
    return sorted(set(issues))


def build_partition_query(contract: dict[str, Any], start_date: str, end_date: str) -> tuple[str, list[str]]:
    source = contract["source"]
    engine = str(source["engine"]).upper()
    schema = str(source["schema"])
    table = str(source["table"])
    mapping = canonical_mapping_from_contract(contract)
    qtable = qualified_table(engine, schema, table)
    selected_targets = list(mapping.keys())
    selected_targets.sort(key=lambda x: (x not in REQUIRED_CANONICAL, x))
    exprs: list[str] = []
    for canonical in selected_targets:
        src = quote_ident(engine, mapping[canonical])
        alias = quote_ident(engine, canonical)
        exprs.append(f"{src} AS {alias}")
    date_col = quote_ident(engine, mapping["race_date"])
    p1 = "%s"
    p2 = "%s"
    query = (
        f"SELECT {', '.join(exprs)} FROM {qtable} "
        f"WHERE CAST({date_col} AS DATE) >= {p1} AND CAST({date_col} AS DATE) < {p2} "
        f"ORDER BY CAST({date_col} AS DATE)"
    )
    return query, selected_targets


def partition_key(source_id: str, start_date: str, end_date: str) -> str:
    raw = f"{source_id}|{start_date}|{end_date}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def write_parquet_rows(path: Path, rows: list[tuple[Any, ...]], columns: list[str]) -> int:
    if not rows:
        return 0
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        data = {name: [row[i] for row in rows] for i, name in enumerate(columns)}
        table = pa.table(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression="zstd")
        return table.num_rows
    except ImportError:
        import pandas as pd

        df = pd.DataFrame(rows, columns=columns)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, compression="zstd", index=False)
        return len(df)


def manifest_for_partition(path: Path, source_id: str, start_date: str, end_date: str, rows: int, columns: list[str], query_hash: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "start_date": start_date,
        "end_date": end_date,
        "rows": rows,
        "columns": columns,
        "path": str(path),
        "sha256": sha256_file(path) if path.exists() else None,
        "query_sha256": query_hash,
        "created_at": now(),
        "status": "PASS" if rows >= 0 else "BLOCKED",
    }


def query_sha256(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()
