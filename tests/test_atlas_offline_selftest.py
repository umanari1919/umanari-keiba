"""Only synthetic contract tests for ATLAS offline runner; no real subprocess."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import atlas_offline_selftest as runner


class FakeCompleted:
    def __init__(self, code=0, stdout=""):
        self.returncode = code
        self.stdout = stdout


class LocalSelfTestTests(unittest.TestCase):
    def test_sensitive_runtime_flags_never_inherit(self):
        inputs = {
            **{s: "PRIVATE_SHOULD_NOT_PASS" for s in runner.SENSITIVE_ENV},
            "SYSTEMROOT": "C:\\Windows", "PATH": "SYNTHETIC_PATH",
        }
        clean = runner.synthetic_env(inputs)
        self.assertTrue(all(x not in clean for x in runner.SENSITIVE_ENV))
        self.assertEqual(clean["SYSTEMROOT"], "C:\\Windows")
        self.assertNotIn("PRIVATE_SHOULD_NOT_PASS", repr(clean))

    def test_synthetic_tests_use_own_python_and_no_shell(self):
        calls = []
        def fake_execute(argv, **kwargs):
            calls.append((argv, kwargs))
            return FakeCompleted()
        result = runner.run_tests(ROOT, execute=fake_execute)
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), len(runner.TESTS))
        for args, opts in calls:
            self.assertEqual(args[:4], [sys.executable, "-m", "unittest", "discover"])
            self.assertEqual(opts["cwd"], ROOT)
            self.assertEqual(opts["stdin"], runner.subprocess.DEVNULL)
            self.assertEqual(opts["check"], False)
            self.assertEqual(opts["timeout"], 90)
            self.assertTrue(all(s not in opts["env"] for s in runner.SENSITIVE_ENV))

    def test_test_failure_stops_following_suites(self):
        called = []
        def fails_once(*args, **kwargs):
            called.append(1)
            return FakeCompleted(1, "EXPECTED_SYNTHETIC_ERROR")
        self.assertEqual(runner.run_tests(ROOT, execute=fails_once), 1)
        self.assertEqual(len(called), 1)

    def test_refuses_missing_test_suite_without_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "ATLAS_OFFLINE_TEST_FILES_MISSING"):
                runner.run_tests(Path(tmp), execute=lambda *a, **k: self.fail("unsafe"))


if __name__ == "__main__":
    unittest.main()
