"""NEO JIZO ATLAS DB-TRUST-001: conservative, read-only metadata audit.

Default invocation does NOT connect to PostgreSQL. --inspect must be explicit.
Inspects structural compatibility only, not physical corruption or row quality.
No database mutation, export of horse rows, service management or retries.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
CORE_TABLES = {
    "race_shosai": {
        "race_code", "kaisai_nen", "kaisai_gappi", "keibajo_code",
        "kyori", "track_code", "hasso_jikoku", "toroku_tosu",
        "data_sakusei_nengappi",
    },
    "umagoto_race_joho": {
        "race_code", "ketto_toroku_bango", "umaban", "kakutei_chakujun",
        "ijo_kubun_code", "data_sakusei_nengappi",
    },
}
OPTIONAL_TABLES = {
    "hanro_chokyo": {"ketto_toroku_bango", "chokyo_nengappi", "data_sakusei_nengappi"},
    "woodchip_chokyo": {"ketto_toroku_bango", "chokyo_nengappi", "data_sakusei_nengappi"},
}
# Aggregate catalog only. Never select, publish or scan individual horse rows.
SQL = """
SELECT json_build_object(
  'database', current_database(),
  'version', current_setting('server_version'),
  'transaction_read_only', current_setting('transaction_read_only'),
  'default_transaction_read_only', current_setting('default_transaction_read_only'),
  'public_tables_total', (
      SELECT count(*) FROM information_schema.tables
      WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
  ),
  'tables', (
      SELECT coalesce(json_agg(row_to_json(t)), '[]'::json)
      FROM (
          SELECT b.table_name,
                 coalesce(s.n_live_tup, 0)::bigint AS estimated_rows,
                 coalesce((
                     SELECT json_agg(json_build_object(
                         'name', c.column_name,
                         'type', c.data_type,
                         'nullable', c.is_nullable
                     ) ORDER BY c.ordinal_position)
                     FROM information_schema.columns c
                     WHERE c.table_schema = 'public'
                       AND c.table_name = b.table_name
                 ), '[]'::json) AS columns,
                 coalesce((
                     SELECT json_agg(k.constraint_type)
                     FROM information_schema.table_constraints k
                     WHERE k.table_schema = 'public'
                       AND k.table_name = b.table_name
                 ), '[]'::json) AS constraints
          FROM information_schema.tables b
          LEFT JOIN pg_stat_user_tables s
            ON s.schemaname = b.table_schema AND s.relname = b.table_name
          WHERE b.table_schema = 'public' AND b.table_type = 'BASE TABLE'
            AND b.table_name IN (
                'race_shosai', 'umagoto_race_joho',
                'hanro_chokyo', 'woodchip_chokyo'
            )
          ORDER BY b.table_name
      ) t
  )
)
"""


def evaluate(metadata: dict) -> dict:
    """No success/production claim is possible from a metadata-only check."""
    if not isinstance(metadata, dict):
        raise ValueError("Invalid metadata payload")
    if metadata.get("database") != "mykeibadb":
        return {"status": "BLOCKED", "certified": False,
                "issues": ["WRONG_DATABASE"], "tables": {}}
    if (metadata.get("transaction_read_only") != "on" or
            metadata.get("default_transaction_read_only") != "on"):
        return {"status": "BLOCKED", "certified": False,
                "issues": ["NOT_READ_ONLY"], "tables": {}}
    entries = metadata.get("tables")
    if not isinstance(entries, list):
        return {"status": "BLOCKED", "certified": False,
                "issues": ["MISSING_TABLE_INVENTORY"], "tables": {}}
    names = [t.get("table_name") for t in entries if isinstance(t, dict)]
    if len(names) != len(entries) or len(set(names)) != len(names):
        return {"status": "BLOCKED", "certified": False,
                "issues": ["DUPLICATE_OR_INVALID_TABLE_INVENTORY"], "tables": {}}
    known = {t["table_name"]: t for t in entries}
    issues, warnings, summaries = [], [], {}
    for table, required in {**CORE_TABLES, **OPTIONAL_TABLES}.items():
        if table not in known:
            (issues if table in CORE_TABLES else warnings).append(
                "MISSING_TABLE:" + table
            )
            summaries[table] = {"present": False}
            continue
        obj = known[table]
        columns = obj.get("columns")
        if not isinstance(columns, list):
            issues.append("INVALID_COLUMNS:" + table)
            continue
        column_names = [c.get("name") for c in columns if isinstance(c, dict)]
        if len(column_names) != len(columns) or len(set(column_names)) != len(columns):
            issues.append("DUPLICATE_OR_INVALID_COLUMNS:" + table)
            continue
        missing = sorted(required - set(column_names))
        if missing:
            (issues if table in CORE_TABLES else warnings).append(
                "MISSING_COLUMNS:" + table + ":" + ",".join(missing)
            )
        constraints = obj.get("constraints", [])
        has_pk = isinstance(constraints, list) and "PRIMARY KEY" in constraints
        if not has_pk:
            warnings.append("NO_DECLARED_PRIMARY_KEY:" + table)
        estimate = obj.get("estimated_rows")
        summaries[table] = {
            "present": True, "column_count": len(column_names),
            "required_columns_present": not missing,
            "missing_columns": missing, "declared_primary_key": has_pk,
            "estimated_rows_not_exact": estimate if type(estimate) is int and estimate >= 0 else None,
        }
    return {
        "status": "STRUCTURE_BLOCKED" if issues else
                  ("STRUCTURE_WARN" if warnings else "STRUCTURE_UNVERIFIED_CONTENT"),
        "certified": False,
        "integrity_checked": False,
        "data_completeness_checked": False,
        "import_pipeline_checked": False,
        "database": "mykeibadb",
        "public_tables_total": metadata.get("public_tables_total"),
        "issues": issues,
        "warnings": warnings,
        "tables": summaries,
        "note": "Schema metadata and approximate statistics are NOT evidence of row or physical integrity.",
    }


def inspect_once(query_fn):
    """The caller explicitly enables a single read-only SELECT catalog probe."""
    raw = query_fn(SQL)
    return evaluate(raw)


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true",
                        help="explicitly perform one read-only metadata SQL query")
    args = parser.parse_args()
    if not args.inspect:
        print(json.dumps({
            "status": "NOT_RUN", "database_contacted": False, "certified": False,
            "next": "Explicit --inspect is required after independent DB recovery approval.",
            "scope": "catalog metadata only; no race records or row quality inspected",
        }, ensure_ascii=False))
        return
    # Importing the existing connector only after explicit operator action.
    sys.path.insert(0, str(ROOT / "src"))
    from sample_extract import query
    try:
        report = inspect_once(query)
    except (OSError, RuntimeError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        # Error details/connection credentials are deliberately not printed.
        print(json.dumps({
            "status": "BLOCKED", "database_contacted": True, "certified": False,
            "reason_class": type(exc).__name__, "database_modified": False,
        }, ensure_ascii=False))
        raise SystemExit(2) from None
    out = ROOT / "artifacts" / "atlas-db-trust-001"
    out.mkdir(parents=True, exist_ok=True)
    created = datetime.now(JST).strftime("%Y%m%d-%H%M%S-%f")
    with (out / ("schema-" + created + ".json")).open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({
        "status": report["status"], "certified": False,
        "critical_findings": len(report["issues"]),
        "warnings": len(report["warnings"]), "report_folder": str(out),
        "database_modified": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    cli()
