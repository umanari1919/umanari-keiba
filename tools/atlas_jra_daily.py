"""ATLAS-JRA-DAILY-003: one local command for capture -> inbox -> typed DB.

Never initializes a database, installs a service, sets a Data Lab subscription,
auto-promotes predictions, or starts unless --run/--watch is explicit.
Requires prior one-time JRA cursor and reviewed source authorization.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import atlas_inbox as inbox
import atlas_jvdata_map as mapper
import atlas_jvlink_capture as jv

MAX_MAP_PASSES = 5


class PipelineBlocked(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def cycle(root: Path, *, capture_fn=None, import_fn=None,
          map_fn=None, db_fn=None):
    inbox.setup(root)
    lock = root / ".jra_daily_update.lock"
    if lock.is_symlink():
        raise PipelineBlocked("UPDATE_LOCK_SYMLINK")
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise PipelineBlocked("UPDATE_ALREADY_RUNNING_OR_STALE_LOCK") from exc

    try:
        code = mapper.local_jra_source(root)
        if not jv._read_checkpoint(root):
            raise PipelineBlocked("FIRST_JRA_CAPTURE_REQUIRED")
        # Verify the fresh isolated ATLAS database BEFORE contacting JV-Link.
        try:
            con = (db_fn or inbox.connect_db)()
            con.close()
        except inbox.ImportBlocked as exc:
            raise PipelineBlocked(exc.code) from exc
        incoming = (capture_fn or jv.capture)(root)
        if incoming.get("status") not in {"CAPTURED_RAW_IN_INBOX", "NO_NEW_JRA_DATA"}:
            raise PipelineBlocked("CAPTURE_STATUS_UNEXPECTED")
        receipt = (import_fn or inbox.run_once)(root, commit=True, organizers=("JRA",))
        if receipt["blocked"]:
            raise PipelineBlocked("INBOX_HAS_BLOCKED_FILES")
        mapped, withheld, scanned = 0, 0, 0
        more = False
        for _ in range(MAX_MAP_PASSES):
            result = (map_fn or mapper.run)(code, apply=True, limit=10)
            mapped += result["mapped"]
            withheld += result["withheld"]
            scanned += result["objects"]
            if result["status"] != "PASS":
                raise PipelineBlocked("CANONICAL_MAPPING_BLOCKED")
            if result["objects"] < 10:
                break
        else:
            more = True
        report = {
            "at": datetime.now(timezone.utc).isoformat(),
            "status": "MORE_BACKLOG" if more else "PASS",
            "capture_status": incoming["status"],
            "received_raw_records": incoming["records"],
            "imported_files": receipt["imported"],
            "duplicate_files": receipt["duplicates"],
            "mapped_objects": mapped,
            "withheld_results": withheld,
            "mapping_objects_examined": scanned,
            "production_prediction_approved": False,
        }
        inbox.write_atomic(
            root / "receipts" / "jra_daily_latest.json",
            json.dumps(report, ensure_ascii=False, indent=2),
        )
        return report
    except jv.CaptureBlocked as exc:
        raise PipelineBlocked(exc.code) from exc
    except mapper.MappingBlocked as exc:
        raise PipelineBlocked(exc.reason) from exc
    finally:
        lock.rmdir()


def main(argv=None):
    p = argparse.ArgumentParser(description="ATLAS JRA one-step daily update; off by default")
    p.add_argument("--root", type=Path,
                   default=Path.home() / "Documents" / "NEO-JIZO-ATLAS-DATA")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--run", action="store_true", help="Run one approved local cycle")
    g.add_argument("--watch", action="store_true", help="Repeat while window stays open")
    p.add_argument("--interval", type=int, default=3600)
    args = p.parse_args(argv)
    if not args.run and not args.watch:
        print("ATLAS: 停止中。許可済みの更新には --run または --watch を指定。")
        return 0
    if args.watch and not 300 <= args.interval <= 86400:
        print("ATLAS保留: INTERVAL_INVALID", file=sys.stderr)
        return 2
    try:
        while True:
            try:
                report = cycle(args.root)
                print("ATLAS JRA 更新: " + report["status"] +
                      f" / 新規 {report['imported_files']}件 / DB変換 {report['mapped_objects']}バッチ",
                      flush=True)
            except PipelineBlocked as exc:
                print("ATLAS JRA 保留: " + exc.reason, file=sys.stderr, flush=True)
                if not args.watch or exc.reason in {
                    "JRA_SOURCE_NOT_APPROVED", "FIRST_JRA_CAPTURE_REQUIRED",
                    "WRONG_DATABASE_OR_SCHEMA", "ATLAS_PG_DSN_REQUIRED",
                    "UPDATE_ALREADY_RUNNING_OR_STALE_LOCK",
                }:
                    return 2
            if not args.watch:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("ATLAS JRA 更新監視を停止しました")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
