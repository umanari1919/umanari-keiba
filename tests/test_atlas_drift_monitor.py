"""Offline synthetic tests for ATLAS-DRIFT-001; no user DB or licensed rows."""
import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import atlas_drift_monitor as monitor

JST = timezone(timedelta(hours=9))


def synthetic_series(n=80, shifted_at=None):
    out = []
    begin = datetime(2025, 1, 1, 12, tzinfo=JST)
    for index in range(n):
        start = begin + timedelta(days=index)
        prediction = start - timedelta(hours=3)
        final = start + timedelta(hours=2)
        swapped = shifted_at is not None and index >= shifted_at
        # Two runners, synthetic complete roster, official outcome observed.
        for runner_index in range(2):
            won = int(runner_index == 0)
            p = .05 if swapped == bool(won) else .95
            out.append({
                "race_id": f"R{index:04d}",
                "runner_id": f"R{index:04d}-H{runner_index}",
                "expected_runners": 2,
                "prediction_at": prediction.isoformat(),
                "race_start_at": start.isoformat(),
                "result_verified_at": final.isoformat(),
                "result_finality": "OFFICIAL",
                "p_win": p,
                "p_top2": 1.0,
                "p_top3": 1.0,
                "label_win": won,
                "label_top2": 1,
                "label_top3": 1,
            })
    return out


class FakeDetector:
    def __init__(self, delta):
        self.values = []
        self.drift_detected = False

    def update(self, loss):
        self.values.append(loss)
        self.drift_detected = len(self.values) == 3


class DriftTests(unittest.TestCase):
    def test_aggregation_is_race_level_without_runner_ids(self):
        report = monitor.scan(synthetic_series(8), min_races=5, detector_factory=FakeDetector)
        self.assertEqual(report["status"], "DRIFT_SIGNAL")
        self.assertEqual(report["races"], 8)
        self.assertTrue(report["changes"])
        self.assertEqual({x["race_index"] for x in report["changes"]}, {3})
        self.assertEqual({x["target"] for x in report["changes"]}, {"win", "top2", "top3"})
        self.assertNotIn("runner_id", repr(report))
        self.assertFalse(report["certified"])
        self.assertFalse(report["model_promoted"])
        self.assertFalse(report["training_triggered"])

    def test_minimum_evidence_blocks_claim(self):
        report = monitor.scan(synthetic_series(4), min_races=5, detector_factory=FakeDetector)
        self.assertEqual(report["status"], "INSUFFICIENT_RACES")
        self.assertFalse(report["production_approved"])

    def test_invalid_or_missing_result_cannot_be_scored(self):
        fixture = synthetic_series(2)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            fixture[0]["label_top3"] = None
            monitor.scan(fixture, min_races=2, detector_factory=FakeDetector)
        fixture = synthetic_series(2)
        fixture[0]["result_finality"] = "PRELIMINARY"
        with self.assertRaisesRegex(ValueError, "official"):
            monitor.scan(fixture, min_races=2, detector_factory=FakeDetector)
        fixture = synthetic_series(2)
        fixture[0]["p_top2"] = 0.0
        with self.assertRaisesRegex(ValueError, "monotonicity"):
            monitor.scan(fixture, min_races=2, detector_factory=FakeDetector)

    def test_time_leakage_and_naive_timestamps_block(self):
        fixture = synthetic_series(2)
        fixture[0]["prediction_at"] = fixture[0]["result_verified_at"]
        with self.assertRaisesRegex(ValueError, "temporal"):
            monitor.scan(fixture, min_races=2, detector_factory=FakeDetector)
        fixture = synthetic_series(2)
        fixture[0]["prediction_at"] = "2025-01-01T09:00:00"
        with self.assertRaisesRegex(ValueError, "timezone"):
            monitor.scan(fixture, min_races=2, detector_factory=FakeDetector)

    def test_duplicate_or_partial_roster_blocks(self):
        fixture = synthetic_series(2)
        fixture.append(dict(fixture[0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            monitor.scan(fixture, min_races=2, detector_factory=FakeDetector)
        fixture = synthetic_series(2)
        del fixture[0]
        with self.assertRaisesRegex(ValueError, "incomplete runner roster"):
            monitor.scan(fixture, min_races=2, detector_factory=FakeDetector)

    def test_missing_river_is_explicit_not_success(self):
        with patch.dict(sys.modules, {"river": None, "river.drift": None}):
            report = monitor.scan(synthetic_series(2), min_races=2)
        self.assertEqual(report["status"], "DEPENDENCY_MISSING")
        self.assertFalse(report["certified"])

    @unittest.skipUnless(importlib.util.find_spec("river"), "River optional extra not installed")
    def test_real_river_adwin_detects_synthetic_shift(self):
        # 128 well-calibrated race predictions followed by 128 inversions.
        report = monitor.scan(synthetic_series(256, shifted_at=128), min_races=32)
        self.assertEqual(report["status"], "DRIFT_SIGNAL")
        self.assertIn("win", {c["target"] for c in report["changes"]})
        self.assertFalse(report["production_approved"])


if __name__ == "__main__":
    unittest.main()
