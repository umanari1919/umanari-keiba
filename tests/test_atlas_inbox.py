"""ATLAS-INBOX-001 synthetic-only tests. Never reads licensed source records."""
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("atlas_inbox", ROOT / "tools" / "atlas_inbox.py")
assert spec and spec.loader
inbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inbox)


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        inbox.setup(self.root)
        self.config = self.root / "sources.local.json"
        self.sources = json.loads(self.config.read_text(encoding="utf-8"))
        self.sources["JRA"].update({
            "enabled": True, "rights_status": "APPROVED_INTERNAL",
            "authorization_reference": "SYNTHETIC_CI_ONLY",
        })
        self.config.write_text(json.dumps(self.sources), encoding="utf-8")

    def write(self, rows, name="sample.jsonl", organizer="JRA"):
        p = self.root / "inbox" / organizer / name
        p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        age = time.time() - 10
        os.utime(p, (age, age))
        return p

    @staticmethod
    def record(native_key="JRA-R1", **kwargs):
        return {"native_kind": "RACE", "native_key": native_key,
                "payload": {"race_id": native_key, "synthetic": True},
                "event_time": "2026-10-10T12:00:00+09:00", **kwargs}

    def test_initial_setup_is_blocked_by_default_and_nondestructive(self):
        self.sources["JRA"].update({"enabled": False, "rights_status": "UNVERIFIED",
                                    "authorization_reference": ""})
        self.config.write_text(json.dumps(self.sources), encoding="utf-8")
        self.write([self.record()])
        result = inbox.run_once(self.root)
        self.assertEqual(result["blocked"], 1)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["events"][0]["reason"], "SOURCE_DISABLED")
        self.assertEqual(len(list((self.root / "objects").rglob("*.jsonl"))), 0)
        self.assertEqual(json.loads(self.config.read_text())["JRA"]["enabled"], False)

    def test_validate_only_never_needs_database_or_creates_archive(self):
        p = self.write([self.record(), self.record("JRA-R2")])
        with patch.dict(os.environ, {"ATLAS_PG_DSN": "postgresql://not-real"}, clear=False):
            result = inbox.run_once(self.root, commit=False)
        self.assertEqual(result["validated_only"], 1)
        self.assertEqual(result["events"][0]["rows"], 2)
        self.assertTrue(p.exists())
        self.assertEqual(list((self.root / "objects").rglob("*.jsonl")), [])
        self.assertFalse(result["production_forecast_approved"])

    def test_duplicate_records_fail_closed(self):
        p = self.write([self.record(), self.record()])
        result = inbox.run_once(self.root)
        self.assertEqual(result["events"][0]["reason"], "RECORD_DUPLICATE_NATIVE_KEY")
        self.assertTrue(p.exists())

    def test_invalid_json_and_time_fail_closed(self):
        self.write([self.record(event_time="2026-10-10T12:00:00")], name="a.jsonl")
        p = self.root / "inbox" / "JRA" / "b.jsonl"
        p.write_text("{broken json\n", encoding="utf-8")
        age = time.time() - 10
        os.utime(p, (age, age))
        result = inbox.run_once(self.root)
        self.assertEqual({e["reason"] for e in result["events"]},
                         {"TIMESTAMP_NO_TIMEZONE", "INVALID_JSONL"})

    def test_result_payload_is_retained_not_interpreted_or_filled(self):
        rec = self.record(native_key="JRA-R3")
        rec["native_kind"] = "RESULT"
        rec["payload"] = {"label_win": None, "result_finality": "UNKNOWN"}
        self.write([rec])
        report = inbox.run_once(self.root)
        self.assertEqual(report["validated_only"], 1)
        self.assertFalse(report["production_forecast_approved"])

    def test_source_change_during_copy_aborts_without_corruption(self):
        p = self.write([self.record()])
        digest, size, _ = inbox.parse_file(p)
        with patch.object(inbox, "sha256_file", return_value="0" * 64):
            with self.assertRaisesRegex(inbox.ImportBlocked, "SOURCE_CHANGED_DURING_COPY"):
                inbox.snapshot(self.root, p, digest, size)
        self.assertFalse((self.root / "objects" / digest[:2] / f"{digest}.jsonl").exists())
        self.assertTrue(p.exists())

    def test_file_too_recent_waits_not_fails_data_contract(self):
        p = self.write([self.record()])
        os.utime(p, None)
        report = inbox.run_once(self.root)
        self.assertEqual(report["events"][0]["reason"], "FILE_STILL_WRITING")
        self.assertTrue(p.exists())

    def test_requires_approval_reference_and_license_status(self):
        self.sources["JRA"]["authorization_reference"] = ""
        self.config.write_text(json.dumps(self.sources), encoding="utf-8")
        self.write([self.record()])
        with self.assertRaisesRegex(inbox.ImportBlocked, "RIGHTS_NOT_APPROVED"):
            inbox.run_once(self.root)

    def test_wrong_database_guard(self):
        class FakeCursor:
            def fetchone(self):
                return "mykeibadb", "off", "atlas.raw_observation"
        class FakeCon:
            closed = False
            def execute(self, _):
                return FakeCursor()
            def close(self):
                self.closed = True
        c = FakeCon()
        with patch.dict(os.environ, {"ATLAS_PG_DSN": "dbname=mykeibadb"}):
            with patch.dict(__import__("sys").modules, {"psycopg": type("P", (), {"connect": staticmethod(lambda *a, **k: c)})}):
                with self.assertRaisesRegex(inbox.ImportBlocked, "WRONG_DATABASE_OR_SCHEMA"):
                    inbox.connect_db()
        self.assertTrue(c.closed)


class PostgresIntegrationTests(InboxTests):
    """Only activated in a synthetic ephemeral PostgreSQL CI service."""

    def setUp(self):
        if not os.environ.get("ATLAS_TEST_POSTGRES"):
            self.skipTest("Ephemeral PostgreSQL CI not enabled")
        super().setUp()

    def test_enroll_import_retry_dedupe_and_source_rights_gate(self):
        inbox.enroll_sources(self.root)
        p = self.write([self.record(), self.record("JRA-R2")])
        first = inbox.run_once(self.root, commit=True)
        self.assertEqual(first["imported"], 1)
        archived = list((self.root / "objects").rglob("*.jsonl"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(inbox.sha256_file(archived[0]), inbox.sha256_file(p))
        self.assertTrue(p.exists())
        second = inbox.run_once(self.root, commit=True)
        self.assertEqual(second["duplicates"], 1)
        with inbox.connect_db() as con:
            count = con.execute("SELECT count(*) FROM atlas.raw_observation").fetchone()[0]
            self.assertEqual(count, 2)
            decisions = con.execute("SELECT count(*) FROM atlas.ingest_decision").fetchone()[0]
            self.assertEqual(decisions, 1)
            con.execute("UPDATE atlas.data_source SET rights_status='DENIED' WHERE source_code=%s",
                        (self.sources["JRA"]["source_code"],))
        self.write([self.record("JRA-R3")], name="new.jsonl")
        blocked = inbox.run_once(self.root, commit=True)
        self.assertEqual(blocked["imported"], 0)
        self.assertEqual(blocked["blocked"], 2)
        self.assertEqual({e.get("reason") for e in blocked["events"]},
                         {"SOURCE_NOT_REGISTERED_OR_REVOKED"})
        with inbox.connect_db() as con:
            after = con.execute("SELECT count(*) FROM atlas.raw_observation").fetchone()[0]
            self.assertEqual(after, 2)


if __name__ == "__main__":
    unittest.main()
