"""ATLAS-JVLINK-002 synthetic COM tests; no Windows SDK or JRA account needed."""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import atlas_inbox as inbox
import atlas_jvlink_capture as jv


class FakeJVLink:
    def __init__(self, records=None, *, init=0, opened=None, close=0):
        self.records = list(records or [])
        self.init = init
        self.opened = opened or (0, 1, 0, "20261008150000")
        self.close_rc = close
        self.close_calls = 0
        self.open_calls = []

    def JVInit(self, name):
        assert name.startswith("NEO-JIZO-ATLAS/")
        return self.init

    def JVOpen(self, *args):
        self.open_calls.append(args)
        return self.opened

    def JVGets(self, buffer, size, filename):
        assert size == 150_000
        if not self.records:
            return 0, b"", filename
        event = self.records.pop(0)
        if isinstance(event, int):
            return event, b"", filename
        return len(event), memoryview(event), filename

    def JVClose(self):
        self.close_calls += 1
        return self.close_rc


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        inbox.setup(self.root)
        path = self.root / "sources.local.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["JRA"].update({
            "enabled": True, "rights_status": "APPROVED_INTERNAL",
            "authorization_reference": "SYNTHETIC_TEST_ONLY",
        })
        path.write_text(json.dumps(cfg), encoding="utf-8")
        self.cfg = cfg

    def fake(self, data):
        return lambda: (data, lambda: None)

    def test_normal_delta_and_raw_exactness_and_cursor(self):
        data = FakeJVLink([b"RA" + bytes([0x82, 0xa0]) + b"\r\n", -1, b"SE" + b"\x00DATA"])
        report = jv.capture(self.root, first_from="20261007000000", com_factory=self.fake(data))
        self.assertEqual(report["status"], "CAPTURED_RAW_IN_INBOX")
        self.assertEqual(report["records"], 2)
        self.assertEqual(data.close_calls, 1)
        self.assertEqual(data.open_calls, [("RACE", "20261007000000", 1, 0, 0, "")])
        outputs = list((self.root / "inbox" / "JRA").glob("*.jsonl"))
        self.assertEqual(len(outputs), 1)
        # The receiver intentionally waits 2 seconds after a new file is published.
        age = time.time() - 10
        os.utime(outputs[0], (age, age))
        digest, size, records = inbox.parse_file(outputs[0])
        self.assertEqual(len(records), 2)
        values = [json.loads(line) for line in outputs[0].read_bytes().splitlines()]
        self.assertEqual(base64.b64decode(values[0]["payload"]["raw_base64"]),
                         b"RA" + bytes([0x82, 0xa0]) + b"\r\n")
        self.assertEqual(base64.b64decode(values[1]["payload"]["raw_base64"]), b"SE\x00DATA")
        self.assertTrue(all(v["event_time"] is None for v in values))
        cursor = json.loads((self.root / "receipts" / "jra_jvlink_cursor.json").read_text())
        self.assertEqual(cursor["lastfiletimestamp"], "20261008150000")
        self.assertFalse(cursor["canonicalized"])
        # The actual ATLAS inbox can validate these raw envelopes offline.
        preview = inbox.run_once(self.root, commit=False)
        self.assertEqual(preview["validated_only"], 1)
        self.assertEqual(preview["events"][0]["file_sha256"], digest)

    def test_second_poll_uses_checkpoint_automatically(self):
        jv.capture(self.root, first_from="20261007000000",
                   com_factory=self.fake(FakeJVLink([b"RAabc"])))
        second = FakeJVLink([b"SEdef"], opened=(0, 1, 0, "20261008170000"))
        result = jv.capture(self.root, com_factory=self.fake(second))
        self.assertEqual(second.open_calls[0][1], "20261008150000")
        self.assertEqual(result["new_cursor"], "20261008170000")
        self.assertEqual(len(list((self.root / "inbox" / "JRA").glob("*.jsonl"))), 2)

    def test_failed_download_is_not_a_completed_batch(self):
        data = FakeJVLink([b"RAabc", -100])
        with self.assertRaisesRegex(jv.CaptureBlocked, "JVGETS_FAILED"):
            jv.capture(self.root, first_from="20261007000000",
                       com_factory=self.fake(data))
        self.assertEqual(data.close_calls, 1)
        self.assertEqual(list((self.root / "inbox" / "JRA").glob("*.jsonl")), [])
        self.assertFalse((self.root / "receipts" / "jra_jvlink_cursor.json").exists())

    def test_stale_or_corrupt_cursor_fails_closed(self):
        (self.root / "receipts" / "jra_jvlink_cursor.json").write_text(
            '{"dataspec":"RACE","lastfiletimestamp":"not-a-date"}', encoding="utf-8")
        with self.assertRaisesRegex(jv.CaptureBlocked, "FROMTIME"):
            jv.capture(self.root, com_factory=self.fake(FakeJVLink([])))

    def test_initial_cursor_is_required_once(self):
        with self.assertRaisesRegex(jv.CaptureBlocked, "FIRST_FROM_REQUIRED"):
            jv.capture(self.root, com_factory=self.fake(FakeJVLink([])))

    def test_missing_license_blocks_before_creating_com(self):
        cfg = self.cfg
        cfg["JRA"].update({"enabled": False, "rights_status": "UNVERIFIED"})
        (self.root / "sources.local.json").write_text(json.dumps(cfg), encoding="utf-8")
        called = []
        with self.assertRaisesRegex(jv.CaptureBlocked, "JRA_SOURCE_NOT_APPROVED"):
            jv.capture(self.root, first_from="20261007000000",
                       com_factory=lambda: called.append(1))
        self.assertFalse(called)

    def test_invalid_dates_and_regressions_block(self):
        for date in ("20261301000000", "202610081530", "20261008246000"):
            with self.assertRaises(jv.CaptureBlocked):
                jv.validate_fromtime(date)
        obj = FakeJVLink([], opened=(0, 0, 0, "20261005000000"))
        with self.assertRaisesRegex(jv.CaptureBlocked, "REGRESSION"):
            jv.capture(self.root, first_from="20261007000000", com_factory=self.fake(obj))

    def test_no_new_data_keeps_unwritten_cursor(self):
        obj = FakeJVLink([], opened=(-1, 0, 0, ""))
        result = jv.capture(self.root, first_from="20261007000000", com_factory=self.fake(obj))
        self.assertEqual(result["status"], "NO_NEW_JRA_DATA")
        self.assertFalse((self.root / "receipts" / "jra_jvlink_cursor.json").exists())

    def test_timeout_is_an_error_not_success(self):
        obj = FakeJVLink([-3, -3, -3])
        ticks = iter([0.0, 0.3, 1.3, 2.0])
        with self.assertRaisesRegex(jv.CaptureBlocked, "TIMEOUT"):
            jv.capture(self.root, first_from="20261007000000",
                       com_factory=self.fake(obj), max_idle=1,
                       monotonic=lambda: next(ticks), sleep=lambda x: None)
        self.assertFalse((self.root / "receipts" / "jra_jvlink_cursor.json").exists())

    def test_overlapping_capture_is_refused(self):
        (self.root / ".jra_jvlink_capture.lock").mkdir()
        with self.assertRaisesRegex(jv.CaptureBlocked, "CAPTURE_ALREADY_RUNNING"):
            jv.capture(self.root, first_from="20261007000000",
                       com_factory=self.fake(FakeJVLink([b"RAabc"])))
        self.assertFalse((self.root / "receipts" / "jra_jvlink_cursor.json").exists())

    def test_chunked_publication_never_overwrites_existing_data(self):
        data = FakeJVLink([b"RA" + b"x"*80, b"SE" + b"y"*80, b"HR" + b"z"*80])
        with patch.object(jv, "CHUNK_MAX_BYTES", 420):
            report = jv.capture(self.root, first_from="20261007000000",
                                com_factory=self.fake(data))
        self.assertGreaterEqual(report["chunks"], 2)
        outputs = list((self.root / "inbox" / "JRA").glob("*.jsonl"))
        self.assertEqual(len(outputs), report["chunks"])
        age = time.time() - 10
        for file in outputs:
            os.utime(file, (age, age))
        self.assertEqual(sum(len(inbox.parse_file(p)[2]) for p in outputs), 3)
        self.assertFalse(list((self.root / "work").rglob("*.part")))

    def test_crash_safe_publish_is_content_addressed(self):
        with tempfile.TemporaryDirectory(dir=self.root) as work:
            src = Path(work) / "test.part"
            src.write_bytes(inbox.json_bytes({
                "native_kind": "JVDATA", "native_key": "JV-0000000001",
                "payload": {"synthetic": True}
            }) + b"\n")
            a = jv._publish(self.root, [src], "20261007000000")
            b = jv._publish(self.root, [src], "20261007000000")
            self.assertEqual(a, b)
            self.assertEqual(len(list((self.root / "inbox" / "JRA").glob("*.jsonl"))), 1)

    def test_closed_failure_does_not_advance(self):
        obj = FakeJVLink([b"RAabc"], close=-100)
        with self.assertRaisesRegex(jv.CaptureBlocked, "JVCLOSE_FAILED"):
            jv.capture(self.root, first_from="20261007000000", com_factory=self.fake(obj))
        self.assertFalse((self.root / "receipts" / "jra_jvlink_cursor.json").exists())
        self.assertEqual(list((self.root / "inbox" / "JRA").glob("*.jsonl")), [])


@unittest.skipUnless(os.environ.get("ATLAS_TEST_POSTGRES"), "Dedicated synthetic CI PostgreSQL only")
class PgIntegration(CaptureTests):
    def test_capture_approved_source_can_commit_and_dedup(self):
        inbox.enroll_sources(self.root)
        jv.capture(self.root, first_from="20261007000000",
                   com_factory=self.fake(FakeJVLink([b"RAabc", b"SEdef"])))
        age = time.time() - 10
        for file in (self.root / "inbox" / "JRA").glob("*.jsonl"):
            os.utime(file, (age, age))
        result = inbox.run_once(self.root, commit=True)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(inbox.run_once(self.root, commit=True)["duplicates"], 1)
        with inbox.connect_db() as con:
            n = con.execute("SELECT count(*) FROM atlas.raw_observation").fetchone()[0]
            self.assertEqual(n, 2)
            outcome = con.execute(
                "SELECT count(*) FROM atlas.runner_observation"
            ).fetchone()[0]
            self.assertEqual(outcome, 0)  # raw -> canonical mapping is intentionally gated


if __name__ == "__main__":
    unittest.main()
