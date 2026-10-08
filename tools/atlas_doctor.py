"""ATLAS-DOCTOR-001: read-only preflight before the first real JRA deployment.

No folders/config files created, JVInit/JVOpen/JVGets never called,
no database writes, no credentials emitted. No external network calls except
explicit local PostgreSQL connectivity validation via the provided DSN.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import struct
import sys
from pathlib import Path
from typing import Callable

import atlas_inbox as inbox

CODE = re.compile(r"^[A-Z][A-Z0-9_-]{1,63}$")


def report(root: Path, *, windows=None, bitness=None,
           module_available: Callable[[str], bool] | None = None,
           pg_check=None) -> dict:
    if windows is None:
        windows = sys.platform == "win32"
    if bitness is None:
        bitness = struct.calcsize("P") * 8
    if module_available is None:
        module_available = lambda name: importlib.util.find_spec(name) is not None

    checks = []

    def add(code, status, detail):
        checks.append({"code": code, "status": status, "detail": detail})

    if not windows:
        add("WINDOWS_REQUIRED", "BLOCKED", "JV-Link実機取得はWindows専用です")
    elif bitness != 64:
        add("PYTHON_BITNESS", "BLOCKED", "64bit Python環境を使ってください")
    else:
        add("WINDOWS_PYTHON", "PASS", "Windows 64bit Python")

    if not (3, 13) <= sys.version_info[:2] <= (3, 14):
        add("PYTHON_VERSION", "BLOCKED", "検証済みのPython 3.13/3.14ではありません")
    else:
        add("PYTHON_VERSION", "PASS", "Python 3.13/3.14")

    if not module_available("win32com") or not module_available("pythoncom"):
        add("PYWIN32", "BLOCKED", "pywin32がこのPython環境にありません")
    else:
        add("PYWIN32", "PASS", "pywin32利用可能")

    if not module_available("psycopg"):
        add("PSYCOPG", "BLOCKED", "psycopgがこのPython環境にありません")
    else:
        add("PSYCOPG", "PASS", "psycopg利用可能")

    if root.is_symlink() or (root / "inbox").is_symlink():
        add("DATA_DIRECTORY", "BLOCKED", "データフォルダーにシンボリックリンクがあります")
    elif not root.is_dir():
        add("DATA_DIRECTORY", "BLOCKED", "ATLASデータフォルダーは未作成です")
    else:
        add("DATA_DIRECTORY", "PASS", "データフォルダーを確認")

    if root.is_dir():
        try:
            free = shutil.disk_usage(root).free
            if free < inbox.MIN_FREE_BYTES + 2 * 32 * 1024 * 1024:
                add("DISK_SPACE", "BLOCKED", "受信・保全に必要な空き容量が不足")
            else:
                add("DISK_SPACE", "PASS", "受信用の最小空き容量を確認")
        except OSError:
            add("DISK_SPACE", "BLOCKED", "空き容量を調べられません")
    else:
        add("DISK_SPACE", "BLOCKED", "データフォルダーがないため未検査")

    try:
        config = inbox.load_authorizations(root)
        jra = config["JRA"]
        if (jra["enabled"] is not True
                or jra["rights_status"] not in inbox.APPROVED
                or jra["adapter_type"] != "JV_LINK"
                or len(jra.get("authorization_reference", "").strip()) < 8
                or not CODE.fullmatch(jra["source_code"])):
            add("JRA_RIGHTS", "BLOCKED", "JRAの利用権限と接続元設定が未確認")
        else:
            add("JRA_RIGHTS", "PASS", "登録設定は有効（実際の契約確認は別途必要）")
    except (inbox.ImportBlocked, KeyError, TypeError, OSError):
        add("JRA_RIGHTS", "BLOCKED", "JRA設定は未作成または未承認")
        jra = None

    path = root / "receipts" / "jra_jvlink_cursor.json"
    if path.is_symlink():
        add("JV_CURSOR", "BLOCKED", "カーソルファイルのリンクは許可しません")
    elif not path.is_file():
        add("JV_CURSOR", "ACTION_REQUIRED", "初回のJRA差分取得と起点日時の設定が必要")
    else:
        try:
            from atlas_jvlink_capture import validate_fromtime
            obj = json.loads(path.read_text(encoding="utf-8"))
            if obj["dataspec"] != "RACE":
                raise ValueError("unexpected dataspec")
            validate_fromtime(obj["lastfiletimestamp"])
            add("JV_CURSOR", "PASS", "前回の取得時刻を確認")
        except (ValueError, OSError, KeyError, TypeError, Exception) as exc:
            # Never display file contents or exception arguments.
            add("JV_CURSOR", "BLOCKED", "取得カーソルが破損・不整合")
    if not os.environ.get("ATLAS_PG_DSN"):
        add("ATLAS_DATABASE", "BLOCKED", "新DBの安全な接続設定がありません")
    elif not module_available("psycopg"):
        add("ATLAS_DATABASE", "BLOCKED", "DB接続ドライバー未導入のため接続未確認")
    else:
        try:
            if pg_check is None:
                import psycopg

                with psycopg.connect(os.environ["ATLAS_PG_DSN"], connect_timeout=5) as con:
                    # read-only session; no administrative SQL or permission changes.
                    con.execute("SET TRANSACTION READ ONLY")
                    values = con.execute(
                        "SELECT current_database(), "
                        "to_regclass('atlas.raw_observation')::text, "
                        "to_regclass('atlas.canonicalization_batch')::text"
                    ).fetchone()
            else:
                values = pg_check()
            if values != (
                "neo_jizo_atlas", "atlas.raw_observation", "atlas.canonicalization_batch"
            ):
                add("ATLAS_DATABASE", "BLOCKED", "接続先DB名または専用DB表構造が不一致")
            else:
                add("ATLAS_DATABASE", "PASS", "新ATLAS専用DBと受信・正規化表を確認")
        except Exception:
            add("ATLAS_DATABASE", "BLOCKED", "新DBに接続できません（秘密情報は非表示）")

    # Inspection only. SDK COM creation/network acquisition is never attempted.
    add("JV_SDK_LIVE", "ACTION_REQUIRED", "JV-Link公式SDKとの実通信は未検証")
    add("NAR_ADAPTER", "ACTION_REQUIRED", "NAR/UmaConn公式取得は別ミッション")
    blocking = sum(x["status"] == "BLOCKED" for x in checks)
    return {
        "status": "BLOCKED" if blocking else "PRECHECK_PASS_NOT_LIVE_CERTIFIED",
        "blocking": blocking, "checks": checks,
        "read_only": True, "jvlink_called": False,
        "local_db_write": False, "production_approved": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="ATLAS JRA read-only setup diagnosis")
    p.add_argument(
        "--root", type=Path,
        default=Path.home() / "Documents" / "NEO-JIZO-ATLAS-DATA",
    )
    args = p.parse_args(argv)
    outcome = report(args.root)
    print("\n================ NEO JIZO ATLAS — 実機導入前チェック ================")
    for item in outcome["checks"]:
        print(f"{item['status']:<15} {item['code']:<18} {item['detail']}")
    print(f"状態: {outcome['status']}。外部SDK取得・DB更新・環境変更は行いません。")
    return 2 if outcome["blocking"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
