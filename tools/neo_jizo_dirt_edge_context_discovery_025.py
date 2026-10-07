"""NEO-JIZO-DIRT-EDGE-025 local market-context discovery.

Read-only helper for the user's PostgreSQL mykeibadb.  It never writes to the
DB and never changes model artifacts.  The purpose is to discover a safe,
joinable source for finish, surface, popularity and win odds.

Output contains metadata/aggregate evidence only; no horse-level records.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_DB = "mykeibadb"
DEFAULT_PORT = "5433"
DEFAULT_HOST = "localhost"

KEY_PATTERNS = (
    "race_code",
    "race_id",
    "競走コード",
    "ketto_toroku_bango",
    "horse_id",
    "race_horse_id",
    "umaban",
    "馬番",
)
ODDS_PATTERNS = ("odds", "オッズ", "tansho", "単勝")
POPULARITY_PATTERNS = ("ninki", "人気", "popularity")
FINISH_PATTERNS = ("chakujun", "着順", "finish")
TRACK_PATTERNS = ("track", "トラック", "surface", "芝", "ダート")
DATE_PATTERNS = ("kaisai_nen", "race_date", "年月日", "date")


def find_psql() -> str | None:
    """Windows client is optional when the WSL-local socket works."""
    candidates = [
        shutil.which("psql"),
        r"C:\Program Files\PostgreSQL\18\bin\psql.exe",
        r"C:\Program Files\PostgreSQL\17\bin\psql.exe",
        r"C:\Program Files\PostgreSQL\16\bin\psql.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def _safe_error(message: str) -> str:
    """Show an actionable PostgreSQL diagnostic, not SQL or secrets."""
    detail = (message or "No diagnostic returned by psql").strip()
    password = os.environ.get("PGPASSWORD")
    if password:
        detail = detail.replace(password, "<redacted>")
    return detail[:1200]


def run_psql(
    psql: str | None,
    sql: str,
    *,
    backend: str,
    host: str,
    port: str,
    db: str,
) -> str:
    env = os.environ.copy()
    env.update(
        PGCONNECT_TIMEOUT="4",
        PGCLIENTENCODING="UTF8",
    )
    safe_options = "-c default_transaction_read_only=on -c statement_timeout=120000"
    env["PGOPTIONS"] = (env.get("PGOPTIONS", "") + " " + safe_options).strip()

    if backend == "windows_tcp":
        if not psql:
            raise RuntimeError("Windows psql.exe is not installed")
        # -U postgres matches the existing repository's known read-only query path.
        # -w refuses an interactive password prompt. Use a preconfigured pgpass/
        # PGPASSWORD; no password is generated, logged or written here.
        command = [
            psql, "-X", "-w", "-v", "ON_ERROR_STOP=1",
            "-h", host, "-p", port, "-U", "postgres",
            "-d", db, "-At", "-f", "-",
        ]
    elif backend == "wsl_socket":
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if not wsl:
            raise RuntimeError("WSL command is unavailable")
        # Ubuntu is an existing, user-owned distribution. Do not start, stop
        # or restart the PostgreSQL service. The Unix socket is local-trust
        # in the previously audited cluster and does not require TCP forwarding.
        shell = (
            'export PGCONNECT_TIMEOUT=4 PGCLIENTENCODING=UTF8 '
            'PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=120000"; '
            'psql_bin="$HOME/.keiba_ai/postgres18/bin/psql"; '
            'if [ ! -x "$psql_bin" ]; then psql_bin="$(command -v psql)"; fi; '
            'if [ -z "$psql_bin" ]; then echo "WSL psql not found" >&2; exit 127; fi; '
            'exec "$psql_bin" -X -w -v ON_ERROR_STOP=1 '
            '-h /tmp -p "$1" -U postgres -d "$2" -At -f -'
        )
        command = [wsl, "-d", "Ubuntu", "--", "bash", "-lc", shell, "_", port, db]
    else:
        raise ValueError("Unsupported connection backend")

    try:
        result = subprocess.run(
            command, input=sql + "\n", check=False, capture_output=True,
            text=True, encoding="utf-8", errors="replace", env=env,
            timeout=130,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{backend} invocation failure: {type(exc).__name__}") from None

    if result.returncode != 0:
        raise RuntimeError(
            f"{backend} psql exit={result.returncode}: {_safe_error(result.stderr)}"
        )
    return result.stdout.strip()


def query_json(psql: str | None, sql: str, **kwargs: str) -> Any:
    raw = run_psql(psql, f"SELECT coalesce(json_agg(x),'[]'::json) FROM ({sql}) x", **kwargs)
    return json.loads(raw or "[]")


def connect_read_only(psql: str | None, *, host: str, port: str, db: str) -> tuple[str, dict[str, str]]:
    probe_sql = """
        SELECT current_setting('transaction_read_only') AS transaction_read_only,
               current_setting('default_transaction_read_only') AS default_transaction_read_only,
               current_database() AS database_name
    """
    diagnostics: list[str] = []
    for backend in ("windows_tcp", "wsl_socket"):
        try:
            state = query_json(
                psql, probe_sql, backend=backend, host=host, port=port, db=db
            )
            if not state or state[0].get("transaction_read_only") != "on":
                diagnostics.append(f"{backend}: read-only verification failed")
                continue
            return backend, state[0]
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            diagnostics.append(f"{backend}: {_safe_error(str(exc))}")

    raise RuntimeError(
        "READ_ONLY_DB_CONNECTION_BLOCKED\n"
        + "\n".join(diagnostics)
        + "\nNo service was started or stopped; no DB changes were made."
    )

def classify(name: str) -> list[str]:
    lower = name.lower()
    kinds: list[str] = []
    groups = {
        "key": KEY_PATTERNS,
        "odds": ODDS_PATTERNS,
        "popularity": POPULARITY_PATTERNS,
        "finish": FINISH_PATTERNS,
        "track": TRACK_PATTERNS,
        "date": DATE_PATTERNS,
    }
    for kind, patterns in groups.items():
        if any(pattern.lower() in lower for pattern in patterns):
            kinds.append(kind)
    return kinds


def find_probability_file(explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None

    roots = []
    env_root = os.environ.get("THE_JOCKEY_RESEARCH_ROOT")
    if env_root:
        roots.append(Path(env_root))
    roots.extend(
        [
            Path.home() / "Downloads" / "THE-JOCKEY-RESEARCH",
            Path.cwd(),
            Path(__file__).resolve().parents[1],
        ]
    )
    seen: set[Path] = set()
    for root in roots:
        root = root.resolve()
        if root in seen:
            continue
        seen.add(root)
        candidates = [
            root / "CORE" / "data" / "CORE-010_calibrated_probabilities.csv",
            root / "data" / "CORE-010_calibrated_probabilities.csv",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
    return None


def csv_header(path: Path | None) -> list[str]:
    if path is None:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        return next(reader, [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--probabilities")
    parser.add_argument("--output")
    args = parser.parse_args()

    psql = find_psql()
    conn = {
        "host": args.host,
        "port": str(args.port),
        "db": args.db,
    }
    try:
        backend, connection_state = connect_read_only(psql, **conn)
    except RuntimeError as exc:
        # A connection problem must not be confused with malformed SQL.
        print(str(exc), file=sys.stderr)
        return 2
    conn["backend"] = backend
    print(f"Read-only PostgreSQL route: {backend}", flush=True)

    columns = query_json(
        psql,
        """
        SELECT table_schema,table_name,column_name,data_type,ordinal_position
        FROM information_schema.columns
        WHERE table_schema NOT IN ('pg_catalog','information_schema')
        ORDER BY table_schema,table_name,ordinal_position
        """,
        **conn,
    )

    table_map: dict[str, dict[str, Any]] = {}
    for col in columns:
        key = f"{col['table_schema']}.{col['table_name']}"
        table = table_map.setdefault(
            key,
            {
                "table": key,
                "columns": [],
                "kinds": set(),
            },
        )
        name = str(col["column_name"])
        kinds = classify(name)
        if kinds:
            table["columns"].append(
                {
                    "name": name,
                    "data_type": col["data_type"],
                    "kinds": kinds,
                }
            )
            table["kinds"].update(kinds)

    candidates = []
    for table in table_map.values():
        kinds = set(table["kinds"])
        score = (
            5 * int("odds" in kinds)
            + 5 * int("popularity" in kinds)
            + 4 * int("finish" in kinds)
            + 3 * int("key" in kinds)
            + 2 * int("track" in kinds)
            + int("date" in kinds)
        )
        if score:
            candidates.append(
                {
                    "table": table["table"],
                    "score": score,
                    "kinds": sorted(kinds),
                    "columns": table["columns"],
                }
            )
    candidates.sort(key=lambda x: (-x["score"], x["table"]))

    # Known core tables: collect exact schema and counts without row output.
    known = []
    for table in ("public.umagoto_race_joho", "public.race_shosai"):
        schema, name = table.split(".", 1)
        exact = [c for c in columns if c["table_schema"] == schema and c["table_name"] == name]
        if exact:
            count_text = run_psql(
                psql,
                f'SELECT count(*) FROM "{schema}"."{name}"',
                **conn,
            )
            known.append(
                {
                    "table": table,
                    "rows": int(count_text),
                    "columns": [c["column_name"] for c in exact],
                }
            )

    probability_path = find_probability_file(args.probabilities)
    header = csv_header(probability_path)

    output = {
        "mission": "NEO-JIZO-DIRT-EDGE-025",
        "probe": "MARKET-CONTEXT-DISCOVERY-001",
        "safety": {
            "db_read_only": True,
            "db_modified": False,
            "horse_rows_output": False,
            "metadata_aggregate_only": True,
        },
        "connection": connection_state,
        "connection_backend": backend,
        "probability_file": str(probability_path) if probability_path else None,
        "probability_header": header,
        "known_core_tables": known,
        "candidate_market_tables": candidates[:40],
        "decision": {
            "status": "READY_FOR_CONTEXT_MAPPING" if candidates else "BLOCKED",
            "note": (
                "Use candidate table metadata to choose a one-to-one race/runner market context join. "
                "No popularity/odds fields are allowed to influence p_win ranking."
            ),
        },
    }

    out_path = (
        Path(args.output)
        if args.output
        else Path(os.environ.get("TEMP", str(Path.home()))) / "JIZO" / "NEO-JIZO-DIRT-EDGE-025" / "market_context_discovery.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=" * 60)
    print(" NEO-JIZO-DIRT-EDGE-025 MARKET CONTEXT DISCOVERY")
    print("=" * 60)
    print(f"DB read-only       : {output['safety']['db_read_only']}")
    print(f"Probability source: {output['probability_file'] or 'NOT FOUND'}")
    print(f"Candidate tables  : {len(candidates)}")
    print("")
    print("--- TOP CANDIDATES ---")
    for item in candidates[:15]:
        cols = ", ".join(
            f"{c['name']}[{','.join(c['kinds'])}]" for c in item["columns"]
        )
        print(f"{item['score']:>2} {item['table']}: {cols}")
    print("")
    print(f"Output             : {out_path}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
