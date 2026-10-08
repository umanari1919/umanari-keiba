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
        self.init_sid = None
        self.close_calls = 0
        self.open_calls = []

    def JVInit(self, name):
        self.init_sid = name
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

    def test_registered_software_sid_from_local_env_never_reported(self):
        sdk = FakeJVLink([b"RAabc"])
        official = "SA123456/SD123456/ATLAS/Ver.0.2"
        with patch.dict(os.environ, {"ATLAS_JVLINK_SID": official}):
            result = jv.capture(
                self.root, first_from="20261007000000", com_factory=self.fake(sdk)
            )
        self.assertEqual(sdk.init_sid, official)
        self.assertNotIn(official, str(result))
        self.assertNotIn(official, str((self.root / "receipts" / "jra_jvlink_cursor.json").read_text()))

    def test_invalid_sid_fails_before_com_construction(self):
        for value in ("", " INVALID", "Z" * 65, "NAME\nINJECTION"):
            called = []
            with patch.dict(os.environ, {"ATLAS_JVLINK_SID": value}):
                with self.assertRaisesRegex(jv.CaptureBlocked, "JV_SID_INVALID"):
                    jv.capture(
                        self.root, first_from="20261007000000",
                        com_factory=lambda: called.append(1),
                    )
            self.assertEqual(called, [])

    def test_vendor_return_codes_preserved_without_secret_content(self):
        sdk_init = FakeJVLink(init=-101)
        with self.assertRaisesRegex(jv.CaptureBlocked, "JVINIT_ERROR_101"):
            jv.capture(
                self.root, first_from="20261007000000",
                com_factory=self.fake(sdk_init),
            )
        sdk_open = FakeJVLink(opened=(-413, 0, 0, ""))
        with self.assertRaisesRegex(jv.CaptureBlocked, "JVOPEN_ERROR_413"):
            jv.capture(
                self.root, first_from="20261007000000",
                com_factory=self.fake(sdk_open),
            )
        self.assertFalse((self.root / "receipts" / "jra_jvlink_cursor.json").exists())

    def test_chunk_row_limit_never_exceeds_mapper_capacity(self):
        # Compact SE-like records may exceed mapper's MAX_BATCH_ROWS long
        # before they reach 32 MiB. Never publish an un-mappable raw object.
        self.assertLess(jv.CHUNK_MAX_RECORDS, 20_000)
        sample = [b"SE" + (f"{n:04d}".encode()) for n in range(5)]
        with patch.object(jv, "CHUNK_MAX_RECORDS", 2):
            report = jv.capture(
                self.root, first_from="20261007000000",
                com_factory=self.fake(FakeJVLink(sample)),
            )
        self.assertEqual(report["records"], 5)
        self.assertEqual(report["chunks"], 3)
        _, batches = inbox._ready_jv_batches(self.root)
        self.assertEqual(len(batches), 1)
        _, parts = batches[0]
        self.assertEqual(len(parts), 3)
        lengths = [len(inbox.parse_file(path, finalized_manifest=True)[2]) for path, _ in parts]
        self.assertEqual(lengths, [2, 2, 1])
        self.assertEqual(sum(lengths), 5)

    def test_low_row_limit_preserves_one_transaction_import_boundary(self):
        sample = [b"SE" + (f"{n:04d}".encode()) for n in range(5)]
        with patch.object(jv, "CHUNK_MAX_RECORDS", 2):
            report = jv.capture(
                self.root, first_from="20261007000000",
                com_factory=self.fake(FakeJVLink(sample)),
            )
        checked = inbox.run_once(self.root, commit=False, organizers=("JRA",))
        self.assertEqual(checked["validated_only"], report["chunks"])
        self.assertEqual(checked["blocked"], 0)

    def test_normal_delta_and_raw_exactness_and_cursor(self):
        data = FakeJVLink([b"RA" + bytes([0x82, 0xa0]) + b"\r\n", -1, b"SE" + b"\x00DATA"])
        report = jv.capture(self.root, first_from="20261007000000", com_factory=self.fake(data))
        self.assertEqual(report["status"], "CAPTURED_RAW_IN_INBOX")
        self.assertEqual(report["records"], 2)
        self.assertEqual(data.close_calls, 1)
        self.assertEqual(data.init_sid, "UNKNOWN")
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

    def test_batch_manifest_is_required_before_import(self):
        jv.capture(self.root, first_from="20261007000000",
                   com_factory=self.fake(FakeJVLink([b"RAabc", b"SEdef"])))
        candidate = next((self.root / "inbox" / "JRA").glob("*.jsonl"))
        # A just-captured, complete batch must work in the SAME one-click cycle.
        # Loose files still require the two-second stability interval.
        with self.assertRaisesRegex(inbox.ImportBlocked, "FILE_STILL_WRITING"):
            inbox.parse_file(candidate)
        good = inbox.run_once(self.root, commit=False)
        self.assertEqual(good["validated_only"], 1)

        manifest = next((self.root / "receipts" / "jra_jvlink_batches").glob("*.json"))
        original = manifest.read_bytes()
        manifest.unlink()
        blocked = inbox.run_once(self.root, commit=False)
        self.assertEqual(blocked["blocked"], 1)
        self.assertEqual(blocked["events"][0]["reason"], "JV_BATCH_NOT_FINALIZED")
        manifest.write_bytes(original)
        recovered = inbox.run_once(self.root, commit=False)
        self.assertEqual(recovered["validated_only"], 1)

    def test_just_published_multi_chunk_batch_validates_without_sleep(self):
        data = FakeJVLink([b"RA" + b"x"*80, b"SE" + b"y"*80, b"HR" + b"z"*80])
        with patch.object(jv, "CHUNK_MAX_BYTES", 420):
            captured = jv.capture(
                self.root, first_from="20261007000000",
                com_factory=self.fake(data),
            )
        self.assertGreaterEqual(captured["chunks"], 2)
        checked = inbox.run_once(self.root, commit=False, organizers=("JRA",))
        self.assertEqual(checked["validated_only"], captured["chunks"])
        self.assertEqual(checked["blocked"], 0)

    def test_missing_chunk_in_batch_blocks_other_chunks(self):
        data = FakeJVLink([b"RA" + b"x"*80, b"SE" + b"y"*80, b"HR" + b"z"*80])
        with patch.object(jv, "CHUNK_MAX_BYTES", 420):
            jv.capture(self.root, first_from="20261007000000",
                       com_factory=self.fake(data))
        outputs = sorted((self.root / "inbox" / "JRA").glob("*.jsonl"))
        self.assertGreaterEqual(len(outputs), 2)
        outputs[0].unlink()
        age = time.time() - 10
        for file in outputs[1:]:
            os.utime(file, (age, age))
        blocked = inbox.run_once(self.root, commit=False)
        self.assertEqual(blocked["validated_only"], 0)
        self.assertEqual(blocked["blocked"], len(outputs)-1)
        self.assertEqual({e["reason"] for e in blocked["events"]}, {"JV_BATCH_NOT_FINALIZED"})

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

    def test_authoritative_sha_lookup_only_queries_requested_hashes(self):
        """Thousands of historical DB hashes must never be loaded per run."""
        requested = {f"{i:064x}" for i in range(1100)}
        source = inbox.load_authorizations(self.root)["JRA"]
        calls = []

        class Cursor:
            def __init__(self, rows):
                self.rows = rows
            def fetchone(self):
                return self.rows[0] if self.rows else None
            def fetchall(self):
                return self.rows

        class FakeDatabase:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql, params):
                calls.append((sql, params))
                if "FROM atlas.data_source" in sql:
                    return Cursor([(42, "JRA", "JV_LINK", "APPROVED_INTERNAL")])
                self.assert_sql(sql)
                return Cursor([(d,) for d in params[1]])

            @staticmethod
            def assert_sql(query):
                assert "o.object_sha256 = ANY(%s)" in query
                assert "ORDER BY d.decision_id DESC LIMIT 1" in query

        with patch.object(inbox, "connect_db", return_value=FakeDatabase()):
            found = inbox._jv_verified_source_digests(source, requested)
        self.assertEqual(found, requested)
        batch_sizes = [len(args[1][1]) for args in calls[1:]]
        self.assertEqual(batch_sizes, [512, 512, 76])
        self.assertEqual(sum(batch_sizes), len(requested))
        self.assertEqual(len(calls), 4)  # one rights lookup, three bounded lookups

    def test_empty_sha_request_only_checks_registered_source(self):
        source = inbox.load_authorizations(self.root)["JRA"]
        called = []
        class Cursor:
            def fetchone(self):
                return (11, "JRA", "JV_LINK", "APPROVED_INTERNAL")
        class Db:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql, params):
                called.append(sql)
                return Cursor()
        with patch.object(inbox, "connect_db", return_value=Db()):
            self.assertEqual(inbox._jv_verified_source_digests(source, set()), set())
        self.assertEqual(len(called), 1)

    def test_verified_duplicate_receipt_avoids_rereading_large_raw_history(self):
        jv.capture(self.root, first_from="20261007000000",
                   com_factory=self.fake(FakeJVLink([b"RAabc"])))
        _, manifests = inbox._ready_jv_batches(self.root)
        self.assertEqual(len(manifests), 1)
        manifest, files = manifests[0]
        item = inbox.load_authorizations(self.root)["JRA"]
        inbox._jv_store_done_receipt(self.root, manifest, files, item)
        assert all(len(sha) == 64 for _, sha in files)
        with patch.object(inbox, "_jv_verified_source_digests",
                          return_value={sha for _, sha in files}), \
             patch.object(inbox, "commit_jv_batch",
                          side_effect=AssertionError("expensive reparse not permitted")) as expensive:
            result = inbox.run_once(self.root, commit=True, organizers=("JRA",))
        self.assertEqual(result["duplicates"], len(files))
        self.assertEqual(result["fast_duplicates"], len(files))
        self.assertEqual(result["blocked"], 0)
        expensive.assert_not_called()

    def test_db_restore_missing_objects_disables_fast_duplicate(self):
        jv.capture(self.root, first_from="20261007000000",
                   com_factory=self.fake(FakeJVLink([b"RAabc"])))
        _, manifests = inbox._ready_jv_batches(self.root)
        manifest, files = manifests[0]
        inbox._jv_store_done_receipt(
            self.root, manifest, files, inbox.load_authorizations(self.root)["JRA"]
        )
        with patch.object(inbox, "_jv_verified_source_digests", return_value=set()), \
             patch.object(inbox, "commit_jv_batch",
                          side_effect=inbox.ImportBlocked("REIMPORT_REQUIRED")) as retry:
            result = inbox.run_once(self.root, commit=True, organizers=("JRA",))
        self.assertEqual(result["duplicates"], 0)
        self.assertEqual(result["blocked"], len(files))
        self.assertEqual(result["events"][0]["reason"], "REIMPORT_REQUIRED")
        retry.assert_called_once()

    def test_cannot_cache_a_file_mutated_after_db_commit(self):
        jv.capture(self.root, first_from="20261007000000",
                   com_factory=self.fake(FakeJVLink([b"RAabc"])))
        _, manifests = inbox._ready_jv_batches(self.root)
        manifest, parts = manifests[0]
        item = inbox.load_authorizations(self.root)["JRA"]
        path, digest = parts[0]
        original = path.read_bytes()
        changed = original.replace(b"UkFhYmM=", b"UkF4eXo=")
        self.assertNotEqual(original, changed)
        path.write_bytes(changed)
        with self.assertRaisesRegex(inbox.ImportBlocked, "JV_SOURCE_CHANGED_AFTER_COMMIT"):
            inbox._jv_store_done_receipt(self.root, manifest, parts, item)
        self.assertFalse(inbox._jv_done_receipt_path(self.root, manifest).exists())

    def test_mutated_old_inbox_file_disables_fast_duplicate(self):
        jv.capture(self.root, first_from="20261007000000",
                   com_factory=self.fake(FakeJVLink([b"RAabc"])))
        _, manifests = inbox._ready_jv_batches(self.root)
        manifest, files = manifests[0]
        item = inbox.load_authorizations(self.root)["JRA"]
        inbox._jv_store_done_receipt(self.root, manifest, files, item)
        original = files[0][0].read_bytes()
        # Original remains same byte count, but the record contents differ.
        # Metadata and source SHA then require the strict byte-level path.
        tampered = original.replace(b"UkFhYmM=", b"UkF4eXo=")
        self.assertNotEqual(tampered, original)
        self.assertEqual(len(tampered), len(original))
        files[0][0].write_bytes(tampered)
        with patch.object(inbox, "_jv_verified_source_digests",
                          return_value={sha for _, sha in files}):
            blocked = inbox.run_once(self.root, commit=True, organizers=("JRA",))
        self.assertEqual(blocked["blocked"], len(files))
        self.assertEqual(blocked["events"][0]["reason"], "JV_CHUNK_HASH_MISMATCH")
        self.assertEqual(blocked["duplicates"], 0)

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

    def test_endless_jvlink_file_switch_does_not_spin_forever(self):
        client = FakeJVLink([-1, -1, -1, -1])
        ticks = iter([0.0, 0.2, 1.1])
        slept = []
        with self.assertRaisesRegex(
            jv.CaptureBlocked, "JVGETS_FILE_SWITCH_TIMEOUT"
        ):
            jv.capture(
                self.root, first_from="20261007000000",
                com_factory=self.fake(client), max_idle=1,
                monotonic=lambda: next(ticks),
                sleep=lambda seconds: slept.append(seconds),
            )
        self.assertEqual(slept, [0.1])
        self.assertEqual(client.close_calls, 1)
        self.assertFalse((self.root / "receipts" / "jra_jvlink_cursor.json").exists())
        self.assertFalse(list((self.root / "inbox" / "JRA").glob("*.jsonl")))

    def test_switch_then_real_record_resets_progress_timer(self):
        client = FakeJVLink([-1, b"RAabc", -1, b"SEdef"])
        ticks = iter([0.0, 0.1, 0.2, 0.3, 0.4])
        result = jv.capture(
            self.root, first_from="20261007000000",
            com_factory=self.fake(client), max_idle=1,
            monotonic=lambda: next(ticks), sleep=lambda _: None,
        )
        self.assertEqual(result["records"], 2)
        self.assertEqual(result["status"], "CAPTURED_RAW_IN_INBOX")

    def test_closed_failure_does_not_advance(self):
        obj = FakeJVLink([b"RAabc"], close=-100)
        with self.assertRaisesRegex(jv.CaptureBlocked, "JVCLOSE_FAILED"):
            jv.capture(self.root, first_from="20261007000000", com_factory=self.fake(obj))
        self.assertFalse((self.root / "receipts" / "jra_jvlink_cursor.json").exists())
        self.assertEqual(list((self.root / "inbox" / "JRA").glob("*.jsonl")), [])


@unittest.skipUnless(os.environ.get("ATLAS_TEST_POSTGRES"), "Dedicated synthetic CI PostgreSQL only")
class PgIntegration(CaptureTests):
    def test_real_postgres_multichunk_batch_is_atomic_after_failure(self):
        """A simulated DB error in the SECOND chunk must roll back the FIRST."""
        from unittest.mock import patch

        config = self.root / "sources.local.json"
        auth = json.loads(config.read_text(encoding="utf-8"))
        auth["JRA"]["source_code"] = "ATLAS_JRA_CI_BATCH_ATOMIC"
        config.write_text(json.dumps(auth), encoding="utf-8")
        inbox.enroll_sources(self.root)

        sample = FakeJVLink([
            b"RA" + b"x"*80,
            b"SE" + b"y"*80,
            b"HR" + b"z"*80,
        ])
        with patch.object(jv, "CHUNK_MAX_BYTES", 420):
            receipt = jv.capture(
                self.root, first_from="20261007000000",
                com_factory=self.fake(sample),
            )
        self.assertGreaterEqual(receipt["chunks"], 2)
        age = time.time() - 10
        for file in (self.root / "inbox" / "JRA").glob("*.jsonl"):
            os.utime(file, (age, age))

        source_code = auth["JRA"]["source_code"]
        with inbox.connect_db() as con:
            source_id = con.execute(
                "SELECT source_id FROM atlas.data_source WHERE source_code=%s",
                (source_code,),
            ).fetchone()[0]
            before = con.execute(
                "SELECT count(*) FROM atlas.raw_observation WHERE source_id=%s",
                (source_id,),
            ).fetchone()[0]

        original = inbox._commit_records_tx
        calls = [0]

        def fail_second(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 2:
                raise inbox.ImportBlocked("SIMULATED_SECOND_CHUNK_DB_FAILURE")
            return original(*args, **kwargs)

        with patch.object(inbox, "_commit_records_tx", side_effect=fail_second):
            failed = inbox.run_once(self.root, commit=True, organizers=("JRA",))
        self.assertEqual(calls[0], 2)
        self.assertEqual(failed["imported"], 0)
        self.assertEqual(failed["blocked"], receipt["chunks"])
        with inbox.connect_db() as con:
            after = con.execute(
                "SELECT count(*) FROM atlas.raw_observation WHERE source_id=%s",
                (source_id,),
            ).fetchone()[0]
        self.assertEqual(before, after, "NO chunk may survive a failed batch")

        passed = inbox.run_once(self.root, commit=True, organizers=("JRA",))
        self.assertEqual(passed["imported"], receipt["chunks"])
        self.assertEqual(passed["blocked"], 0)
        retried = inbox.run_once(self.root, commit=True, organizers=("JRA",))
        self.assertEqual(retried["duplicates"], receipt["chunks"])
        with inbox.connect_db() as con:
            rows = con.execute(
                "SELECT count(*) FROM atlas.raw_observation WHERE source_id=%s",
                (source_id,),
            ).fetchone()[0]
        self.assertEqual(rows-before, 3)

    def test_later_rejection_invalidates_accelerated_duplicate_cache(self):
        config = self.root / "sources.local.json"
        auth = json.loads(config.read_text(encoding="utf-8"))
        auth["JRA"]["source_code"] = "ATLAS_JRA_CI_REJECTED_FAST"
        config.write_text(json.dumps(auth), encoding="utf-8")
        inbox.enroll_sources(self.root)
        jv.capture(
            self.root, first_from="20261007000000",
            com_factory=self.fake(FakeJVLink([b"RAabc"])),
        )
        first = inbox.run_once(self.root, commit=True, organizers=("JRA",))
        self.assertEqual(first["imported"], 1)
        repeat = inbox.run_once(self.root, commit=True, organizers=("JRA",))
        self.assertEqual(repeat["duplicates"], 1)

        with inbox.connect_db() as con:
            con.execute(
                "INSERT INTO atlas.ingest_decision "
                "(object_id,decision,validated_record_count,"
                "quarantined_record_count,policy_version) "
                "SELECT o.object_id, 'REJECTED', 0, 1, 'SYNTHETIC_REVOCATION' "
                "FROM atlas.import_object o "
                "JOIN atlas.data_source s ON s.source_id=o.source_id "
                "WHERE s.source_code=%s",
                (auth["JRA"]["source_code"],),
            )
        # Old VALIDATED decision still exists, but latest REJECTED must win.
        blocked = inbox.run_once(self.root, commit=True, organizers=("JRA",))
        self.assertEqual(blocked["duplicates"], 0)
        self.assertEqual(blocked["blocked"], 1)
        self.assertEqual(
            blocked["events"][0]["reason"], "EXISTING_BATCH_UNVERIFIED"
        )

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
