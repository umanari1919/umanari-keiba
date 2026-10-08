"""Synthetic supervisor tests: no actual Windows COM, licensed records or DB."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import atlas_inbox as inbox
import atlas_jra_daily as daily


class FakeCon:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class JraUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        inbox.setup(self.root)
        src_file = self.root / "sources.local.json"
        sources = json.loads(src_file.read_text(encoding="utf-8"))
        sources["JRA"].update({
            "enabled": True, "rights_status": "APPROVED_INTERNAL",
            "authorization_reference": "CI_SYNTHETIC_AUTH",
        })
        src_file.write_text(json.dumps(sources), encoding="utf-8")
        self.code = sources["JRA"]["source_code"]
        (self.root / "receipts" / "jra_jvlink_cursor.json").write_text(
            '{"dataspec":"RACE","lastfiletimestamp":"20261008150000"}',
            encoding="utf-8",
        )

    def test_single_action_sequences_capture_import_and_mapping(self):
        stages = []
        con = FakeCon()

        def db():
            stages.append("db-check")
            return con

        def capture(root):
            stages.append("capture")
            return {"status": "CAPTURED_RAW_IN_INBOX", "records": 25}

        def receive(root, *, commit):
            stages.append(("inbox", commit))
            return {"blocked": 0, "imported": 2, "duplicates": 3}

        def mapit(source_code, *, apply, limit):
            stages.append(("map", source_code, apply, limit))
            return {"status": "PASS", "mapped": 2, "withheld": 1, "objects": 2}

        report = daily.cycle(self.root, capture_fn=capture, import_fn=receive,
                             map_fn=mapit, db_fn=db)
        self.assertEqual(stages, [
            "db-check", "capture", ("inbox", True), ("map", self.code, True, 10)
        ])
        self.assertTrue(con.closed)
        self.assertEqual(report["mapped_objects"], 2)
        self.assertEqual(report["withheld_results"], 1)
        self.assertFalse(report["production_prediction_approved"])
        self.assertFalse((self.root / ".jra_daily_update.lock").exists())
        self.assertTrue((self.root / "receipts" / "jra_daily_latest.json").exists())

    def test_db_preflight_blocks_network_before_capture(self):
        called = []
        def db():
            raise inbox.ImportBlocked("WRONG_DATABASE_OR_SCHEMA")
        def capture(root):
            called.append(True)
        with self.assertRaisesRegex(daily.PipelineBlocked, "WRONG_DATABASE"):
            daily.cycle(self.root, capture_fn=capture, db_fn=db)
        self.assertFalse(called)
        self.assertFalse((self.root / ".jra_daily_update.lock").exists())

    def test_initial_capture_must_exist_and_not_auto_backfill(self):
        (self.root / "receipts" / "jra_jvlink_cursor.json").unlink()
        with self.assertRaisesRegex(daily.PipelineBlocked, "FIRST_JRA_CAPTURE_REQUIRED"):
            daily.cycle(self.root, capture_fn=lambda r: self.fail("should not connect"))

    def test_blocked_file_never_runs_canonical_mapper(self):
        def received(root, *, commit):
            return {"blocked": 1, "imported": 0, "duplicates": 0}
        with self.assertRaisesRegex(daily.PipelineBlocked, "INBOX_HAS_BLOCKED_FILES"):
            daily.cycle(
                self.root, capture_fn=lambda r: {"status": "NO_NEW_JRA_DATA", "records": 0},
                import_fn=received, map_fn=lambda *a, **k: self.fail("no map"),
                db_fn=FakeCon,
            )

    def test_more_than_ten_objects_is_processed_in_bounded_passes(self):
        calls = []
        def mapit(code, *, apply, limit):
            calls.append(1)
            return {"status": "PASS", "mapped": 10 if len(calls) == 1 else 3,
                    "withheld": 0, "objects": 10 if len(calls) == 1 else 3}
        report = daily.cycle(
            self.root, capture_fn=lambda r: {"status": "NO_NEW_JRA_DATA", "records": 0},
            import_fn=lambda r, *, commit: {"blocked": 0, "imported": 0, "duplicates": 1},
            map_fn=mapit, db_fn=FakeCon,
        )
        self.assertEqual(report["mapped_objects"], 13)
        self.assertEqual(len(calls), 2)

    def test_concurrent_updater_is_rejected(self):
        (self.root / ".jra_daily_update.lock").mkdir()
        with self.assertRaisesRegex(daily.PipelineBlocked, "UPDATE_ALREADY_RUNNING"):
            daily.cycle(self.root)

    def test_disabled_source_never_contacts_sdk_or_db(self):
        file = self.root / "sources.local.json"
        sources = json.loads(file.read_text(encoding="utf-8"))
        sources["JRA"]["rights_status"] = "UNVERIFIED"
        sources["JRA"]["enabled"] = False
        file.write_text(json.dumps(sources), encoding="utf-8")
        with self.assertRaisesRegex(daily.PipelineBlocked, "JRA_SOURCE_NOT_APPROVED"):
            daily.cycle(self.root, capture_fn=lambda r: self.fail("must not call"))


if __name__ == "__main__":
    unittest.main()
