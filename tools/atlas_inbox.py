"""ATLAS-INBOX-001: local-only, file-drop staging into an isolated ATLAS DB.

No JV-Link, UmaConn, old mykeibadb or network access is used by this module.
Source records MUST already be normalized by a rights-approved source adapter.
The default mode is validation only; writes require explicit --commit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SOURCE_CODES = {"JRA", "NAR"}
APPROVED = {"APPROVED_INTERNAL", "APPROVED"}
KIND = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
CODE = re.compile(r"^[A-Z][A-Z0-9_-]{1,63}$")
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_LINE_BYTES = 256 * 1024
MAX_RECORDS = 100_000
MIN_FREE_BYTES = 1024 * 1024 * 1024
POLICY = "ATLAS_INBOX_V1"


class ImportBlocked(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def now():
    return datetime.now(timezone.utc).isoformat()


def json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def timestamp(value, *, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise ImportBlocked("TIMESTAMP_REQUIRED")
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ImportBlocked("TIMESTAMP_INVALID") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ImportBlocked("TIMESTAMP_NO_TIMEZONE")
    return t


def setup(root: Path):
    if root.is_symlink() or (root / "inbox").is_symlink():
        raise ImportBlocked("ROOT_OR_INBOX_SYMLINK")
    root.mkdir(parents=True, exist_ok=True)
    for name in ("JRA", "NAR"):
        folder = root / "inbox" / name
        if folder.is_symlink():
            raise ImportBlocked("INBOX_SYMLINK")
        folder.mkdir(parents=True, exist_ok=True)
    for name in ("receipts", "objects"):
        folder = root / name
        if folder.is_symlink():
            raise ImportBlocked("STORAGE_SYMLINK")
        folder.mkdir(parents=True, exist_ok=True)
    config = root / "sources.local.json"
    if not config.exists():
        # No rights are silently granted. This file is NEVER committed to GitHub.
        defaults = {
            name: {
                "enabled": False,
                "source_code": f"ATLAS_{name}_APPROVED",
                "rights_status": "UNVERIFIED",
                "authorization_reference": "",
                "adapter_type": "JV_LINK" if name == "JRA" else "OFFICIAL_NAR",
            }
            for name in sorted(SOURCE_CODES)
        }
        write_atomic(config, json.dumps(defaults, ensure_ascii=False, indent=2))
    return config


def write_atomic(path: Path, content: str):
    # Writes only our own local receipts/config; never touches source files.
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with tmp.open("x", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_authorizations(root: Path):
    try:
        obj = json.loads((root / "sources.local.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ImportBlocked("SOURCE_CONFIG_INVALID") from exc
    if not isinstance(obj, dict):
        raise ImportBlocked("SOURCE_CONFIG_INVALID")
    result = {}
    for organizer in SOURCE_CODES:
        src = obj.get(organizer)
        if not isinstance(src, dict) or type(src.get("enabled")) is not bool:
            raise ImportBlocked("SOURCE_CONFIG_INCOMPLETE")
        source_code = src.get("source_code")
        if not isinstance(source_code, str) or not CODE.fullmatch(source_code):
            raise ImportBlocked("SOURCE_CODE_INVALID")
        if src.get("adapter_type") not in {"JV_LINK", "OFFICIAL_NAR", "LOCAL_ARCHIVE", "OTHER"}:
            raise ImportBlocked("SOURCE_ADAPTER_INVALID")
        if src["enabled"] and (
            src.get("rights_status") not in APPROVED
            or not isinstance(src.get("authorization_reference"), str)
            or len(src["authorization_reference"].strip()) < 8
        ):
            raise ImportBlocked("RIGHTS_NOT_APPROVED")
        result[organizer] = src
    return result


def parse_file(path: Path):
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".jsonl":
        raise ImportBlocked("UNSUPPORTED_SOURCE_FILE")
    before = path.stat()
    if before.st_size <= 0 or before.st_size > MAX_FILE_BYTES:
        raise ImportBlocked("FILE_SIZE_INVALID")
    if time.time_ns() - before.st_mtime_ns < 2_000_000_000:
        raise ImportBlocked("FILE_STILL_WRITING")
    items = []
    keys = set()
    try:
        with path.open("rb") as stream:
            for ordinal, raw in enumerate(stream, 1):
                if ordinal > MAX_RECORDS:
                    raise ImportBlocked("RECORD_LIMIT_EXCEEDED")
                if len(raw) > MAX_LINE_BYTES:
                    raise ImportBlocked("LINE_TOO_LARGE")
                value = json.loads(raw)
                if not isinstance(value, dict) or set(value) - {
                    "native_kind", "native_key", "payload",
                    "provider_published_at", "event_time"
                }:
                    raise ImportBlocked("RECORD_SCHEMA_INVALID")
                kind, key, payload = value.get("native_kind"), value.get("native_key"), value.get("payload")
                if not isinstance(kind, str) or not KIND.fullmatch(kind):
                    raise ImportBlocked("RECORD_KIND_INVALID")
                if not isinstance(key, str) or not 0 < len(key) <= 512:
                    raise ImportBlocked("RECORD_KEY_INVALID")
                if not isinstance(payload, dict):
                    raise ImportBlocked("RECORD_PAYLOAD_INVALID")
                try:
                    packed = json_bytes(payload)
                except (TypeError, ValueError) as exc:
                    raise ImportBlocked("RECORD_PAYLOAD_INVALID") from exc
                if len(packed) > MAX_LINE_BYTES:
                    raise ImportBlocked("RECORD_PAYLOAD_TOO_LARGE")
                if (kind, key) in keys:
                    raise ImportBlocked("RECORD_DUPLICATE_NATIVE_KEY")
                keys.add((kind, key))
                items.append((
                    ordinal, kind, key, hashlib.sha256(packed).hexdigest(),
                    payload,
                    timestamp(value.get("provider_published_at"), optional=True),
                    timestamp(value.get("event_time"), optional=True),
                ))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ImportBlocked("INVALID_JSONL") from exc
    after = path.stat()
    if not items or (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size, after.st_mtime_ns, after.st_ino
    ):
        raise ImportBlocked("SOURCE_CHANGED_DURING_READ")
    digest = sha256_file(path)
    after_hash = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after_hash.st_size, after_hash.st_mtime_ns, after_hash.st_ino
    ):
        raise ImportBlocked("SOURCE_CHANGED_DURING_HASH")
    return digest, before.st_size, items


def snapshot(root: Path, original: Path, expected_sha: str, expected_size: int):
    dest = root / "objects" / expected_sha[:2] / f"{expected_sha}.jsonl"
    if dest.parent.is_symlink():
        raise ImportBlocked("ARCHIVE_SYMLINK")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.is_symlink() or sha256_file(dest) != expected_sha:
            raise ImportBlocked("ARCHIVE_HASH_MISMATCH")
        return dest
    if shutil.disk_usage(root).free < expected_size + MIN_FREE_BYTES:
        raise ImportBlocked("LOW_DISK_SPACE")
    tmp = dest.with_name(dest.name + f".{os.getpid()}.tmp")
    try:
        with original.open("rb") as src, tmp.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if tmp.stat().st_size != expected_size or sha256_file(tmp) != expected_sha:
            raise ImportBlocked("SOURCE_CHANGED_DURING_COPY")
        # Never intentionally rewrite an existing immutable object.
        if dest.exists():
            if sha256_file(dest) != expected_sha:
                raise ImportBlocked("ARCHIVE_HASH_MISMATCH")
        else:
            os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def connect_db():
    dsn = os.environ.get("ATLAS_PG_DSN")
    if not dsn:
        raise ImportBlocked("ATLAS_PG_DSN_REQUIRED")
    try:
        import psycopg
        con = psycopg.connect(dsn, connect_timeout=5)
        database, ro, schema = con.execute(
            "SELECT current_database(), current_setting('transaction_read_only'),"
            "to_regclass('atlas.raw_observation')::text"
        ).fetchone()
        if database != "neo_jizo_atlas" or ro != "off" or schema != "atlas.raw_observation":
            con.close()
            raise ImportBlocked("WRONG_DATABASE_OR_SCHEMA")
        return con
    except ImportBlocked:
        raise
    except Exception as exc:
        raise ImportBlocked("DB_CONNECTION_OR_DRIVER_UNAVAILABLE") from exc


def enroll_sources(root: Path):
    auth = load_authorizations(root)
    with connect_db() as con:
        with con.transaction():
            for organizer, item in sorted(auth.items()):
                if not item["enabled"]:
                    continue
                existing = con.execute(
                    "SELECT organizer, adapter_type, rights_status FROM atlas.data_source WHERE source_code=%s",
                    (item["source_code"],)
                ).fetchone()
                if existing:
                    if existing != (organizer, item["adapter_type"], item["rights_status"]):
                        raise ImportBlocked("SOURCE_REGISTRY_MISMATCH")
                    continue
                con.execute(
                    "INSERT INTO atlas.data_source "
                    "(source_code,organizer,adapter_type,provenance_description,rights_status) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (item["source_code"], organizer, item["adapter_type"],
                     "Local authorization reference: " + item["authorization_reference"],
                     item["rights_status"]),
                )
    return "REGISTERED"


def commit_records(root: Path, organizer: str, item: dict, path: Path, digest: str,
                   length: int, records: list):
    from psycopg.types.json import Jsonb

    # Local immutable copy succeeds BEFORE transaction. Database errors cannot destroy it.
    snapshot(root, path, digest, length)
    with connect_db() as con:
        with con.transaction():
            source = con.execute(
                "SELECT source_id,organizer,rights_status FROM atlas.data_source "
                "WHERE source_code=%s FOR SHARE", (item["source_code"],)
            ).fetchone()
            if not source or source[1] != organizer or source[2] not in APPROVED or (
                source[2] != item["rights_status"]
            ):
                raise ImportBlocked("SOURCE_NOT_REGISTERED_OR_REVOKED")
            source_id = source[0]
            result = con.execute(
                "INSERT INTO atlas.import_object "
                "(source_id,object_sha256,object_bytes,provider_object_key,acquired_at,"
                "rights_status_at_ingest) VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (source_id,object_sha256) DO NOTHING RETURNING object_id",
                (source_id, digest, length, path.name, datetime.now(timezone.utc), item["rights_status"])
            ).fetchone()
            if result is None:
                row = con.execute(
                    "SELECT d.decision FROM atlas.import_object o "
                    "LEFT JOIN atlas.ingest_decision d ON d.object_id=o.object_id "
                    "WHERE o.source_id=%s AND o.object_sha256=%s "
                    "ORDER BY d.decision_id DESC LIMIT 1", (source_id, digest)
                ).fetchone()
                if not row or row[0] != "VALIDATED":
                    raise ImportBlocked("EXISTING_BATCH_UNVERIFIED")
                return "DUPLICATE"
            object_id = result[0]
            for ordinal, kind, key, payload_sha, payload, published, event in records:
                con.execute(
                    "INSERT INTO atlas.raw_observation "
                    "(object_id,source_id,ordinal,native_kind,native_key,raw_sha256,"
                    "raw_payload,provider_published_at,event_time) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (object_id, source_id, ordinal, kind, key, payload_sha,
                     Jsonb(payload), published, event)
                )
            con.execute(
                "INSERT INTO atlas.ingest_decision "
                "(object_id,decision,validated_record_count,quarantined_record_count,policy_version) "
                "VALUES (%s,'VALIDATED',%s,0,%s)",
                (object_id, len(records), POLICY)
            )
            return "IMPORTED"


def run_once(root: Path, *, commit=False):
    setup(root)
    auth = load_authorizations(root)
    events = []
    for organizer in sorted(SOURCE_CODES):
        folder = root / "inbox" / organizer
        if folder.is_symlink():
            raise ImportBlocked("INBOX_SYMLINK")
        for path in sorted(folder.iterdir()):
            if path.name.startswith(".") or path.name.endswith(".tmp"):
                continue
            item = auth[organizer]
            event = {"source": organizer, "file_sha256": None, "rows": 0}
            try:
                if not item["enabled"]:
                    raise ImportBlocked("SOURCE_DISABLED")
                if (item.get("rights_status") not in APPROVED or
                        len(item.get("authorization_reference", "").strip()) < 8):
                    raise ImportBlocked("RIGHTS_NOT_APPROVED")
                digest, size, records = parse_file(path)
                event["file_sha256"] = digest
                event["rows"] = len(records)
                event["status"] = (
                    commit_records(root, organizer, item, path, digest, size, records)
                    if commit else "VALIDATED_ONLY"
                )
            except ImportBlocked as exc:
                event["status"] = "BLOCKED"
                event["reason"] = exc.code
            except Exception:
                # No exception values: may include DSN/credentials or raw source data.
                event["status"] = "BLOCKED"
                event["reason"] = "UNEXPECTED_FAILURE"
            events.append(event)
    summary = {
        "run_at": now(), "commit_requested": bool(commit),
        "files": len(events),
        "imported": sum(e["status"] == "IMPORTED" for e in events),
        "duplicates": sum(e["status"] == "DUPLICATE" for e in events),
        "blocked": sum(e["status"] == "BLOCKED" for e in events),
        "validated_only": sum(e["status"] == "VALIDATED_ONLY" for e in events),
        "events": events,
        "production_forecast_approved": False,
    }
    write_atomic(root / "receipts" / "latest.json", json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="ATLAS local data inbox (safe dry-run by default)")
    parser.add_argument("--root", type=Path,
                        default=Path.home() / "Documents" / "NEO-JIZO-ATLAS-DATA")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--enroll", action="store_true",
                        help="Explicitly register reviewed, enabled sources in NEW neo_jizo_atlas only")
    parser.add_argument("--commit", action="store_true",
                        help="Explicitly import into neo_jizo_atlas (requires ATLAS_PG_DSN)")
    parser.add_argument("--watch", action="store_true",
                        help="Scan continuously; only commits when --commit is explicitly included")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args(argv)
    try:
        setup(args.root)
        if args.setup:
            print("ATLAS取込フォルダー:", args.root)
            print("初期設定:", args.root / "sources.local.json", "(既定では許諾未確認・取込停止)")
            return 0
        if args.enroll:
            print("ATLAS登録:", enroll_sources(args.root))
            return 0
        if args.watch and not 10 <= args.interval <= 3600:
            raise ImportBlocked("INTERVAL_INVALID")
        while True:
            report = run_once(args.root, commit=args.commit)
            print(f"ATLAS取込: {report['imported']}新規 / {report['duplicates']}重複 / "
                  f"{report['blocked']}保留 / {report['validated_only']}検査のみ")
            if not args.watch:
                return 1 if report["blocked"] else 0
            time.sleep(args.interval)
    except ImportBlocked as exc:
        print(f"ATLAS保留: {exc.code}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ATLAS監視を停止しました")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
