import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import weekend_replay as replay


def conditions(rid):
    return {
        rid: {
            "race_id": rid,
            "distance": "1600",
            "track": "11",
            "grade": "",
            "race_class": "005",
        }
    }


def records(rid, finishes=("1", "2"), abnormal=("0", "0")):
    return {
        rid: [
            {"race_id": rid, "horse_id": "2020000001", "finish": finishes[0], "abnormal": abnormal[0]},
            {"race_id": rid, "horse_id": "2020000002", "finish": finishes[1], "abnormal": abnormal[1]},
        ]
    }


def ids(rid):
    return {
        (rid, "2020000001"): "01001",
        (rid, "2020000002"): "01002",
    }


class WeekendReplayTests(unittest.TestCase):
    def seeded(self):
        stores = replay.make_stores()
        replay.set_day(stores, "20261002")
        stores["general"].add("2020000001", 1)
        stores["general"].add("2020000002", 0)
        stores["jockey"].add("01001", 1)
        stores["jockey"].add("01002", 0)
        return stores

    def test_target_day_results_do_not_change_frozen_probabilities(self):
        rid = "2026100305010101"
        a = replay.score_day("20261003", records(rid, ("1", "2")), conditions(rid), ids(rid), self.seeded())
        b = replay.score_day("20261003", records(rid, ("2", "1")), conditions(rid), ids(rid), self.seeded())
        pa = {r["horse_id"]: r["jockey_25"] for r in a[0]["runners"]}
        pb = {r["horse_id"]: r["jockey_25"] for r in b[0]["runners"]}
        self.assertEqual(pa, pb)

    def test_prior_day_update_can_change_next_day_prediction(self):
        rid1 = "2026100305010101"
        rid2 = "2026100405010101"
        stores = self.seeded()
        before = replay.score_day("20261003", records(rid1), conditions(rid1), ids(rid1), stores)
        p_before = before[0]["runners"][0]["jockey_25"][0]
        replay.update_day("20261003", records(rid1), conditions(rid1), ids(rid1), stores)
        after = replay.score_day("20261004", records(rid2), conditions(rid2), ids(rid2), stores)
        p_after = after[0]["runners"][0]["jockey_25"][0]
        self.assertNotEqual(p_before, p_after)

    def test_cancelled_final_roster_is_not_scored(self):
        rid = "2026100305010101"
        scored = replay.score_day(
            "20261003",
            records(rid, ("1", "2"), ("0", "1")),
            conditions(rid),
            ids(rid),
            self.seeded(),
        )
        self.assertEqual(scored[0]["result_state"], "final_roster_changed")
        self.assertIsNone(scored[0]["_metrics"])

    def test_display_metadata_requires_read_only_connection(self):
        prediction = [{
            "race_id": "2026100305010101",
            "runners": [{"horse_id": "2020000001", "jockey_25": [1.0, 1.0, 1.0]}],
        }]
        def bad(_sql):
            return {"transaction_read_only": "off", "default_transaction_read_only": "on"}
        with self.assertRaises(ValueError):
            replay.attach_display_metadata(copy.deepcopy(prediction), query_fn=bad)

    def test_display_metadata_is_not_model_input(self):
        prediction = [{
            "race_id": "2026100305010101",
            "runners": [{"horse_id": "2020000001", "jockey_25": [1.0, 1.0, 1.0]}],
        }]
        calls = []
        def fake(sql):
            calls.append(sql)
            if "current_setting" in sql:
                return replay.READONLY
            return [{
                "race_id": "2026100305010101",
                "horse_id": "2020000001",
                "horse_number": "7",
                "horse_name": "テスト馬",
            }]
        result = replay.attach_display_metadata(prediction, query_fn=fake)
        self.assertTrue(result["attached"])
        self.assertFalse(result["model_input"])
        self.assertEqual(prediction[0]["runners"][0]["horse_number"], "7")


if __name__ == "__main__":
    unittest.main()
