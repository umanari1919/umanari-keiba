"""ATLAS-OFFLINE-SELFTEST-001: one-click synthetic tests, never licensed data.

This runner deliberately strips DB connection settings and live-integration
flags from its child processes. It doesn't invoke JVInit, start services,
install packages, read legacy DBs, or transmit test results.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "test_atlas_inbox.py",
    "test_atlas_jvlink_capture.py",
    "test_atlas_jvdata_map.py",
    "test_atlas_jra_daily.py",
    "test_atlas_doctor.py",
    "test_atlas_db_setup.py",
    "test_atlas_offline_selftest.py",
)
SENSITIVE_ENV = (
    "ATLAS_TEST_POSTGRES", "ATLAS_TEST_BOOTSTRAP",
    "ATLAS_PG_DSN", "ATLAS_PG_ADMIN_DSN", "ATLAS_JVLINK_SID",
    "PGPASSWORD", "PGPASSFILE", "PGHOST", "PGPORT", "PGUSER",
    "PGDATABASE", "PGSERVICE", "PGSERVICEFILE",
)


def synthetic_env(source=None):
    clean = dict(os.environ if source is None else source)
    for name in SENSITIVE_ENV:
        clean.pop(name, None)
    return clean


def run_tests(root=ROOT, *, execute=None, timeout=90):
    if not (root / "tests" / TESTS[0]).is_file():
        raise RuntimeError("ATLAS_OFFLINE_TEST_FILES_MISSING")
    execute = execute or subprocess.run
    safe_env = synthetic_env()
    passed = 0
    for name in TESTS:
        print(f"ATLAS 合成検証: {name}", flush=True)
        args = [
            sys.executable, "-m", "unittest", "discover",
            "-s", "tests", "-p", name, "-q",
        ]
        try:
            result = execute(
                args, cwd=root, env=safe_env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            print("  BLOCKED: SYNTHETIC_TEST_TIMEOUT")
            return 2
        if result.returncode:
            print("  BLOCKED: SYNTHETIC_TEST_FAILED")
            # Test bodies are synthetic; limit output and never forward remotely.
            print((result.stdout or "")[-6000:])
            return 1
        print("  PASS", flush=True)
        passed += 1
    print(f"ATLAS 合成検証: {passed}/{len(TESTS)}スイートPASS")
    print("ローカルDB・JV-Link・実データ接続は行っていません。")
    return 0


def main():
    try:
        return run_tests()
    except Exception:
        print("ATLAS合成検証: BLOCKED / LOCAL_RUNNER_ERROR")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
