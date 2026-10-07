"""Synthetic-only tests: result DB is never contacted in CI."""
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import forward_blind as blind
import forward_results as result
import test_forward_blind as fixture_module


class ResultAdapterTests(unittest.TestCase):
    def setUp(self):
        self.fixt = fixture_module.ForwardBlindTests(
            methodName="test_freeze_is_content_addressed_and_locally_verifiable"
        )
        self.fixt.setUp()
        self.addCleanup(self.fixt.doCleanups)
        self.receipt = self.fixt.freeze()
        self.clock_now = datetime.fromisoformat("2026-10-10T11:40:00+09:00")
        self.query_log = []
        self.rows = [
            {"race_id": self.fixt.rid, "horse_id": "2020000001",
             "finish_position": "01", "abnormal_code": "0"},
            {"race_id": self.fixt.rid, "horse_id": "2020000002",
             "finish_position": "02", "abnormal_code": "0"},
        ]
        self.read_only = dict(blind.READONLY)

    def query(self, sql):
        self.query_log.append(sql)
        return self.read_only if sql == result.READONLY_SQL else self.rows

    def collect(self):
        return result.collect(self.receipt, root=self.fixt.root,
                              query_fn=self.query, clock=lambda: self.clock_now)

    def test_no_database_contact_for_offline_receipt_check(self):
        info = result.receipt_info(self.receipt, root=self.fixt.root,
                                   clock=self.clock_now)
        self.assertTrue(info["ready"])
        self.assertEqual(info["race_ids"], [self.fixt.rid])
        self.assertEqual(self.query_log, [])

    def test_waits_for_results_without_even_readonly_db_probe(self):
        self.clock_now = datetime.fromisoformat("2026-10-10T11:29:59+09:00")
        with self.assertRaisesRegex(ValueError, "NOT_MATURE"):
            self.collect()
        self.assertEqual(self.query_log, [])

    def test_safe_fixed_sql_and_correct_three_target_scoring(self):
        report = self.collect()
        self.assertEqual(report["status"], "SCORED_LOCAL_ONLY")
        self.assertFalse(report["prospective_verified"])
        self.assertFalse(report["production_approved"])
        self.assertEqual(report["scored_races"], 1)
        self.assertEqual(report["quarantined_races"], 0)
        self.assertEqual(self.query_log[0], result.READONLY_SQL)
        self.assertIn("public.umagoto_race_joho", self.query_log[1])
        self.assertIn("kakutei_chakujun", self.query_log[1])
        self.assertNotIn("UPDATE ", self.query_log[1])
        self.assertNotIn("DELETE ", self.query_log[1])
        export = blind.read(report["result_export_path"])
        self.assertEqual(export["source"], result.RESULT_SOURCE)
        self.assertEqual(export["rows"][0]["finish_position"], 1)
        scored = blind.read(report["score_path"])
        self.assertEqual(scored["metrics"]["all"]["races"], 1)
        self.assertEqual(scored["metrics"]["all"]["targets"]["win"]["top1_accuracy"], 1.)
        self.assertIn("2026_JRA", scored["metrics"])
        self.assertEqual(self.collect()["result_export_sha256"],
                         report["result_export_sha256"])

    def test_database_not_confirmed_read_only_stops_before_results(self):
        self.read_only["transaction_read_only"] = "off"
        with self.assertRaisesRegex(ValueError, "read-only"):
            self.collect()
        self.assertEqual(len(self.query_log), 1)
        self.assertEqual(list(self.fixt.root.rglob("exports/*.json")), [])

    def test_duplicate_or_unknown_identity_never_published(self):
        self.rows.append(dict(self.rows[0]))
        with self.assertRaisesRegex(ValueError, "Duplicate DB"):
            self.collect()
        self.assertFalse(list(self.fixt.root.rglob("exports/*.json")))
        self.rows.pop()
        self.rows[0]["race_id"] = "1999010105010101"
        with self.assertRaisesRegex(ValueError, "unknown result identity"):
            self.collect()

    def test_missing_results_are_quarantined_not_made_negative(self):
        self.rows.pop()
        summary = self.collect()
        self.assertEqual(summary["status"], "QUARANTINED")
        self.assertEqual(summary["scored_races"], 0)
        self.assertEqual(summary["quarantined_races"], 1)
        scores = blind.read(summary["score_path"])
        self.assertEqual(scores["metrics"]["all"]["runners"], 0)

    def test_nonstarter_and_unresolved_finishes_remain_quarantined(self):
        for abn, finish in [("1", ""), ("0", ""), ("4", "00"), ("8", "01")]:
            with self.subTest(abnormal_code=abn, raw_finish=finish):
                self.rows[1]["abnormal_code"] = abn
                self.rows[1]["finish_position"] = finish
                summary = self.collect()
                self.assertEqual(summary["status"], "QUARANTINED")
                self.assertEqual(summary["scored_races"], 0)

    def test_no_result_guessing_on_blank_codes(self):
        raw = [{"race_id": self.fixt.rid, "horse_id": "2020000001",
                "finish_position": "", "abnormal_code": ""}]
        standardized = result.normalize(raw, [self.fixt.rid])
        self.assertEqual(standardized[0]["result_status"], "UNRESOLVED")
        self.assertIsNone(standardized[0]["finish_position"])

    def test_null_result_fields_are_unresolved_not_negative(self):
        raw = [{"race_id": self.fixt.rid, "horse_id": "2020000001",
                "finish_position": None, "abnormal_code": None}]
        rows = result.normalize(raw, [self.fixt.rid])
        self.assertEqual(rows[0]["result_status"], "UNRESOLVED")
        self.assertIsNone(rows[0]["finish_position"])
        self.rows[1].update(finish_position=None, abnormal_code=None)
        summary = self.collect()
        self.assertEqual(summary["status"], "QUARANTINED")
        self.assertEqual(summary["scored_races"], 0)

    def test_sql_injection_and_wrong_scopes_rejected(self):
        for rid in ("1'; DROP TABLE;--", "abc", "１２３４５６７８９０１２３４５６"):
            with self.subTest(rid=rid):
                with self.assertRaises(ValueError):
                    result.select_sql([rid])
        with self.assertRaises(ValueError):
            result.select_sql([self.fixt.rid, self.fixt.rid])
        with self.assertRaises(ValueError):
            result.select_sql([])

    def test_db_failure_leaves_no_partial_artifacts(self):
        def failing(sql):
            raise RuntimeError("connection refused")
        with self.assertRaises(RuntimeError):
            result.collect(self.receipt, root=self.fixt.root,
                           query_fn=failing, clock=lambda: self.clock_now)
        self.assertFalse(list(self.fixt.root.rglob("exports/*.json")))

    def test_same_day_capture_or_modified_receipt_refused(self):
        receipt = blind.read(self.receipt)
        receipt["receipt"]["prediction_path"] = "../../untrusted.json"
        self.receipt.write_bytes(blind.encoded(receipt))
        with self.assertRaisesRegex(ValueError, "Tampered"):
            result.receipt_info(self.receipt, root=self.fixt.root,
                                clock=self.clock_now)


if __name__ == "__main__":
    unittest.main()
