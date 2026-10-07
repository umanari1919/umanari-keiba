"""Synthetic-only local forecast-freeze and result-reconciliation tests."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import forward_blind as f


class ForwardBlindTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.seal_time = datetime.fromisoformat("2026-10-10T09:00:02+09:00")
        self.outcome_time = datetime.fromisoformat("2026-10-10T11:00:01+09:00")
        self.rid = "2026101005010101"
        self.runners = [
            {"horse_id": "2020000001", "horse_number": "1", "jockey_25": [.6, 1., 1.]},
            {"horse_id": "2020000002", "horse_number": "2", "jockey_25": [.4, 1., 1.]},
        ]
        self.source = {
            "payload": {
                "races": [{"race_id": self.rid, "venue": "05", "distance": "1600",
                           "track": "11", "grade": "", "race_class": "005",
                           "start_time": "1000", "registered": "02", "created": "20261010"}],
                "runners": [
                    {"race_id": self.rid, "horse_id": r["horse_id"], "horse_number": r["horse_number"],
                     "jockey_id": "01234", "trainer_id": "01234", "created": "20261010"}
                    for r in self.runners],
                "workouts": [],
            },
            "metadata": {"runner_status": [
                {"race_id": self.rid, "horse_id": r["horse_id"], "horse_name": "テスト馬",
                 "abnormal_code": "0"} for r in self.runners]},
        }
        self.run = {
            "state": "personal_predictions_saved",
            "model": "jockey_25",
            "captured_at": "2026-10-10T09:00:00+09:00",
            "created_at": "2026-10-10T09:00:01+09:00",
            "automatic_betting": False, "production_promotion": False,
            "database_modified": False, "read_only_connection": dict(f.READONLY),
            "source_sha256": "", "source_path": "",
            "history_sha256": "a" * 64, "model_seal_sha256": "b" * 64,
            "predicted_races": 1, "predicted_runners": 2,
            "input_checks": {"capture_finished_at": "2026-10-10T09:00:00+09:00",
                             "races": [{"race_id": self.rid, "input_checks_passed": True}]},
            "predictions": [{"race_id": self.rid, "venue": "05", "start_time": "1000",
                             "distance": "1600", "runners": self.runners}],
        }
        self.results = {
            "observed_at": "2026-10-10T11:00:00+09:00",
            "read_only_connection": dict(f.READONLY),
            "source": "verified-readonly-result-extract",
            "rows": [
                {"race_id": self.rid, "horse_id": "2020000001", "finish_position": 1,
                 "result_status": "FINISHED"},
                {"race_id": self.rid, "horse_id": "2020000002", "finish_position": 2,
                 "result_status": "FINISHED"},
            ],
        }

    def artifact(self, data):
        assets = self.root / f.PERSONAL / "assets"
        runs = self.root / f.PERSONAL / "runs"
        assets.mkdir(parents=True, exist_ok=True)
        runs.mkdir(parents=True, exist_ok=True)
        payload = f.encoded(self.source)
        sha = f.digest(payload)
        (assets / ("source-" + sha + ".json")).write_bytes(payload)
        self.run["source_sha256"] = sha
        self.run["source_path"] = (Path(f.PERSONAL) / "assets" / ("source-" + sha + ".json")).as_posix()
        if data is not None:
            data(self.run)
        raw = f.encoded(self.run)
        path = runs / (f.digest(raw) + ".json")
        path.write_bytes(raw)
        return path

    def freeze(self, mutate=None, now=None):
        return f.freeze_run(self.artifact(mutate), root=self.root,
                            now=now or self.seal_time)

    def results_file(self):
        path = self.root / "final-results.json"
        path.write_bytes(f.encoded(self.results))
        return path

    def test_freeze_is_content_addressed_and_locally_verifiable(self):
        receipt = self.freeze()
        payload = f.verify_receipt(receipt, root=self.root)
        self.assertEqual(payload["status"], "LOCAL_PRESTART_SEALED_UNATTESTED")
        self.assertFalse(payload["independent_timestamp_attestation"])
        self.assertEqual(self.freeze(), receipt)
        self.assertEqual(len(list(receipt.parent.glob("*.json"))), 1)

    def test_tampered_receipt_or_source_is_rejected(self):
        receipt = self.freeze()
        saved = f.read(receipt)
        saved["receipt"]["production_approved"] = True
        receipt.write_bytes(f.encoded(saved))
        with self.assertRaisesRegex(ValueError, "Tampered"):
            f.verify_receipt(receipt, root=self.root)
        with self.assertRaisesRegex(ValueError, "modified"):
            self.freeze()
        receipt.unlink()
        receipt = self.freeze()
        source = self.root / f.read(receipt)["receipt"]["source_path"]
        source.write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "source changed"):
            f.verify_receipt(receipt, root=self.root)

    def test_late_or_historical_predictions_cannot_be_backfilled(self):
        with self.assertRaises(ValueError):
            self.freeze(now=datetime.fromisoformat("2026-10-10T10:00:00+09:00"))
        with self.assertRaisesRegex(ValueError, "stale"):
            self.freeze(now=datetime.fromisoformat("2026-10-10T09:03:00+09:00"))
        with self.assertRaisesRegex(ValueError, "timestamps"):
            self.freeze(lambda d: d.update(created_at="2026-10-10T09:05:00+09:00"))

    def test_outcome_odds_and_bad_rosters_are_refused_at_freeze(self):
        cases = [
            lambda d: d["predictions"][0]["runners"][0].update(finish_position=1),
            lambda d: d["predictions"][0]["runners"][0].update(jockey_25=[.9, .5, 1.]),
            lambda d: d["predictions"][0]["runners"][0].update(jockey_25=[.9, 1., 1.]),
            lambda d: d["predictions"][0]["runners"][0].update(horse_id="2020000099"),
            lambda d: d.update(read_only_connection={"transaction_read_only": "off"}),
            lambda d: d.update(model="experimental-workout"),
        ]
        original = copy.deepcopy(self.run)
        for mutation in cases:
            with self.subTest(mutation=mutation):
                self.run = copy.deepcopy(original)
                with self.assertRaises(ValueError):
                    self.freeze(mutation)

    def test_injected_result_field_in_source_is_refused(self):
        self.source["payload"]["runners"][0]["finish_position"] = 1
        with self.assertRaisesRegex(ValueError, "Outcome"):
            self.freeze()
        del self.source["payload"]["runners"][0]["finish_position"]
        self.source["metadata"]["runner_status"][0]["abnormal_code"] = "1"
        with self.assertRaisesRegex(ValueError, "status"):
            self.freeze()

    def test_complete_results_three_targets_and_metrics(self):
        receipt = self.freeze()
        scored = f.score_receipt(receipt, self.results_file(), root=self.root,
                                 now=self.outcome_time)
        result = f.read(scored)
        self.assertEqual(result["status"], "SCORED_LOCAL_ONLY")
        self.assertFalse(result["prospective_verified"])
        self.assertEqual(result["scored_races"], 1)
        self.assertEqual(result["metrics"]["all"]["runners"], 2)
        self.assertAlmostEqual(result["metrics"]["all"]["targets"]["win"]["brier"], .16)
        for goal in f.TARGETS:
            self.assertEqual(result["metrics"]["all"]["targets"][goal]["top1_accuracy"], 1.)
        self.assertIn("2026_JRA", result["metrics"])
        self.assertEqual(f.score_receipt(receipt, self.results_file(), root=self.root,
                                         now=self.outcome_time), scored)

    def test_missing_outcome_and_ties_are_quarantined_not_negative(self):
        receipt = self.freeze()
        self.results["rows"].pop()
        partial = f.read(f.score_receipt(receipt, self.results_file(), root=self.root,
                                         now=self.outcome_time))
        self.assertEqual(partial["status"], "QUARANTINED")
        self.assertEqual(partial["scored_races"], 0)
        self.assertEqual(partial["metrics"]["all"]["runners"], 0)
        self.assertEqual(partial["quarantined_races"][0]["reason"],
                         "MISSING_OR_CHANGED_FINAL_ROSTER")
        self.results["rows"].append({"race_id": self.rid, "horse_id": "2020000002",
                                     "finish_position": 1, "result_status": "FINISHED"})
        tied = f.read(f.score_receipt(receipt, self.results_file(), root=self.root,
                                      now=self.outcome_time))
        self.assertEqual(tied["quarantined_races"][0]["reason"],
                         "TIE_OR_INCOMPLETE_PODIUM")

    def test_result_identity_and_time_violations(self):
        receipt = self.freeze()
        self.results["rows"].append(dict(self.results["rows"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            f.score_receipt(receipt, self.results_file(), root=self.root,
                            now=self.outcome_time)
        self.results["rows"].pop()
        self.results["observed_at"] = "2026-10-10T09:00:01+09:00"
        with self.assertRaisesRegex(ValueError, "follow"):
            f.score_receipt(receipt, self.results_file(), root=self.root,
                            now=self.outcome_time)

    def test_result_nonfinisher_requires_explicit_status(self):
        receipt = self.freeze()
        self.results["rows"][1].update(finish_position=None, result_status="DID_NOT_FINISH")
        quarantined = f.read(f.score_receipt(receipt, self.results_file(), root=self.root,
                                             now=self.outcome_time))
        self.assertEqual(quarantined["status"], "QUARANTINED")
        self.assertNotEqual(quarantined["quarantined_races"][0]["reason"],
                            "MISSING_OR_CHANGED_FINAL_ROSTER")


if __name__ == "__main__":
    unittest.main()
