"""ATLAS-JVDATA-MAP-003 synthetic binary layout and isolated PostgreSQL tests."""
import base64
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import atlas_inbox as inbox
import atlas_jvdata_map as m


def write(raw: bytearray, pos: int, value: str, length: int):
    data = value.encode("ascii")
    assert len(data) == length
    raw[pos - 1 : pos - 1 + length] = data


def make(kind="RA", phase="2", *, race="2026101005010101",
         horse="2020100001", number="01", finish="01", abnormal="0"):
    size = {"RA": 1272, "SE": 555}[kind]
    raw = bytearray(b"0" * size)
    raw[-2:] = b"\r\n"
    write(raw, 1, kind, 2)
    write(raw, 3, phase, 1)
    write(raw, 4, "20261008", 8)
    write(raw, 12, race, 16)
    if kind == "RA":
        write(raw, 698, "1600", 4)
        write(raw, 706, "17", 2)
        write(raw, 874, "1530", 4)
    else:
        write(raw, 29, number, 2)
        write(raw, 31, horse, 10)
        name = "合成テスト馬".encode("cp932")
        raw[40:76] = name + b" " * (36 - len(name))
        write(raw, 332, abnormal, 1)
        write(raw, 335, finish, 2)
    assert len(raw) == size
    return bytes(raw)


def envelope(data):
    return {
        "jv_dataspec": "RACE",
        "record_spec": data[:2].decode("ascii"),
        "encoding": "cp932",
        "raw_base64": base64.b64encode(data).decode("ascii"),
        "raw_sha256": hashlib.sha256(data).hexdigest(),
    }


class ParsingTests(unittest.TestCase):
    def test_official_RA_layout_date_distance_and_venue(self):
        rec = m.parsed(envelope(make("RA")))
        self.assertEqual(rec["kind"], "RA")
        self.assertEqual(rec["race_number"], 1)
        self.assertEqual(rec["venue_code"], "05")
        self.assertEqual(rec["distance_m"], 1600)
        self.assertEqual(rec["native_race_id"], "JRA:20261010:05:01:01:01")
        self.assertEqual(rec["scheduled_start"].isoformat(), "2026-10-10T15:30:00+09:00")
        self.assertEqual(rec["card_phase"], "CONFIRMED_CARD")
        self.assertIsNone(rec["surface"])
        self.assertFalse(rec["pre_race_certified"])

    def test_SE_cp932_multibyte_horse_and_official_id(self):
        rec = m.parsed(envelope(make("SE")))
        self.assertEqual(rec["horse_name"], "合成テスト馬")
        self.assertEqual(rec["official_horse_id"], "2020100001")
        self.assertEqual(rec["horse_number"], 1)
        self.assertEqual(rec["runner_status"], "CONFIRMED")
        self.assertIsNone(rec["finish_position"])

    def test_provisional_result_cannot_be_a_label(self):
        self.assertIsNone(m.parsed(envelope(make("SE", "5"))))
        rec = m.parsed(envelope(make("SE", "7", finish="02")))
        self.assertEqual(rec["result_status"], "FINISHED")
        self.assertEqual(rec["finish_position"], 2)

    def test_abnormal_starts_are_not_fabricated_losses(self):
        for code in ("1", "2", "3", "4", "5", "6", "7"):
            row = m.parsed(envelope(make("SE", "7", abnormal=code, finish="00")))
            self.assertIsNone(row["finish_position"])
            self.assertTrue(row["results_withheld"])
        self.assertEqual(m.parsed(envelope(make("SE", "7", abnormal="1")))["result_status"],
                         "NON_STARTER")
        self.assertEqual(m.parsed(envelope(make("SE", "7", abnormal="4")))["result_status"],
                         "DID_NOT_FINISH")
        self.assertEqual(m.parsed(envelope(make("SE", "7", abnormal="5")))["result_status"],
                         "UNRESOLVED")

    def test_no_foreign_race_or_deletion_is_promoted(self):
        self.assertIsNone(m.parsed(envelope(make("RA", "A"))))
        with self.assertRaisesRegex(m.MappingBlocked, "SOURCE_DELETE"):
            m.parsed(envelope(make("RA", "0")))
        with self.assertRaisesRegex(m.MappingBlocked, "UNRECOGNIZED_JRA_VENUE"):
            m.parsed(envelope(make("RA", "7", race="2026101011010101")))

    def test_missing_and_wrong_fields_fail_closed(self):
        original = make("SE", "7")
        bad = envelope(original[:-5])
        bad["raw_sha256"] = hashlib.sha256(original[:-5]).hexdigest()
        with self.assertRaisesRegex(m.MappingBlocked, "LENGTH"):
            m.parsed(bad)
        bad = envelope(original)
        bad["raw_sha256"] = "0" * 64
        with self.assertRaisesRegex(m.MappingBlocked, "SOURCE_RECORD_HASH"):
            m.parsed(bad)
        with self.assertRaisesRegex(m.MappingBlocked, "RAW_PAYLOAD_HASH"):
            m.parsed(envelope(original), "0" * 64)
        with self.assertRaisesRegex(m.MappingBlocked, "OUT_OF_RANGE"):
            m.parsed(envelope(make("SE", "7", number="00")))
        with self.assertRaisesRegex(m.MappingBlocked, "OUT_OF_RANGE"):
            m.parsed(envelope(make("SE", "7", finish="00")))


@unittest.skipUnless(os.environ.get("ATLAS_TEST_POSTGRES"), "Ephemeral PostgreSQL CI only")
class DbMappingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        inbox.setup(self.root)
        path = self.root / "sources.local.json"
        source = json.loads(path.read_text(encoding="utf-8"))
        source["JRA"]["source_code"] = "CI_" + self._testMethodName.upper()[:50]
        source["JRA"].update({
            "enabled": True,
            "rights_status": "APPROVED_INTERNAL",
            "authorization_reference": "SYNTHETIC_CI_ONLY",
        })
        path.write_text(json.dumps(source), encoding="utf-8")
        self.code = source["JRA"]["source_code"]
        self.batch_number = 0
        self.race_day = {
            "test_invalid_record_rolls_back_whole_batch": "20261012",
            "test_orphan_runner_stays_pending_until_ra_exists": "20261011",
        }.get(self._testMethodName, "20261010")
        inbox.enroll_sources(self.root)

    def ingest(self, raws, *, name="map.jsonl"):
        # Give each test its own race/day, without touching existing CI DB rows.
        fixed = []
        for raw in raws:
            sample = bytearray(raw)
            write(sample, 12, self.race_day, 8)
            fixed.append(bytes(sample))
        lines = [
            json.dumps({
                "native_kind": "JVDATA",
                "native_key": f"JV-{i+1:010d}",
                "payload": envelope(item),
                "provider_published_at": None,
                "event_time": None,
            }) for i, item in enumerate(fixed)
        ]
        content = ("\n".join(lines) + "\n").encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        name = f"jv_RACE_20261007000000_{self.batch_number:06d}_{digest[:16]}.jsonl"
        self.batch_number += 1
        destination = self.root / "inbox" / "JRA" / name
        destination.write_bytes(content)
        folder = self.root / "receipts" / "jra_jvlink_batches"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"batch-{self.batch_number:06d}.json").write_text(json.dumps({
            "format": "ATLAS_JVLINK_RAW_BATCH_V1",
            "dataspec": "RACE",
            "chunks": [{"filename": name, "sha256": digest, "bytes": len(content)}],
        }), encoding="utf-8")
        # Actual JV-Link publisher uses a named manifest, not an arbitrary batch key.
        manifest = folder / f"batch-{self.batch_number:06d}.json"
        manifest.rename(folder / f"jv_RACE_20261007000000_{digest[:16]}.json")
        age = time.time() - 10
        os.utime(destination, (age, age))
        report = inbox.run_once(self.root, commit=True)
        self.assertEqual(report["imported"], 1, report)

    def test_previews_are_read_only_and_full_mapping_is_idempotent(self):
        self.ingest([
            make("RA", "2"), make("SE", "2"),
            make("RA", "7"), make("SE", "7", finish="01"),
            make("SE", "7", horse="2021100002", number="02",
                 finish="00", abnormal="4"),
        ])
        preview = m.run(self.code, apply=False)
        self.assertEqual(preview["objects"], 1)
        self.assertEqual(preview["mapped"], 0)
        with inbox.connect_db() as con:
            count = con.execute(
                "SELECT count(*) FROM atlas.race_observation ro "
                "JOIN atlas.import_object io ON ro.object_id=io.object_id "
                "JOIN atlas.data_source ds ON ds.source_id=io.source_id "
                "WHERE ds.source_code=%s", (self.code,)
            ).fetchone()[0]
            self.assertEqual(count, 0)

        done = m.run(self.code, apply=True)
        self.assertEqual(done["mapped"], 1)
        self.assertEqual(done["withheld"], 1)
        with inbox.connect_db() as con:
            src_id = con.execute(
                "SELECT source_id FROM atlas.data_source WHERE source_code=%s",
                (self.code,),
            ).fetchone()[0]
            def count(table):
                if table in ("race", "horse"):
                    identifiers = "race_identifier" if table == "race" else "horse_identifier"
                    return con.execute(
                        f"SELECT count(*) FROM atlas.{identifiers} WHERE source_id=%s",
                        (src_id,),
                    ).fetchone()[0]
                if table == "horse_identifier":
                    return con.execute(
                        "SELECT count(*) FROM atlas.horse_identifier WHERE source_id=%s",
                        (src_id,),
                    ).fetchone()[0]
                return con.execute(
                    f"SELECT count(*) FROM atlas.{table} a "
                    "JOIN atlas.import_object io ON io.object_id=a.object_id "
                    "WHERE io.source_id=%s", (src_id,),
                ).fetchone()[0]
            self.assertEqual(count("race"), 1)
            self.assertEqual(count("horse"), 2)
            self.assertEqual(count("horse_identifier"), 2)
            self.assertEqual(count("race_observation"), 2)
            self.assertEqual(count("runner_observation"), 3)
            self.assertEqual(count("result_observation"), 2)
            self.assertEqual(count("canonicalization_batch"), 1)
            self.assertEqual(count("quarantine_issue"), 1)
            finished = con.execute(
                "SELECT result_status,finish_position FROM atlas.result_observation "
                "WHERE finish_position IS NOT NULL",
            ).fetchone()
            self.assertEqual(finished, ("FINISHED", 1))
            withheld = con.execute(
                "SELECT result_status,finish_position FROM atlas.result_observation "
                "WHERE result_status='DID_NOT_FINISH'",
            ).fetchone()
            self.assertEqual(withheld, ("DID_NOT_FINISH", None))
        again = m.run(self.code, apply=True)
        self.assertEqual(again["objects"], 0)

    def test_orphan_runner_stays_pending_until_ra_exists(self):
        self.ingest([make("SE", "2")])
        blocked = m.run(self.code, apply=True)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertEqual(blocked["reports"][0]["reason"], "RACE_HEADER_NOT_YET_AVAILABLE")
        with inbox.connect_db() as con:
            self.assertEqual(con.execute(
                "SELECT count(*) FROM atlas.horse_identifier hi "
                "JOIN atlas.data_source ds ON ds.source_id=hi.source_id "
                "WHERE ds.source_code=%s", (self.code,),
            ).fetchone()[0], 0)
        self.ingest([make("RA", "2")], name="race.jsonl")
        # The queue blocks first; later object can run in same scan.
        m.run(self.code, apply=True)
        result = m.run(self.code, apply=True)
        self.assertEqual(result["mapped"], 1)

    def test_invalid_record_rolls_back_whole_batch(self):
        self.ingest([make("RA", "2"), make("SE", "7", abnormal="0", finish="00")])
        outcome = m.run(self.code, apply=True)
        self.assertEqual(outcome["status"], "BLOCKED")
        self.assertEqual(outcome["reports"][0]["reason"], "NUMBER_FIELD_OUT_OF_RANGE")
        with inbox.connect_db() as con:
            self.assertEqual(con.execute(
                "SELECT count(*) FROM atlas.race_identifier ri "
                "JOIN atlas.data_source ds ON ds.source_id=ri.source_id "
                "WHERE ds.source_code=%s", (self.code,),
            ).fetchone()[0], 0)
            self.assertEqual(con.execute(
                "SELECT count(*) FROM atlas.canonicalization_batch cb "
                "JOIN atlas.import_object io ON io.object_id=cb.object_id "
                "JOIN atlas.data_source ds ON ds.source_id=io.source_id "
                "WHERE ds.source_code=%s", (self.code,),
            ).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
