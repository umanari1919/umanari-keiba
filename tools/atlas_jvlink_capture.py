"""ATLAS-JVLINK-002: conservative Windows JV-Link normal-delta RACE receiver.

The only external operation is opt-in JV-Link COM acquisition; records are kept
as exact base64 CP932 bytes, with no field guesses. Output is a normalized
*raw envelope* for the ATLAS inbox, NEVER canonical race/horse/label data.
No postgres interaction, no old database interaction, no subscription setup.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import atlas_inbox as inbox

DATA_SPEC = "RACE"
FROM_RE = re.compile(r"^[0-9]{14}$")
CHUNK_MAX_BYTES = 32 * 1024 * 1024
RECORD_LIMIT = 150_000
MAX_RECORD_BYTES = 150_000
JV_GETS_BUFFER = 150_000
MAX_POLL_SECONDS = 3600
APP_ID = "NEO-JIZO-ATLAS/0.2"


class CaptureBlocked(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def validate_fromtime(value: str) -> str:
    if not isinstance(value, str) or not FROM_RE.fullmatch(value):
        raise CaptureBlocked("FROMTIME_FORMAT_INVALID")
    try:
        datetime.strptime(value, "%Y%m%d%H%M%S")
    except ValueError as exc:
        raise CaptureBlocked("FROMTIME_DATE_INVALID") from exc
    return value


def _write_json(path: Path, data: dict):
    inbox.write_atomic(path, json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))


def _read_checkpoint(root: Path) -> str | None:
    path = root / "receipts" / "jra_jvlink_cursor.json"
    if path.is_symlink():
        raise CaptureBlocked("CURSOR_SYMLINK")
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CaptureBlocked("CURSOR_CORRUPT") from exc
    if not isinstance(obj, dict) or obj.get("dataspec") != DATA_SPEC:
        raise CaptureBlocked("CURSOR_INVALID")
    return validate_fromtime(obj.get("lastfiletimestamp"))


def authorized(root: Path) -> bool:
    try:
        settings = inbox.load_authorizations(root)
    except inbox.ImportBlocked as exc:
        raise CaptureBlocked(exc.code) from exc
    jra = settings["JRA"]
    if (not jra.get("enabled") or jra.get("rights_status") not in inbox.APPROVED
            or len(jra.get("authorization_reference", "").strip()) < 8):
        raise CaptureBlocked("JRA_SOURCE_NOT_APPROVED")
    if jra.get("adapter_type") != "JV_LINK":
        raise CaptureBlocked("JRA_NOT_A_JVLINK_SOURCE")
    return True


def create_com():
    if sys.platform != "win32":
        raise CaptureBlocked("JVLINK_REQUIRES_WINDOWS")
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise CaptureBlocked("PYWIN32_MISSING") from exc
    pythoncom.CoInitialize()
    try:
        com = win32com.client.Dispatch("JVDTLab.JVLink")
    except Exception as exc:
        pythoncom.CoUninitialize()
        raise CaptureBlocked("JVLINK_COM_NOT_AVAILABLE") from exc
    return com, pythoncom.CoUninitialize


def _decode_open(result: Any):
    # pywin32 returns (rcode, readcount, downloadcount, lastfiletimestamp).
    if not isinstance(result, (tuple, list)) or len(result) != 4:
        raise CaptureBlocked("JVOPEN_RESPONSE_UNEXPECTED")
    rc, files, downloads, last = result
    if any(type(v) is not int for v in (rc, files, downloads)):
        raise CaptureBlocked("JVOPEN_RESPONSE_UNEXPECTED")
    if rc == -1:
        return rc, "", 0, 0
    if rc != 0:
        raise CaptureBlocked("JVOPEN_FAILED")
    if files < 0 or downloads < 0 or downloads > files:
        raise CaptureBlocked("JVOPEN_COUNTS_INVALID")
    return rc, validate_fromtime(last), files, downloads


def _record(result: Any) -> tuple[int, bytes]:
    if not isinstance(result, (tuple, list)) or len(result) < 2:
        raise CaptureBlocked("JVGETS_RESPONSE_UNEXPECTED")
    rc = result[0]
    if type(rc) is not int:
        raise CaptureBlocked("JVGETS_RESPONSE_UNEXPECTED")
    if rc <= 0:
        return rc, b""
    data = result[1]
    try:
        payload = data.tobytes() if hasattr(data, "tobytes") else bytes(data)
    except Exception as exc:
        raise CaptureBlocked("JVGETS_BYTES_UNAVAILABLE") from exc
    if not 2 <= rc <= MAX_RECORD_BYTES or len(payload) < rc:
        raise CaptureBlocked("JVGETS_LENGTH_INVALID")
    return rc, payload[:rc]


def _make_line(index: int, payload: bytes):
    try:
        kind = payload[:2].decode("ascii")
    except UnicodeError as exc:
        raise CaptureBlocked("RECORD_KIND_NOT_ASCII") from exc
    if not re.fullmatch(r"[A-Z0-9]{2}", kind):
        raise CaptureBlocked("RECORD_KIND_UNKNOWN")
    record = {
        "native_kind": "JVDATA",
        "native_key": f"JV-{index:010d}",
        "payload": {
            "jv_dataspec": DATA_SPEC,
            "record_spec": kind,
            "encoding": "cp932",
            "raw_base64": base64.b64encode(payload).decode("ascii"),
            "raw_sha256": hashlib.sha256(payload).hexdigest(),
        },
        # Not guessed: record's actual event timestamp needs official parsing.
        "provider_published_at": None,
        "event_time": None,
    }
    line = inbox.json_bytes(record) + b"\n"
    if len(line) > inbox.MAX_LINE_BYTES:
        raise CaptureBlocked("RECORD_TOO_LARGE_FOR_INBOX")
    return line


def _spool(client: Any, temp: Path, *, max_idle: int,
           monotonic: Callable[[], float], sleep: Callable[[float], None]):
    """Write only private .part fragments; only publish after successful EOF."""
    paths = []
    active = None
    records = 0
    overall_sha = hashlib.sha256()
    idle_since = monotonic()
    current_size = 0
    next_number = 0

    def new_part():
        nonlocal active, current_size, next_number
        if active:
            active.flush()
            os.fsync(active.fileno())
            active.close()
        name = temp / f"chunk-{next_number:06d}.part"
        next_number += 1
        active = name.open("xb")
        paths.append(name)
        current_size = 0

    try:
        while True:
            result = client.JVGets(bytearray(), JV_GETS_BUFFER, bytearray())
            rc, payload = _record(result)
            if rc == 0:
                break
            if rc in (-1, -3):
                if rc == -3:
                    if monotonic() - idle_since >= max_idle:
                        raise CaptureBlocked("JVGETS_DOWNLOAD_TIMEOUT")
                    sleep(1.0)
                else:
                    idle_since = monotonic()
                continue
            if rc < 0:
                raise CaptureBlocked("JVGETS_FAILED")
            idle_since = monotonic()
            if records >= RECORD_LIMIT:
                raise CaptureBlocked("JVGETS_RECORD_LIMIT")
            line = _make_line(records + 1, payload)
            if active is None or current_size + len(line) > CHUNK_MAX_BYTES:
                new_part()
            active.write(line)
            current_size += len(line)
            overall_sha.update(payload)
            records += 1
        if active:
            active.flush()
            os.fsync(active.fileno())
            active.close()
            active = None
        return paths, records, overall_sha.hexdigest()
    finally:
        if active and not active.closed:
            active.close()


def _publish(root: Path, temp_files: list[Path], from_time: str):
    """Atomically reveal completed JSONL files; never remove source originals."""
    target = root / "inbox" / "JRA"
    if target.is_symlink():
        raise CaptureBlocked("JRA_INBOX_SYMLINK")
    out = []
    for index, part in enumerate(temp_files):
        digest = inbox.sha256_file(part)
        name = f"jv_RACE_{from_time}_{index:06d}_{digest[:16]}.jsonl"
        dest = target / name
        try:
            # Atomic create-without-clobber, on the same local volume.
            os.link(part, dest)
        except FileExistsError:
            if dest.is_symlink() or inbox.sha256_file(dest) != digest:
                raise CaptureBlocked("PUBLISHED_FILE_CONFLICT") from None
        except OSError as exc:
            # Hardlinks avoid exposing a partial .jsonl file to inbox watcher.
            raise CaptureBlocked("PUBLISH_ATOMIC_LINK_FAILED") from exc
        out.append({"filename": name, "sha256": digest, "bytes": dest.stat().st_size})
    return out


def capture(root: Path, *, first_from: str | None = None, max_idle: int = 900,
            com_factory=None, monotonic=time.monotonic, sleep=time.sleep):
    inbox.setup(root)
    lock = root / ".jra_jvlink_capture.lock"
    if lock.is_symlink():
        raise CaptureBlocked("CAPTURE_LOCK_SYMLINK")
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise CaptureBlocked("CAPTURE_ALREADY_RUNNING_OR_STALE_LOCK") from exc
    try:
        return _capture_locked(root, first_from=first_from, max_idle=max_idle,
                               com_factory=com_factory, monotonic=monotonic, sleep=sleep)
    finally:
        lock.rmdir()


def _capture_locked(root: Path, *, first_from: str | None = None, max_idle: int = 900,
                    com_factory=None, monotonic=time.monotonic, sleep=time.sleep):
    if type(max_idle) is not int or not 1 <= max_idle <= MAX_POLL_SECONDS:
        raise CaptureBlocked("INVALID_POLL_LIMIT")
    inbox.setup(root)
    authorized(root)
    prior = _read_checkpoint(root)
    if prior:
        if first_from is not None:
            raise CaptureBlocked("CURSOR_ALREADY_ESTABLISHED")
        from_time = prior
    elif first_from is not None:
        from_time = validate_fromtime(first_from)
    else:
        raise CaptureBlocked("FIRST_FROM_REQUIRED")

    if (root / "work").is_symlink():
        raise CaptureBlocked("WORK_SYMLINK")
    (root / "work").mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < inbox.MIN_FREE_BYTES + 2 * CHUNK_MAX_BYTES:
        raise CaptureBlocked("LOW_DISK_SPACE")
    com, dispose = (com_factory or create_com)()
    opened = False
    acquired = False
    try:
        if com.JVInit(APP_ID) != 0:
            raise CaptureBlocked("JVINIT_FAILED")
        decoded = _decode_open(com.JVOpen(DATA_SPEC, from_time, 1, 0, 0, ""))
        if decoded[0] == -1:
            return {"status": "NO_NEW_JRA_DATA", "records": 0, "chunks": 0,
                    "cursor": prior, "new_cursor": None}
        opened = True
        _, next_time, files, downloads = decoded
        if next_time < from_time:
            raise CaptureBlocked("JV_CURSOR_REGRESSION")
        # Temp lives on the same filesystem as inbox, permitting atomic rename.
        with tempfile.TemporaryDirectory(dir=root / "work", prefix="jv-") as tmpdir:
            parts, count, digest = _spool(
                com, Path(tmpdir), max_idle=max_idle, monotonic=monotonic, sleep=sleep
            )
            if count == 0 and files > 0:
                raise CaptureBlocked("JVOPEN_FILES_BUT_NO_RECORDS")
            # All records were read. Do not publish anything until close succeeds.
            closed = com.JVClose()
            if closed not in (0, None):
                raise CaptureBlocked("JVCLOSE_FAILED")
            opened = False
            published = _publish(root, parts, from_time)
            acquired = True
        # ONE complete-batch manifest is made visible after every chunk has been published.
        # Importer rejects all fragments unless the complete manifest is present.
        manifest_folder = root / "receipts" / "jra_jvlink_batches"
        if manifest_folder.is_symlink():
            raise CaptureBlocked("MANIFEST_FOLDER_SYMLINK")
        manifest_folder.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_folder / f"jv_RACE_{from_time}_{digest[:16]}.json"
        manifest = {
            "format": "ATLAS_JVLINK_RAW_BATCH_V1",
            "dataspec": DATA_SPEC,
            "fromtime": from_time,
            "lastfiletimestamp": next_time,
            "raw_stream_sha256": digest,
            "records": count,
            "chunks": published,
            "canonicalized": False,
        }
        if manifest_path.exists():
            if manifest_path.is_symlink() or json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
                raise CaptureBlocked("MANIFEST_CONFLICT")
        else:
            _write_json(manifest_path, manifest)
        # The checkpoint is written ONLY after the batch manifest has been published.
        _write_json(root / "receipts" / "jra_jvlink_cursor.json", {
            "dataspec": DATA_SPEC, "lastfiletimestamp": next_time,
            "previous_cursor": prior, "completed_at": datetime.now(timezone.utc).isoformat(),
            "records": count, "chunks": len(published),
            "raw_stream_sha256": digest, "chunk_sha256": [p["sha256"] for p in published],
            "batch_manifest": manifest_path.name,
            "mode": "NORMAL_DELTA_ONLY", "canonicalized": False,
            "inbox_committed": False,
        })
        return {
            "status": "CAPTURED_RAW_IN_INBOX",
            "records": count, "chunks": len(published),
            "cursor": from_time, "new_cursor": next_time,
            "canonicalized": False, "inbox_committed": False,
        }
    except CaptureBlocked:
        raise
    except Exception as exc:
        # Provider exception may contain private keys/paths. Never log repr(exc).
        raise CaptureBlocked("JVLINK_OPERATION_FAILED") from exc
    finally:
        if opened:
            try:
                com.JVClose()
            except Exception:
                pass
        dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description="JRA JV-Link raw incremental reader (off by default)")
    parser.add_argument("--root", type=Path,
                        default=Path.home() / "Documents" / "NEO-JIZO-ATLAS-DATA")
    parser.add_argument("--capture", action="store_true",
                        help="Opt in to licensed JV-Link network retrieval")
    parser.add_argument("--watch", action="store_true",
                        help="Repeat locally on a timer; requires --capture and active terminal session")
    parser.add_argument("--interval", type=int, default=3600)
    parser.add_argument("--first-from", help="One-time initial 14-digit JV-Link timestamp")
    parser.add_argument("--max-idle", type=int, default=900)
    args = parser.parse_args(argv)
    if not args.capture:
        print("ATLAS JV-Link: 未実行。取得には --capture が必要です。")
        return 0
    if args.watch and not 300 <= args.interval <= 86400:
        print("JRA取得保留: INTERVAL_INVALID", file=sys.stderr)
        return 2
    initial = args.first_from
    try:
        while True:
            try:
                result = capture(args.root, first_from=initial, max_idle=args.max_idle)
                print(f"JRA取得: {result['status']} / {result['records']}件 / {result['chunks']}分割", flush=True)
                if result["status"] == "CAPTURED_RAW_IN_INBOX":
                    initial = None  # persistent cursor replaces one-time seed
            except CaptureBlocked as exc:
                print(f"JRA取得保留: {exc.code}", file=sys.stderr, flush=True)
                if not args.watch:
                    return 2
                # Configuration/rights problems should never trigger a network retry loop.
                if exc.code in {"JRA_SOURCE_NOT_APPROVED", "JRA_NOT_A_JVLINK_SOURCE",
                                "CURSOR_CORRUPT", "CURSOR_INVALID", "FIRST_FROM_REQUIRED",
                                "JVLINK_REQUIRES_WINDOWS", "PYWIN32_MISSING",
                                "JVLINK_COM_NOT_AVAILABLE", "SOURCE_CONFIG_INVALID",
                                "SOURCE_CONFIG_INCOMPLETE", "CAPTURE_ALREADY_RUNNING_OR_STALE_LOCK"}:
                    return 2
            if not args.watch:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("JRA監視を停止しました")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
