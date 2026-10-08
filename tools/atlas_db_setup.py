"""ATLAS-DB-SETUP-001: create ONLY an isolated, previously nonexistent ATLAS database.

Default mode is read-only inspection. Explicit --apply creates only
"neo_jizo_atlas" when absent, then runs the versioned, DB-name-guarded
schema migrations. NEVER drops databases, deletes records, restarts
PostgreSQL, installs extensions, or touches mykeibadb.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, unquote

DB_NAME = "neo_jizo_atlas"
MAINTENANCE_DB = "postgres"
SCHEMAS = ("atlas/sql/001_init.sql", "atlas/sql/002_canonical_map.sql")
REQUIRED_TABLES = (
    "data_source", "import_object", "raw_observation", "race",
    "horse", "race_identifier", "horse_identifier",
    "race_observation", "runner_observation", "result_observation",
    "ingest_decision", "canonicalization_batch",
)
MAX_SQL_BYTES = 256 * 1024


class SetupBlocked(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _parse_dsn(value: str, database: str):
    if not isinstance(value, str) or not value.startswith(("postgresql://", "postgres://")):
        raise SetupBlocked("URL_STYLE_LOCAL_POSTGRES_DSN_REQUIRED")
    try:
        u = urlsplit(value)
        hostname, port = u.hostname, u.port
        username = unquote(u.username or "")
        dbname = unquote(u.path.lstrip("/"))
    except ValueError as exc:
        raise SetupBlocked("DATABASE_DSN_INVALID") from exc
    if (
        hostname not in {"localhost", "127.0.0.1", "::1"}
        or port is None or not (1 <= port <= 65535)
        or not username or not dbname or dbname != database
        or u.fragment or not u.password or u.query
    ):
        raise SetupBlocked("DATABASE_DSN_LOCAL_OR_DBNAME_MISMATCH")
    return hostname, port, username


def connection_settings(admin: str | None, target: str | None):
    if not admin or not target:
        raise SetupBlocked("BOTH_LOCAL_POSTGRES_DSNS_REQUIRED")
    admin_info = _parse_dsn(admin, MAINTENANCE_DB)
    target_info = _parse_dsn(target, DB_NAME)
    if admin_info != target_info:
        raise SetupBlocked("POSTGRES_ADMIN_AND_TARGET_CLUSTER_DIFFER")
    return {"target_database": DB_NAME, "maintenance_database": MAINTENANCE_DB,
            "local_endpoint": f"{admin_info[0]}:{admin_info[1]}"}


def _psycopg():
    try:
        import psycopg
        from psycopg import sql
    except ImportError as exc:
        raise SetupBlocked("PSYCOPG_DRIVER_NOT_INSTALLED") from exc
    return psycopg, sql


def _read_schema(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size < MAX_SQL_BYTES:
        raise SetupBlocked("MIGRATION_MISSING_OR_UNSAFE")
    content = path.read_text(encoding="utf-8")
    if "current_database() <> 'neo_jizo_atlas'" not in content:
        raise SetupBlocked("MIGRATION_HAS_NO_DATABASE_GUARD")
    return content


def _available_tables(con):
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='atlas' AND table_type='BASE TABLE'"
    ).fetchall()
    return {row[0] for row in rows}


def _guard_admin(con):
    name, recovery = con.execute(
        "SELECT current_database(), pg_is_in_recovery()"
    ).fetchone()
    if name != MAINTENANCE_DB or recovery:
        raise SetupBlocked("NOT_POSTGRES_MAINTENANCE_PRIMARY")


def _guard_target(con):
    if con.execute("SELECT current_database()").fetchone()[0] != DB_NAME:
        raise SetupBlocked("WRONG_TARGET_DATABASE")


def bootstrap(*, apply: bool = False, admin_dsn=None, target_dsn=None,
              repo_root: Path | None = None):
    """Inspect only by default. Must have explicit admin/target DSNs even for preview."""
    admin = admin_dsn or os.environ.get("ATLAS_PG_ADMIN_DSN")
    target = target_dsn or os.environ.get("ATLAS_PG_DSN")
    settings = connection_settings(admin, target)
    root = repo_root or Path(__file__).resolve().parents[1]
    migrations = [_read_schema(root / name) for name in SCHEMAS]
    psycopg, sql = _psycopg()
    try:
        # Maintenance DB is queried but its schema/tables are NEVER altered.
        with psycopg.connect(admin, connect_timeout=5, autocommit=True) as maintenance:
            _guard_admin(maintenance)
            existing = maintenance.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s",
                (DB_NAME,),
            ).fetchone() is not None
            if not apply:
                return {
                    **settings, "status": "EXISTS_REVIEW_REQUIRED" if existing else "READY_TO_CREATE",
                    "modified": False, "old_database_modified": False,
                }
            if not existing:
                # Autocommit is mandatory for CREATE DATABASE; name is a
                # constant validated above and independently SQL-escaped.
                maintenance.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME))
                )
    except SetupBlocked:
        raise
    except Exception as exc:
        raise SetupBlocked("MAINTENANCE_DATABASE_CONNECTION_OR_PERMISSION_ERROR") from exc

    try:
        with psycopg.connect(target, connect_timeout=5) as con:
            _guard_target(con)
            tables = _available_tables(con)
            if existing:
                # Never silently repurpose an already-present database, even
                # if its name happens to match. No update on unknown contents.
                if not set(REQUIRED_TABLES).issubset(tables):
                    raise SetupBlocked("EXISTING_ATLAS_DB_NEEDS_MANUAL_REVIEW")
                return {
                    **settings, "status": "ALREADY_READY_NO_CHANGES",
                    "modified": False, "old_database_modified": False,
                }
            if tables:
                raise SetupBlocked("NEW_DB_ALREADY_HAS_TABLES")
            for migration in migrations:
                con.execute(migration)
            missing = set(REQUIRED_TABLES) - _available_tables(con)
            if missing:
                raise SetupBlocked("MIGRATION_TABLES_MISSING")
            return {
                **settings, "status": "CREATED_AND_INITIALIZED",
                "modified": True, "old_database_modified": False,
                "tables_verified": len(REQUIRED_TABLES),
            }
    except SetupBlocked:
        raise
    except Exception as exc:
        # The newly created DB is deliberately retained for supervised review
        # after a partial failure; never drop or reset it automatically.
        raise SetupBlocked("NEW_DB_CREATED_BUT_SCHEMA_NEEDS_MANUAL_REVIEW") from exc


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Safely prepare new neo_jizo_atlas; preview by default"
    )
    p.add_argument("--apply", action="store_true",
                   help="Explicitly create ONLY a new isolated ATLAS database")
    args = p.parse_args(argv)
    try:
        status = bootstrap(apply=args.apply)
    except SetupBlocked as exc:
        print(f"ATLAS新DB構築: 保留 / {exc.code}", file=sys.stderr)
        print("旧DBの削除・変更・サービス再起動は行いません。", file=sys.stderr)
        return 2
    print(f"ATLAS新DB構築: {status['status']}")
    print("対象DB: neo_jizo_atlas / 既存mykeibadbは対象外")
    if status.get("tables_verified"):
        print(f"必要な管理テーブル {status['tables_verified']}件を確認")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
