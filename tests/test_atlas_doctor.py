"""Synthetic read-only ATLAS preflight; never uses real subscriptions or user DB."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import atlas_doctor as doctor


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_fails_closed_with_no_local_setup_and_makes_no_files(self):
        root = self.root / "not-present"
        result = doctor.report(
            root, windows=True, bitness=64,
            module_available=lambda s: False,
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(root.exists())
        self.assertTrue(result["read_only"])
        self.assertFalse(result["jvlink_called"])
        self.assertFalse(result["local_db_write"])

    def test_correct_local_config_cursor_and_db_are_verified(self):
        (self.root / "inbox" / "JRA").mkdir(parents=True)
        (self.root / "inbox" / "NAR").mkdir(parents=True)
        (self.root / "receipts").mkdir()
        (self.root / "sources.local.json").write_text(json.dumps({
            "JRA": {
                "enabled": True, "source_code": "ATLAS_JRA_APPROVED",
                "rights_status": "APPROVED_INTERNAL",
                "authorization_reference": "TEST_APPROVED_ONLY",
                "adapter_type": "JV_LINK",
            },
            "NAR": {
                "enabled": False, "source_code": "ATLAS_NAR_APPROVED",
                "rights_status": "UNVERIFIED",
                "authorization_reference": "", "adapter_type": "OFFICIAL_NAR",
            },
        }), encoding="utf-8")
        (self.root / "receipts" / "jra_jvlink_cursor.json").write_text(
            '{"dataspec":"RACE","lastfiletimestamp":"20261008140000"}',
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"ATLAS_PG_DSN": "SECRET_DO_NOT_PRINT"}):
            outcome = doctor.report(
                self.root, windows=True, bitness=64,
                module_available=lambda s: True,
                pg_check=lambda: (
                    "neo_jizo_atlas", "atlas.raw_observation",
                    "atlas.canonicalization_batch",
                ),
            )
        items = {x["code"]: x["status"] for x in outcome["checks"]}
        self.assertEqual(items["JRA_RIGHTS"], "PASS")
        self.assertEqual(items["JV_CURSOR"], "PASS")
        self.assertEqual(items["ATLAS_DATABASE"], "PASS")
        self.assertEqual(items["NAR_ADAPTER"], "ACTION_REQUIRED")
        self.assertNotIn("SECRET_DO_NOT_PRINT", json.dumps(outcome))
        self.assertNotIn("TEST_APPROVED_ONLY", json.dumps(outcome))
        self.assertFalse(outcome["production_approved"])

    def test_wrong_database_is_never_called_pass(self):
        with patch.dict(os.environ, {"ATLAS_PG_DSN": "SENSITIVE_CONNECTION"}, clear=False):
            outcome = doctor.report(
                self.root, windows=True, bitness=64,
                module_available=lambda s: True,
                pg_check=lambda: (
                    "mykeibadb", "atlas.raw_observation",
                    "atlas.canonicalization_batch",
                ),
            )
        item = next(x for x in outcome["checks"] if x["code"] == "ATLAS_DATABASE")
        self.assertEqual(item["status"], "BLOCKED")
        self.assertNotIn("SENSITIVE_CONNECTION", json.dumps(outcome))

    def test_invalid_sid_blocked_without_disclosing_value(self):
        secret = " INVALID_PRIVATE_SID"
        with patch.dict(os.environ, {"ATLAS_JVLINK_SID": secret}):
            outcome = doctor.report(
                self.root, windows=True, bitness=64,
                module_available=lambda name: False,
            )
        item = next(c for c in outcome["checks"] if c["code"] == "JV_SOFTWARE_ID")
        self.assertEqual(item["status"], "BLOCKED")
        self.assertNotIn(secret, json.dumps(outcome))

    def test_private_development_uses_official_unknown(self):
        with patch.dict(os.environ, {"ATLAS_JVLINK_SID": "UNKNOWN"}):
            outcome = doctor.report(
                self.root, windows=True, bitness=64,
                module_available=lambda name: False,
            )
        item = next(c for c in outcome["checks"] if c["code"] == "JV_SOFTWARE_ID")
        self.assertEqual(item["status"], "PASS")
        self.assertFalse(outcome["jvlink_called"])

    def test_com_not_contacted_during_default_read_only_diagnosis(self):
        calls = []
        outcome = doctor.report(
            self.root, windows=True, bitness=64,
            module_available=lambda _: True,
            com_probe=lambda: calls.append("COM"),
        )
        self.assertEqual(calls, [])
        statuses = {c["code"]: c["status"] for c in outcome["checks"]}
        self.assertEqual(statuses["JV_COM_LOCAL"], "ACTION_REQUIRED")
        self.assertFalse(outcome["jvlink_called"])

    def test_explicit_com_check_uses_local_probe_and_stays_non_network(self):
        called = []
        def success():
            called.append("COM-ONLY")
        outcome = doctor.report(
            self.root, windows=True, bitness=64,
            module_available=lambda _: True,
            check_com=True, com_probe=success,
        )
        statuses = {c["code"]: c["status"] for c in outcome["checks"]}
        self.assertEqual(statuses["JV_COM_LOCAL"], "PASS")
        self.assertEqual(called, ["COM-ONLY"])
        self.assertFalse(outcome["jvlink_called"])
        self.assertTrue(outcome["read_only"])

    def test_com_exception_does_not_expose_local_system_details(self):
        private = "SECRET_LOCAL_REGISTRY_CRED"
        def fails():
            raise RuntimeError(private)
        result = doctor.report(
            self.root, windows=True, bitness=64,
            module_available=lambda _: True,
            check_com=True, com_probe=fails,
        )
        row = next(c for c in result["checks"] if c["code"] == "JV_COM_LOCAL")
        self.assertEqual(row["status"], "BLOCKED")
        self.assertNotIn(private, json.dumps(result))

    def test_missing_pywin32_blocks_com_before_probe(self):
        calls = []
        result = doctor.report(
            self.root, windows=True, bitness=64,
            module_available=lambda _: False,
            check_com=True, com_probe=lambda: calls.append("UNSAFE"),
        )
        self.assertEqual(calls, [])
        self.assertEqual(
            next(c["status"] for c in result["checks"] if c["code"] == "JV_COM_LOCAL"),
            "BLOCKED",
        )

    def test_unknown_sdk_never_claims_live_certification(self):
        outcome = doctor.report(
            self.root, windows=False,
            module_available=lambda s: False,
        )
        check = next(x for x in outcome["checks"] if x["code"] == "JV_SDK_LIVE")
        self.assertEqual(check["status"], "ACTION_REQUIRED")


if __name__ == "__main__":
    unittest.main()
