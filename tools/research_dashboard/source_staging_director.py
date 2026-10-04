from __future__ import annotations

import json
import os
import shutil
import time
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any

from source_adapter_director import _mysql_connection, _postgres_connection, load_contracts
from source_staging_runtime import (
    atomic_json,
    build_partition_query,
    manifest_for_partition,
    partition_key,
    query_sha256,
    validate_export_contract,
)

ROOT = Path(os.environ.get("THE_JOCKEY_RESEARCH_ROOT", Path.home() / "Downloads" / "THE-JOCKEY-RESEARCH"))
REPORTS = ROOT / "CORE" / "reports"
STAGING = ROOT / "staging" / "source_partitions"
CHECK = ROOT / "checkpoints"
LOG = ROOT / "logs" / "source_staging_director.log"
STATE = CHECK / "source_staging_director_state.json"
SUMMARY = REPORTS / "SOURCE_STAGING_summary.json"
MANIFEST = REPORTS / "SOURCE_STAGING_manifest.json"
INTERVAL = max(300, int(os.environ.get("THE_JOCKEY_SOURCE_STAGING_INTERVAL", "1800")))
CHUNK_ROWS = max(1000, int(os.environ.get("THE_JOCKEY_SOURCE_STAGING_CHUNK_ROWS", "50000")))
MIN_FREE_GB = max(2.0, float(os.environ.get("THE_JOCKEY_SOURCE_STAGING_MIN_FREE_GB", "10")))
START_YEAR = int(os.environ.get("THE_JOCKEY_SOURCE_STAGING_START_YEAR", "1986"))
CURRENT_YEAR = datetime.now().year

for p in (REPORTS, STAGING, CHECK, LOG.parent):
    p.mkdir(parents=True, exist_ok=True)


def now() -> str:
    return datetime.now().astimezone().isoformat()


def log(message: str) -> None:
    line = f"[{now()}] {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def write_state(status: str, detail: str = "", extra: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"pid": os.getpid(), "updated": now(), "status": status, "detail": detail}
    if extra:
        payload.update(extra)
    atomic_json(STATE, payload)


def free_gb() -> float:
    usage = shutil.disk_usage(STAGING)
    return usage.free / (1024 ** 3)


def eligible_contracts() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for contract in load_contracts():
        issues = validate_export_contract(contract)
        if issues:
            blocked.append({"source_id": contract.get("source_id"), "issues": issues})
        else:
            ready.append(contract)
    return ready, blocked


def years_for(contract: dict[str, Any]) -> list[int]:
    limits = contract.get("export_window") or {}
    lo = int(limits.get("start_year", START_YEAR))
    hi = int(limits.get("end_year", CURRENT_YEAR))
    lo = max(1900, lo)
    hi = min(CURRENT_YEAR, hi)
    return list(range(lo, hi + 1)) if lo <= hi else []


def open_source(contract: dict[str, Any]):
    engine = str((contract.get("source") or {}).get("engine") or "").upper()
    if engine == "POSTGRES":
        return _postgres_connection()
    if engine == "MYSQL":
        return _mysql_connection()
    raise RuntimeError(f"unsupported engine: {engine}")


def write_cursor_to_parquet(cur, columns: list[str], output: Path) -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq

    tmp = output.with_suffix(".parquet.building")
    if tmp.exists():
        tmp.unlink()
    writer = None
    total = 0
    try:
        while True:
            rows = cur.fetchmany(CHUNK_ROWS)
            if not rows:
                break
            arrays = {name: [row[i] for row in rows] for i, name in enumerate(columns)}
            table = pa.table(arrays)
            if writer is None:
                writer = pq.ParquetWriter(tmp, table.schema, compression="zstd")
            writer.write_table(table)
            total += table.num_rows
        if writer is not None:
            writer.close()
            writer = None
        else:
            empty = pa.table({name: pa.array([], type=pa.string()) for name in columns})
            pq.write_table(empty, tmp, compression="zstd")
        tmp.replace(output)
        return total
    finally:
        if writer is not None:
            writer.close()
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def extract_partition(con, contract: dict[str, Any], year: int) -> dict[str, Any]:
    source_id = str(contract["source_id"])
    start = date(year, 1, 1).isoformat()
    end = date(year + 1, 1, 1).isoformat()
    key = partition_key(source_id, start, end)
    part_dir = STAGING / source_id / f"year={year}"
    part_dir.mkdir(parents=True, exist_ok=True)
    output = part_dir / f"part-{key}.parquet"
    meta_path = part_dir / f"part-{key}.manifest.json"
    query, columns = build_partition_query(contract, start, end)
    qsha = query_sha256(query)

    if output.exists() and meta_path.exists():
        try:
            old = json.loads(meta_path.read_text(encoding="utf-8-sig"))
            if old.get("status") == "PASS" and old.get("query_sha256") == qsha and old.get("sha256"):
                return {**old, "action": "RESUME_SKIP"}
        except Exception:
            pass

    if free_gb() < MIN_FREE_GB:
        return {
            "source_id": source_id,
            "year": year,
            "status": "HOLD",
            "reason": "LOW_DISK_SPACE",
            "free_gb": round(free_gb(), 2),
        }

    cur = con.cursor()
    try:
        cur.execute(query, (start, end))
        rows = write_cursor_to_parquet(cur, columns, output)
    finally:
        cur.close()
    manifest = manifest_for_partition(output, source_id, start, end, rows, columns, qsha)
    manifest["year"] = year
    manifest["action"] = "EXTRACTED"
    atomic_json(meta_path, manifest)
    return manifest


def run_once() -> dict[str, Any]:
    ready, blocked = eligible_contracts()
    partitions: list[dict[str, Any]] = []
    source_summaries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if not ready:
        out = {
            "updated": now(),
            "status": "WAITING",
            "ready_contracts": 0,
            "blocked_contracts": blocked,
            "partitions": [],
            "next_action": "APPROVE_SOURCE_ADAPTER_CONTRACT_OR_WAIT_FOR_DISCOVERY",
        }
        atomic_json(MANIFEST, out)
        atomic_json(SUMMARY, out)
        write_state("WAITING", out["next_action"], {"ready_contracts": 0})
        return out

    for contract in ready:
        source_id = str(contract.get("source_id"))
        con = None
        done = 0
        skipped = 0
        held = 0
        try:
            con, meta = open_source(contract)
            for year in years_for(contract):
                item = extract_partition(con, contract, year)
                partitions.append(item)
                if item.get("action") == "EXTRACTED":
                    done += 1
                elif item.get("action") == "RESUME_SKIP":
                    skipped += 1
                elif item.get("status") == "HOLD":
                    held += 1
                    break
            source_summaries.append({
                "source_id": source_id,
                "engine": (contract.get("source") or {}).get("engine"),
                "database": (contract.get("source") or {}).get("database"),
                "extracted_partitions": done,
                "resumed_partitions": skipped,
                "held_partitions": held,
            })
        except Exception as exc:
            errors.append({"source_id": source_id, "error": f"{type(exc).__name__}:{str(exc)[:1000]}"})
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

    status = "PARTIAL" if errors else ("HOLD" if any(x.get("status") == "HOLD" for x in partitions) else "PASS")
    out = {
        "updated": now(),
        "status": status,
        "ready_contracts": len(ready),
        "blocked_contracts": blocked,
        "sources": source_summaries,
        "partitions": partitions,
        "errors": errors,
        "chunk_rows": CHUNK_ROWS,
        "min_free_gb": MIN_FREE_GB,
        "staging_root": str(STAGING),
        "next_action": "CANONICALIZATION" if status == "PASS" else "REPAIR_STAGING_OR_RESOURCE_CONSTRAINT",
    }
    atomic_json(MANIFEST, out)
    atomic_json(SUMMARY, out)
    write_state(status, out["next_action"], {"ready_contracts": len(ready), "partition_count": len(partitions)})
    log(f"SOURCE STAGING {status} ready={len(ready)} partitions={len(partitions)} errors={len(errors)}")
    return out


def main() -> None:
    log("SOURCE STAGING DIRECTOR START")
    while True:
        try:
            run_once()
        except Exception:
            err = traceback.format_exc()
            log(err)
            write_state("BLOCKED", err[-1800:])
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
