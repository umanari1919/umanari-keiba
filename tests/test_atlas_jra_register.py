"""Synthetic-only JRA-only onboarding. Never contacts a real database."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import atlas_inbox as inbox
import atlas_jra_register as register


class FakeDB:
    def __init__(self, row):
        self.row = row
        self.commands = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def execute(self, statement, params=None):
        self.commands.append((statement, params))
        return self
    def fetchone(self):
        return self.row


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        inbox.setup(self.root)

    def _approve(self, *, jra=True, nar=False):
        path = self.root / "sources.local.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if jra:
            cfg["JRA"]["enabled"] = True
            cfg["JRA"]["rights_status"] = "APPROVED_INTERNAL"
            cfg["JRA"]["authorization_reference"] = "SYNTHETIC_ONLY"
        if nar:
            cfg["NAR"]["enabled"] = True
            cfg["NAR"]["rights_status"] = "APPROVED_INTERNAL"
            cfg["NAR"]["authorization_reference"] = "SYNTHETIC_ONLY_NAR"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        return cfg

    def test_default_disabled_rights_never_call_db_or_enrollment(self):
        with patch.object(inbox, "connect_db", side_effect=AssertionError("unsafe")), \
             patch.object(inbox, "enroll_sources", side_effect=AssertionError("unsafe")):
            with self.assertRaisesRegex(
                register.RegistrationBlocked, "JRA_RIGHTS_NOT_APPROVED"
            ):
                register.register(self.root, apply=True)

    def test_preview_only_reads_local_jra_state_and_db(self):
        cfg = self._approve(jra=True, nar=True)
        db = FakeDB(None)
        with patch.object(inbox, "connect_db", return_value=db), \
             patch.object(inbox, "enroll_sources", side_effect=AssertionError("write")):
            result = register.register(self.root)
        self.assertEqual(result["status"], "JRA_REVIEWED_READY_TO_REGISTER")
        self.assertEqual(len(db.commands), 2)
        self.assertEqual(db.commands[0][0], "SET TRANSACTION READ ONLY")
        self.assertEqual(db.commands[1][1], (cfg["JRA"]["source_code"],))

    def test_explicit_apply_selects_jra_even_if_nar_also_enabled(self):
        self._approve(jra=True, nar=True)
        calls = []
        def fake_enroll(root, *, organizers=None):
            calls.append((root, organizers))
        with patch.object(inbox, "enroll_sources", side_effect=fake_enroll), \
             patch.object(inbox, "connect_db", side_effect=AssertionError("preview")):
            result = register.register(self.root, apply=True)
        self.assertEqual(result["status"], "REGISTERED_OR_ALREADY_MATCHED")
        self.assertEqual(calls, [(self.root, ("JRA",))])

    def test_existing_mismatched_registration_fails_closed(self):
        self._approve()
        with patch.object(inbox, "connect_db",
                          return_value=FakeDB(("NAR", "JV_LINK", "APPROVED_INTERNAL"))):
            with self.assertRaisesRegex(
                register.RegistrationBlocked, "DB_JRA_SOURCE_REGISTRY_MISMATCH"
            ):
                register.register(self.root)

    def test_registration_database_errors_redact_secrets(self):
        self._approve()
        secret = "password=NEVER_REPORT_THIS"
        with patch.object(inbox, "enroll_sources", side_effect=RuntimeError(secret)):
            with self.assertRaises(register.RegistrationBlocked) as error:
                register.register(self.root, apply=True)
        self.assertEqual(error.exception.reason, "JRA_DB_REGISTRY_UNAVAILABLE")
        self.assertNotIn(secret, str(error.exception))

    def test_missing_config_must_not_create_default(self):
        (self.root / "sources.local.json").unlink()
        with self.assertRaisesRegex(
            register.RegistrationBlocked, "SOURCE_CONFIG_NOT_REVIEWED"
        ):
            register.register(self.root, apply=False)
        self.assertFalse((self.root / "sources.local.json").exists())


if __name__ == "__main__":
    unittest.main()
