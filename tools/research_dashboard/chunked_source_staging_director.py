from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("THE_JOCKEY_RESEARCH_ROOT", Path.home() / "Downloads" / "THE-JOCKEY-RESEARCH"))
CORE = ROOT / "CORE"
REPORTS = CORE / "reports"
CONTRACTS = CORE / "contracts" / "source_adapters"
STAGING = CORE / "source_staging"
CHECK = ROOT / "checkpoints"
LOG = ROOT / "logs" / "chunked_source_staging_director.log"
STATE = CHECK / "chunked_source_staging_director_state.json"
SUMMARY = REPORTS / "SOURCE_STAGING_summary.json"
INTERVAL = max(300, int(os.environ.get("THE_JOCKEY_SOURCE_STAGING_INTERVAL", "1800")))
CHUNK_ROWS = max(10000, int(os.environ.get("THE_JOCKEY_SOURCE_STAGING_CHUNK_ROWS", "100000")))
ALLOWED_RIGHTS = {"APPROVED", "APPROVED_INTERNAL"}

for p in (REPORTS, STAGING, CHECK, LOG.parent):
    p.mkdir(parents=True, exist_ok=True)


def now() -> str:
    return datetime.now().astimezone().isoformat()


def writej(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def log(msg: str) -> None:
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_contracts() -> list[dict[str, Any]]:
    out = []
    for path in sorted(CONTRACTS.glob("*.json")):
        try:
            obj = json.loads(path.read_text(encoding="utf-8-sig"))
            obj["__path"] = str(path)
            out.append(obj)
        except Exception as exc:
            log(f"CONTRACT_ERROR {path.name}: {exc!r}")
    return out


def eligible(contract: dict[str, Any]) -> tuple[bool, str]:
    if contract.get("enabled") is not True:
        return False, "CONTRACT_DISABLED"
    if contract.get("export_enabled") is not True:
        return False, "EXPORT_DISABLED"
    if contract.get("rights_status") not in ALLOWED_RIGHTS:
        return False, "RIGHTS_NOT_APPROVED"
    src = contract.get("source") or {}
    if str(src.get("engine") or "").upper() not in {"POSTGRES", "MYSQL"}:
        return False, "UNSUPPORTED_ENGINE"
    if not src.get("table"):
        return False, "TABLE_MISSING"
    if not isinstance(contract.get("column_map"), dict) or not contract["column_map"]:
        return False, "COLUMN_MAP_MISSING"
    return True, "READY"


def canonical_projection(contract: dict[str, Any]) -> list[tuple[str, str]]:
    mapping = contract["column_map"]
    pairs = []
    for source_name, canonical_name in mapping.items():
        if not isinstance(source_name, str) or not isinstance(canonical_name, str):
            raise ValueError("column_map must be string:string")
        pairs.append((source_name, canonical_name))
    return pairs


def connect(contract: dict[str, Any]):
    src = contract["source"]
    engine = str(src["engine"]).upper()
    database = str(src.get("database") or "")
    if engine == "POSTGRES":
        try:
            import psycopg
            con = psycopg.connect(host=os.environ.get("THE_JOCKEY_PG_HOST", "127.0.0.1"), port=int(os.environ.get("THE_JOCKEY_PG_PORT", "5433")), dbname=database or os.environ.get("THE_JOCKEY_PG_DB", "mykeibadb"), user=os.environ.get("THE_JOCKEY_PG_USER") or os.environ.get("PGUSER"), password=os.environ.get("THE_JOCKEY_PG_PASSWORD") or os.environ.get("PGPASSWORD"), connect_timeout=5)
            con.autocommit = True
            cur = con.cursor(); cur.execute("SET default_transaction_read_only = on"); cur.execute("SET statement_timeout = '60s'"); cur.close()
            return con, engine
        except ImportError:
            import psycopg2
            con = psycopg2.connect(host=os.environ.get("THE_JOCKEY_PG_HOST", "127.0.0.1"), port=int(os.environ.get("THE_JOCKEY_PG_PORT", "5433")), dbname=database or os.environ.get("THE_JOCKEY_PG_DB", "mykeibadb"), user=os.environ.get("THE_JOCKEY_PG_USER") or os.environ.get("PGUSER"), password=os.environ.get("THE_JOCKEY_PG_PASSWORD") or os.environ.get("PGPASSWORD"), connect_timeout=5)
            con.autocommit = True
            cur = con.cursor(); cur.execute("SET default_transaction_read_only = on"); cur.execute("SET statement_timeout = '60s'"); cur.close()
            return con, engine
    if not database:
        raise RuntimeError("MYSQL database must be explicit in contract")
    try:
        import pymysql
        con = pymysql.connect(host=os.environ.get("THE_JOCKEY_MYSQL_HOST", "127.0.0.1"), port=int(os.environ.get("THE_JOCKEY_MYSQL_PORT", "3306")), user=os.environ.get("THE_JOCKEY_MYSQL_USER") or os.environ.get("MYSQL_USER"), password=os.environ.get("THE_JOCKEY_MYSQL_PASSWORD") or os.environ.get("MYSQL_PWD"), database=database, connect_timeout=5, read_timeout=60, autocommit=True)
        return con, engine
    except ImportError:
        import mysql.connector
        con = mysql.connector.connect(host=os.environ.get("THE_JOCKEY_MYSQL_HOST", "127.0.0.1"), port=int(os.environ.get("THE_JOCKEY_MYSQL_PORT", "3306")), user=os.environ.get("THE_JOCKEY_MYSQL_USER") or os.environ.get("MYSQL_USER"), password=os.environ.get("THE_JOCKEY_MYSQL_PASSWORD") or os.environ.get("MYSQL_PWD"), database=database, connection_timeout=5, autocommit=True)
        return con, engine


def qi(engine: str, name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError(f"unsafe identifier: {name}")
    return f'"{name}"' if engine == "POSTGRES" else f'`{name}`'


def build_query(contract: dict[str, Any], engine: str, resume_after: str | None = None) -> tuple[str, list[str]]:
    src = contract["source"]
    pairs = canonical_projection(contract)
    cols = [f"{qi(engine, s)} AS {qi(engine, c)}" for s, c in pairs]
    schema = str(src.get("schema") or "public")
    table = str(src["table"])
    qualified = f"{qi(engine, schema)}.{qi(engine, table)}" if engine == "POSTGRES" else f"{qi(engine, table)}"
    canonical_names = {c for _, c in pairs}
    order_source = next((s for s, c in pairs if c == "race_horse_id"), None)
    if not order_source:
        raise ValueError("race_horse_id mapping required for resumable staging")
    where = ""
    params: list[str] = []
    if resume_after:
        ph = "%s"
        where = f" WHERE {qi(engine, order_source)} > {ph}"
        params.append(resume_after)
    query = f"SELECT {', '.join(cols)} FROM {qualified}{where} ORDER BY {qi(engine, order_source)}"
    required = {"race_id", "race_horse_id", "horse_id", "race_date", "race_scope_cd", "label_win", "label_top2", "label_top3"}
    missing = sorted(required - canonical_names)
    if missing:
        raise ValueError(f"canonical required mapping missing: {missing}")
    return query, params


def rows_to_parquet(columns: list[str], rows: list[tuple], path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.Table.from_pylist([dict(zip(columns, row)) for row in rows])
    pq.write_table(table, path, compression="zstd")


def stage_contract(contract: dict[str, Any]) -> dict[str, Any]:
    ok, reason = eligible(contract)
    source_id = str(contract.get("source_id") or "UNNAMED")
    if not ok:
        return {"source_id": source_id, "status": "SKIP", "reason": reason}

    root = STAGING / source_id
    parts = root / "parts"
    root.mkdir(parents=True, exist_ok=True); parts.mkdir(parents=True, exist_ok=True)
    checkpoint = root / "checkpoint.json"
    manifest_path = root / "manifest.json"
    cp = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {}
    resume_after = cp.get("last_race_horse_id")
    completed_parts = list(cp.get("parts") or [])

    con = None
    try:
        con, engine = connect(contract)
        query, params = build_query(contract, engine, resume_after)
        cur = con.cursor()
        cur.execute(query, tuple(params))
        columns = [d[0] for d in cur.description]
        total_new = 0
        part_index = len(completed_parts)
        last_key = resume_after
        while True:
            rows = cur.fetchmany(CHUNK_ROWS)
            if not rows:
                break
            part_index += 1
            tmp = parts / f"part-{part_index:06d}.parquet.tmp"
            final = parts / f"part-{part_index:06d}.parquet"
            rows_to_parquet(columns, rows, tmp)
            tmp.replace(final)
            digest = sha256(final)
            last_key = str(rows[-1][columns.index("race_horse_id")])
            meta = {"file": final.name, "rows": len(rows), "sha256": digest, "last_race_horse_id": last_key}
            completed_parts.append(meta)
            total_new += len(rows)
            writej(checkpoint, {"source_id": source_id, "updated": now(), "last_race_horse_id": last_key, "parts": completed_parts, "status": "IN_PROGRESS"})
        cur.close()
        manifest = {"source_id": source_id, "status": "READY", "updated": now(), "contract_path": contract.get("__path"), "engine": engine, "parts": completed_parts, "part_count": len(completed_parts), "rows": sum(int(x.get("rows", 0)) for x in completed_parts), "new_rows_this_run": total_new, "resume_key": last_key, "policy": "READ_ONLY_SOURCE; CHUNKED_PARQUET; SHA256; RESUMABLE; NO_DIRECT_CANONICAL_WRITE"}
        writej(manifest_path, manifest)
        writej(checkpoint, {**manifest, "status": "COMPLETE"})
        return manifest
    except Exception as exc:
        err = {"source_id": source_id, "status": "BLOCKED", "updated": now(), "error": f"{type(exc).__name__}:{str(exc)[:1000]}", "parts": completed_parts, "last_race_horse_id": resume_after}
        writej(checkpoint, err)
        return err
    finally:
        try:
            if con is not None:
                con.close()
        except Exception:
            pass


def run_once() -> dict[str, Any]:
    contracts = load_contracts()
    results = [stage_contract(c) for c in contracts]
    ready = sum(1 for x in results if x.get("status") == "READY")
    blocked = sum(1 for x in results if x.get("status") == "BLOCKED")
    skipped = sum(1 for x in results if x.get("status") == "SKIP")
    status = "BLOCKED" if blocked else ("PASS" if ready else "WAITING")
    out = {"pid": os.getpid(), "updated": now(), "status": status, "ready_sources": ready, "blocked_sources": blocked, "skipped_sources": skipped, "chunk_rows": CHUNK_ROWS, "results": results}
    writej(SUMMARY, out); writej(STATE, out)
    log(f"SOURCE STAGING {status} ready={ready} blocked={blocked} skipped={skipped}")
    return out


def main() -> None:
    log("CHUNKED SOURCE STAGING DIRECTOR START")
    while True:
        try:
            run_once()
        except Exception:
            err = traceback.format_exc(); log(err); writej(STATE, {"pid": os.getpid(), "updated": now(), "status": "BLOCKED", "detail": err[-1800:]})
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
