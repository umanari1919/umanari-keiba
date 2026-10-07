"""Optional, single-pass JRA result extraction for a locally frozen FORWARD run.

Results are never used as model inputs. The database is read-only and is not
contacted until an operator explicitly requests --extract after the race window.
No automatic PostgreSQL restart, retry loop, migration, or licensed-data upload.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import forward_blind as blind
from sample_extract import query as read_only_query

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/neo-jizo-forward-results-v1"
REQUIRED_FIELDS = {"race_id", "horse_id", "finish_position", "abnormal_code"}
RESULT_SOURCE = "JRA_LOCAL_PG_READONLY_umagoto_race_joho"
READONLY_SQL = (
    "SELECT json_build_object("
    "'transaction_read_only',current_setting('transaction_read_only'),"
    "'default_transaction_read_only',current_setting('default_transaction_read_only'))"
)
DELAY = timedelta(minutes=90)
MAX_RACES = 96


def receipt_info(path: Path, *, root: Path = ROOT, clock: datetime | None = None) -> dict:
    """Offline-only validation; never queries or attempts to start a database."""
    root = Path(root).resolve()
    receipt_path = blind.ensure_inside(
        path, root / "artifacts/neo-jizo-forward-blind-v1/receipts"
    )
    receipt = blind.verify_receipt(receipt_path, root=root)
    observed = clock if clock is not None else datetime.now(blind.JST)
    if observed.utcoffset() != timedelta(hours=9):
        raise ValueError("The observation clock must be timezone-aware JST")
    races = receipt["run"]["predictions"]
    if not 1 <= len(races) <= MAX_RACES:
        raise ValueError("Unexpected predicted race count")
    if any(r["venue"] not in {f"{i:02}" for i in range(1, 11)} for r in races):
        raise ValueError("JRA-only result adapter cannot use an NAR or unknown venue")
    ready_after = max(blind.race_start(r) + DELAY for r in races)
    return {
        "receipt": receipt,
        "receipt_path": receipt_path,
        "race_ids": sorted(r["race_id"] for r in races),
        "ready_after": ready_after,
        "ready": observed > ready_after and observed > blind.jst_time(receipt["sealed_at"]),
    }


def select_sql(race_ids: list[str]) -> str:
    """Fixed table/columns; only digits-only race IDs from verified receipts."""
    if not 1 <= len(race_ids) <= MAX_RACES:
        raise ValueError("Race ID list is empty or unbounded")
    if len(race_ids) != len(set(race_ids)):
        raise ValueError("Duplicate race identifiers")
    for rid in race_ids:
        if (not isinstance(rid, str) or len(rid) != 16 or
                not rid.isascii() or not rid.isdigit()):
            raise ValueError("Untrusted race identifier")
    literals = ",".join("'" + rid + "'" for rid in sorted(race_ids))
    return (
        "SELECT coalesce(json_agg(t),'[]'::json) FROM ("
        "SELECT trim(race_code) AS race_id,"
        "trim(ketto_toroku_bango) AS horse_id,"
        "trim(kakutei_chakujun) AS finish_position,"
        "trim(ijo_kubun_code) AS abnormal_code "
        "FROM public.umagoto_race_joho "
        f"WHERE race_code IN ({literals}) "
        "ORDER BY race_code,ketto_toroku_bango) t"
    )


def normalize(raw_rows: object, race_ids: list[str]) -> list[dict]:
    """Do not infer missing finishes or convert missing labels into losses."""
    if not isinstance(raw_rows, list):
        raise ValueError("Unexpected database response (not an array)")
    allowed = set(race_ids)
    seen = set()
    output = []
    for raw in raw_rows:
        if not isinstance(raw, dict) or set(raw) != REQUIRED_FIELDS:
            raise ValueError("Unexpected DB result columns")
        race_id, horse_id = raw["race_id"], raw["horse_id"]
        if (not isinstance(race_id, str) or race_id not in allowed or
                not isinstance(horse_id, str) or len(horse_id) != 10 or
                not horse_id.isascii() or not horse_id.isdigit()):
            raise ValueError("Malformed/unknown result identity")
        key = race_id, horse_id
        if key in seen:
            raise ValueError("Duplicate DB result identity")
        seen.add(key)
        abnormal = raw["abnormal_code"]
        finish = raw["finish_position"]
        if not isinstance(abnormal, (str, type(None))) or not isinstance(finish, (str, type(None))):
            raise ValueError("Malformed DB result status types")
        # SQL NULL means unresolved; it must not become a zero/losing label.
        abnormal = (abnormal or "").strip()
        finish = (finish or "").strip()
        # 0=normal, 4=競走中止; 1/2/3=出走取消・除外等
        # Unknown codes/empty ranks remain unresolved rather than becoming 0.
        if abnormal == "0" and finish.isascii() and finish.isdigit() and int(finish) > 0:
            status, position = "FINISHED", int(finish)
        elif abnormal == "4" and (not finish or finish.isascii() and finish.isdigit() and int(finish) == 0):
            status, position = "DID_NOT_FINISH", None
        elif abnormal in {"1", "2", "3"}:
            status, position = "NON_STARTER", None
        else:
            status, position = "UNRESOLVED", None
        output.append({
            "race_id": race_id,
            "horse_id": horse_id,
            "finish_position": position,
            "result_status": status,
        })
    return sorted(output, key=lambda x: (x["race_id"], x["horse_id"]))


def collect(receipt_path: Path, *, root: Path = ROOT,
            query_fn: Callable[[str], object] = read_only_query,
            clock: Callable[[], datetime] | None = None,
            store: Path | None = None) -> dict:
    """Only --extract calls this. No retry or partial output on DB failure."""
    root = Path(root).resolve()
    now = clock() if clock is not None else datetime.now(blind.JST)
    info = receipt_info(receipt_path, root=root, clock=now)
    if not info["ready"]:
        raise ValueError("RESULT_WINDOW_NOT_MATURE: no database query performed")
    status = query_fn(READONLY_SQL)
    if status != blind.READONLY:
        raise ValueError("Result DB transaction is not confirmed read-only")
    raw_rows = query_fn(select_sql(info["race_ids"]))
    normalized = normalize(raw_rows, info["race_ids"])
    observed = clock() if clock is not None else datetime.now(blind.JST)
    if observed.utcoffset() != timedelta(hours=9) or observed < now:
        raise ValueError("Result observation clock moved backwards")
    if not observed > info["ready_after"]:
        raise ValueError("Result query finished before safe observation window")
    results = {
        "observed_at": observed.isoformat(),
        "read_only_connection": dict(blind.READONLY),
        "source": RESULT_SOURCE,
        "rows": normalized,
    }
    output_base = Path(store) if store is not None else root / "artifacts/neo-jizo-forward-results-v1"
    raw = blind.encoded(results)
    sha = blind.digest(raw)
    receipt_sha = info["receipt"]["prediction_sha256"]
    location = output_base / "exports" / (receipt_sha + "-" + sha + ".json")
    blind._write_once(location, results)
    score = blind.score_receipt(info["receipt_path"], location, root=root, now=observed)
    summary = blind.read(score)
    return {
        "status": summary["status"],
        "result_export_path": str(location),
        "score_path": str(score),
        "result_export_sha256": sha,
        "scored_races": summary["scored_races"],
        "quarantined_races": len(summary["quarantined_races"]),
        "prospective_verified": False,
        "production_approved": False,
        "source": RESULT_SOURCE,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="JRA local result receipt adapter; no DB retry")
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--extract", action="store_true",
                        help="explicitly allow one read-only DB query, when ready")
    args = parser.parse_args()
    info = receipt_info(args.receipt, root=args.root)
    if not args.extract:
        print(json.dumps({
            "status": "READY_FOR_OPERATOR_EXTRACTION" if info["ready"] else "NOT_YET_MATURE",
            "race_count": len(info["race_ids"]),
            "ready_after": info["ready_after"].isoformat(),
            "database_contacted": False,
        }, ensure_ascii=False))
        return
    if not info["ready"]:
        print(json.dumps({"status": "NOT_YET_MATURE", "database_contacted": False}))
        raise SystemExit(2)
    try:
        outcome = collect(args.receipt, root=args.root)
    except (RuntimeError, OSError, TimeoutError) as exc:
        # Connection/psql failures are operational blockers; never print a
        # connection string, a password, or rows from a failed query.
        print(json.dumps({"status": "DB_UNAVAILABLE_OR_QUERY_FAILED",
                          "exception_type": type(exc).__name__,
                          "database_modified": False}))
        raise SystemExit(2) from None
    print(json.dumps(outcome, ensure_ascii=False))


if __name__ == "__main__":
    main()
