from __future__ import annotations

import csv
import json
import os
import time
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from source_adapter_runtime import assess_table, build_year_coverage_query, contract_table_binding
except Exception:
    assess_table = None
    build_year_coverage_query = None
    contract_table_binding = None

ROOT = Path(os.environ.get("THE_JOCKEY_RESEARCH_ROOT", Path.home() / "Downloads" / "THE-JOCKEY-RESEARCH"))
CORE = ROOT / "CORE"
REPORTS = CORE / "reports"
CONTRACTS = CORE / "contracts" / "source_adapters"
PROPOSALS = CONTRACTS / "proposals"
CHECK = ROOT / "checkpoints"
LOG = ROOT / "logs" / "source_adapter_director.log"
STATE = CHECK / "source_adapter_director_state.json"
SUMMARY = REPORTS / "SOURCE_ADAPTER_summary.json"
SCHEMA_REPORT = REPORTS / "SOURCE_SCHEMA_inventory.json"
COVERAGE_REPORT = REPORTS / "SOURCE_COVERAGE_by_year.csv"
OVERLAP_REPORT = REPORTS / "SOURCE_OVERLAP_audit.json"
RECON_PLAN = REPORTS / "CANONICAL_RECONCILIATION_plan.json"
RECON_DECISION = REPORTS / "CANONICAL_RECONCILIATION_decision.json"
INTERVAL = max(300, int(os.environ.get("THE_JOCKEY_SOURCE_ADAPTER_INTERVAL", "1800")))

for p in (REPORTS, CONTRACTS, PROPOSALS, CHECK, LOG.parent):
    p.mkdir(parents=True, exist_ok=True)


def now() -> str:
    return datetime.now().astimezone().isoformat()


def writej(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def log(message: str) -> None:
    line = f"[{now()}] {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def state(status: str, detail: str = "", extra: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"pid": os.getpid(), "updated": now(), "status": status, "detail": detail}
    if extra:
        payload.update(extra)
    writej(STATE, payload)


def load_contracts() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(CONTRACTS.glob("*.json")):
        try:
            obj = json.loads(path.read_text(encoding="utf-8-sig"))
            obj["__contract_path"] = str(path)
            out.append(obj)
        except Exception as exc:
            log(f"CONTRACT_READ_ERROR {path.name}: {exc!r}")
    return out


def contract_for_table(
    contracts: list[dict[str, Any]], engine: str, database: str, schema: str, table: str
) -> dict[str, Any] | None:
    for contract in contracts:
        source = contract.get("source") or {}
        if not isinstance(source, dict):
            continue
        if str(source.get("engine") or "").upper() != engine.upper():
            continue
        configured_db = str(source.get("database") or "")
        if configured_db and configured_db != database:
            continue
        try:
            binding = contract_table_binding(contract) if contract_table_binding else None
        except Exception:
            continue
        if binding == (schema, table):
            return contract
    return None


def _postgres_connection():
    host = os.environ.get("THE_JOCKEY_PG_HOST", "127.0.0.1")
    port = int(os.environ.get("THE_JOCKEY_PG_PORT", "5433"))
    database = os.environ.get("THE_JOCKEY_PG_DB", "mykeibadb")
    user = os.environ.get("THE_JOCKEY_PG_USER") or os.environ.get("PGUSER")
    password = os.environ.get("THE_JOCKEY_PG_PASSWORD") or os.environ.get("PGPASSWORD")
    try:
        import psycopg

        kwargs: dict[str, Any] = {"host": host, "port": port, "dbname": database, "connect_timeout": 4}
        if user:
            kwargs["user"] = user
        if password:
            kwargs["password"] = password
        con = psycopg.connect(**kwargs)
        con.autocommit = True
        cur = con.cursor()
        cur.execute("SET default_transaction_read_only = on")
        cur.execute("SET statement_timeout = '20s'")
        cur.close()
        return con, {"engine": "POSTGRES", "database": database, "host": host, "port": port, "driver": "psycopg"}
    except ImportError:
        pass
    try:
        import psycopg2

        kwargs = {"host": host, "port": port, "dbname": database, "connect_timeout": 4}
        if user:
            kwargs["user"] = user
        if password:
            kwargs["password"] = password
        con = psycopg2.connect(**kwargs)
        con.autocommit = True
        cur = con.cursor()
        cur.execute("SET default_transaction_read_only = on")
        cur.execute("SET statement_timeout = '20s'")
        cur.close()
        return con, {"engine": "POSTGRES", "database": database, "host": host, "port": port, "driver": "psycopg2"}
    except ImportError as exc:
        raise RuntimeError("POSTGRES_DRIVER_UNAVAILABLE: install psycopg or psycopg2") from exc


def _mysql_connection():
    database = os.environ.get("THE_JOCKEY_MYSQL_DB")
    if not database:
        raise RuntimeError("MYSQL_NOT_CONFIGURED: THE_JOCKEY_MYSQL_DB is required; database name is never guessed")
    host = os.environ.get("THE_JOCKEY_MYSQL_HOST", "127.0.0.1")
    port = int(os.environ.get("THE_JOCKEY_MYSQL_PORT", "3306"))
    user = os.environ.get("THE_JOCKEY_MYSQL_USER") or os.environ.get("MYSQL_USER")
    password = os.environ.get("THE_JOCKEY_MYSQL_PASSWORD") or os.environ.get("MYSQL_PWD")
    try:
        import pymysql

        con = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            connect_timeout=4,
            read_timeout=20,
            write_timeout=20,
            autocommit=True,
        )
        cur = con.cursor()
        cur.execute("SET SESSION TRANSACTION READ ONLY")
        try:
            cur.execute("SET SESSION MAX_EXECUTION_TIME=20000")
        except Exception:
            pass
        cur.close()
        return con, {"engine": "MYSQL", "database": database, "host": host, "port": port, "driver": "pymysql"}
    except ImportError:
        pass
    try:
        import mysql.connector

        con = mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            connection_timeout=4,
            autocommit=True,
        )
        cur = con.cursor()
        cur.execute("SET SESSION TRANSACTION READ ONLY")
        try:
            cur.execute("SET SESSION MAX_EXECUTION_TIME=20000")
        except Exception:
            pass
        cur.close()
        return con, {"engine": "MYSQL", "database": database, "host": host, "port": port, "driver": "mysql.connector"}
    except ImportError as exc:
        raise RuntimeError("MYSQL_DRIVER_UNAVAILABLE: install pymysql or mysql-connector-python") from exc


def discover_postgres(con, meta: dict[str, Any]) -> list[dict[str, Any]]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT c.table_schema, c.table_name, c.column_name, c.ordinal_position, c.data_type, c.is_nullable,
               COALESCE(s.n_live_tup, 0)
        FROM information_schema.columns c
        LEFT JOIN pg_stat_user_tables s
          ON s.schemaname=c.table_schema AND s.relname=c.table_name
        WHERE c.table_schema NOT IN ('pg_catalog','information_schema')
        ORDER BY c.table_schema, c.table_name, c.ordinal_position
        """
    )
    rows = cur.fetchall()
    cur.close()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for schema, table, column, ordinal, data_type, nullable, estimated_rows in rows:
        key = (str(schema), str(table))
        item = grouped.setdefault(
            key,
            {
                "engine": "POSTGRES",
                "database": meta["database"],
                "schema": str(schema),
                "table": str(table),
                "estimated_rows": int(estimated_rows or 0),
                "columns": [],
            },
        )
        item["columns"].append(
            {"name": str(column), "ordinal": int(ordinal), "data_type": str(data_type), "nullable": str(nullable)}
        )
    return list(grouped.values())


def discover_mysql(con, meta: dict[str, Any]) -> list[dict[str, Any]]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT c.table_schema, c.table_name, c.column_name, c.ordinal_position, c.data_type, c.is_nullable,
               COALESCE(t.table_rows, 0)
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema=c.table_schema AND t.table_name=c.table_name
        WHERE c.table_schema=%s AND t.table_type='BASE TABLE'
        ORDER BY c.table_schema, c.table_name, c.ordinal_position
        """,
        (meta["database"],),
    )
    rows = cur.fetchall()
    cur.close()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for schema, table, column, ordinal, data_type, nullable, estimated_rows in rows:
        key = (str(schema), str(table))
        item = grouped.setdefault(
            key,
            {
                "engine": "MYSQL",
                "database": meta["database"],
                "schema": str(schema),
                "table": str(table),
                "estimated_rows": int(estimated_rows or 0),
                "columns": [],
            },
        )
        item["columns"].append(
            {"name": str(column), "ordinal": int(ordinal), "data_type": str(data_type), "nullable": str(nullable)}
        )
    return list(grouped.values())


def execute_coverage(con, table: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    query, _ = build_year_coverage_query(
        table["engine"], table["schema"], table["table"], contract
    )
    cur = con.cursor()
    cur.execute(query)
    rows = cur.fetchall()
    cur.close()
    out = []
    for year, runner_rows, race_count, runner_key_count, labeled_rows in rows:
        out.append(
            {
                "engine": table["engine"],
                "database": table["database"],
                "schema": table["schema"],
                "table": table["table"],
                "source_id": contract.get("source_id", ""),
                "year": int(year) if year is not None else "",
                "runner_rows": int(runner_rows or 0),
                "races": int(race_count or 0),
                "runner_keys": int(runner_key_count or 0),
                "labeled_rows": int(labeled_rows or 0),
            }
        )
    return out


def write_coverage(rows: list[dict[str, Any]]) -> None:
    fields = [
        "engine", "database", "schema", "table", "source_id", "year", "runner_rows", "races", "runner_keys", "labeled_rows"
    ]
    tmp = COVERAGE_REPORT.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(COVERAGE_REPORT)


def exact_proposal(table: dict[str, Any], assessment: dict[str, Any]) -> str | None:
    if assessment.get("status") != "EXACT_CANONICAL_CANDIDATE":
        return None
    source_id = f"PROPOSAL_{table['engine']}_{table['database']}_{table['schema']}_{table['table']}"
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in source_id)
    path = PROPOSALS / f"{safe}.json"
    if not path.exists():
        required = sorted(assessment.get("exact_canonical_fields") or [])
        proposal = {
            "source_id": safe,
            "enabled": False,
            "domain": "MIXED",
            "provenance": "AUTO_DISCOVERED_SCHEMA_ONLY_REQUIRES_FOUNDER_OR_CONTRACT_REVIEW",
            "rights_status": "UNVERIFIED",
            "source": {
                "engine": table["engine"],
                "database": table["database"],
                "schema": table["schema"],
                "table": table["table"],
            },
            "column_map": {name: name for name in required},
            "defaults": {},
            "export_enabled": False,
            "note": "Generated only because exact canonical column names were present. Disabled and rights-unverified; never auto-promoted.",
        }
        writej(path, proposal)
    return str(path)


def inspect_source(kind: str, contracts: list[dict[str, Any]]) -> tuple[dict[str, Any], Any | None]:
    try:
        if kind == "POSTGRES":
            con, meta = _postgres_connection()
            tables = discover_postgres(con, meta)
        else:
            con, meta = _mysql_connection()
            tables = discover_mysql(con, meta)
    except Exception as exc:
        return {
            "engine": kind,
            "status": "UNAVAILABLE",
            "error": f"{type(exc).__name__}:{str(exc)[:600]}",
            "tables": [],
        }, None

    coverage: list[dict[str, Any]] = []
    contract_ready = 0
    exact_candidates = 0
    for table in tables:
        contract = contract_for_table(
            contracts, table["engine"], table["database"], table["schema"], table["table"]
        )
        names = [c["name"] for c in table["columns"]]
        assessment = assess_table(names, contract) if assess_table else {"status": "RUNTIME_UNAVAILABLE"}
        table["assessment"] = assessment
        table["contract_path"] = (contract or {}).get("__contract_path")
        table["source_id"] = (contract or {}).get("source_id")
        table["proposal_path"] = exact_proposal(table, assessment)
        if assessment.get("status") == "EXACT_CANONICAL_CANDIDATE":
            exact_candidates += 1
        if assessment.get("status") == "CONTRACT_READY":
            contract_ready += 1
            if contract and contract.get("enabled") is True and contract.get("rights_status") in {"APPROVED", "APPROVED_INTERNAL"}:
                try:
                    coverage.extend(execute_coverage(con, table, contract))
                except Exception as exc:
                    table["coverage_error"] = f"{type(exc).__name__}:{str(exc)[:500]}"

    return {
        "engine": kind,
        "status": "PASS",
        "connection": {k: v for k, v in meta.items() if k != "password"},
        "table_count": len(tables),
        "contract_ready_tables": contract_ready,
        "exact_canonical_candidates": exact_candidates,
        "tables": tables,
        "coverage": coverage,
    }, con


def close_quietly(con) -> None:
    try:
        if con is not None:
            con.close()
    except Exception:
        pass


def build_reconciliation_outputs(sources: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ready = []
    needs_contract = []
    unavailable = []
    for source in sources:
        if source.get("status") != "PASS":
            unavailable.append({"engine": source.get("engine"), "error": source.get("error")})
            continue
        for table in source.get("tables", []):
            status = (table.get("assessment") or {}).get("status")
            item = {
                "engine": table.get("engine"),
                "database": table.get("database"),
                "schema": table.get("schema"),
                "table": table.get("table"),
                "estimated_rows": table.get("estimated_rows"),
                "source_id": table.get("source_id"),
                "assessment": status,
            }
            if status == "CONTRACT_READY":
                ready.append(item)
            elif status in {"EXACT_CANONICAL_CANDIDATE", "CONTRACT_INCOMPLETE", "NEEDS_CONTRACT"}:
                needs_contract.append(item)

    plan = {
        "updated": now(),
        "status": "READY" if ready else "DISCOVERY_ONLY",
        "ready_sources": ready,
        "needs_contract": needs_contract,
        "unavailable_sources": unavailable,
        "next_action": "STAGE_CONTRACT_READY_SOURCES" if ready else "REGISTER_VERIFIED_SOURCE_ADAPTER_CONTRACTS",
        "policy": "No schema/table/column guessing. Discovery is read-only. Only explicit enabled rights-approved contracts may proceed to data staging.",
    }
    decision = {
        "updated": now(),
        "decision": "HOLD" if not ready else "READY_FOR_STAGING_IMPLEMENTATION",
        "reason": "NO_CONTRACT_READY_SOURCE" if not ready else "EXPLICIT_CONTRACT_READY_SOURCE_EXISTS",
        "contract_ready_count": len(ready),
        "unknown_or_incomplete_count": len(needs_contract),
        "production_write_allowed": False,
    }
    overlap = {
        "updated": now(),
        "status": "PENDING_STAGING",
        "checked": False,
        "reason": "Cross-source overlap is intentionally deferred until contract-ready source keys are staged. No IDs are bulk-read during schema discovery.",
        "policy": "Overlap audit must compare staged race_horse_id keys against Active Canonical before promotion.",
    }
    return plan, decision, overlap


def run_once() -> dict[str, Any]:
    if assess_table is None or build_year_coverage_query is None:
        raise RuntimeError("source_adapter_runtime unavailable")
    state("RUNNING", "Read-only source schema discovery")
    contracts = load_contracts()
    sources = []
    connections = []
    try:
        pg, pg_con = inspect_source("POSTGRES", contracts)
        sources.append(pg)
        connections.append(pg_con)
        mysql, mysql_con = inspect_source("MYSQL", contracts)
        sources.append(mysql)
        connections.append(mysql_con)

        coverage = []
        for source in sources:
            coverage.extend(source.pop("coverage", []))
        write_coverage(coverage)
        inventory = {
            "updated": now(),
            "status": "PASS" if any(s.get("status") == "PASS" for s in sources) else "WAITING",
            "contracts_registered": len(contracts),
            "sources": sources,
            "policy": "information_schema / catalog discovery only; no SELECT *; no data mutation; no guessed mapping",
        }
        writej(SCHEMA_REPORT, inventory)
        plan, decision, overlap = build_reconciliation_outputs(sources)
        writej(RECON_PLAN, plan)
        writej(RECON_DECISION, decision)
        writej(OVERLAP_REPORT, overlap)

        available = sum(1 for s in sources if s.get("status") == "PASS")
        tables = sum(int(s.get("table_count") or 0) for s in sources)
        ready = sum(int(s.get("contract_ready_tables") or 0) for s in sources)
        out = {
            "updated": now(),
            "status": "PASS" if available else "WAITING",
            "available_sources": available,
            "discovered_tables": tables,
            "contract_ready_tables": ready,
            "coverage_rows": len(coverage),
            "decision": decision["decision"],
            "source_status": [{"engine": s.get("engine"), "status": s.get("status"), "error": s.get("error")} for s in sources],
        }
        writej(SUMMARY, out)
        state(out["status"], "source adapter discovery complete", out)
        log(f"SOURCE ADAPTER {out['status']} sources={available} tables={tables} contract_ready={ready}")
        return out
    finally:
        for con in connections:
            close_quietly(con)


def main() -> None:
    log("SOURCE ADAPTER DIRECTOR START — READ ONLY")
    while True:
        try:
            run_once()
        except Exception:
            err = traceback.format_exc()
            log(err)
            state("BLOCKED", err[-1800:])
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
