import unittest
from datetime import datetime
from weekend_engine_check import before_start


class TimingTests(unittest.TestCase):
    def test_same_day_strict_start_boundary(self):
        race = dict(race_id='2026101005010101', start_time='1010')
        captured = datetime.fromisoformat('2026-10-10T08:00:00+09:00')
        self.assertTrue(before_start(race, captured, datetime.fromisoformat('2026-10-10T10:09:59+09:00')))
        self.assertFalse(before_start(race, captured, datetime.fromisoformat('2026-10-10T10:10:00+09:00')))

    def test_unknown_stale_and_future_capture(self):
        race = dict(race_id='2026101005010101', start_time='1010')
        now = datetime.fromisoformat('2026-10-10T08:00:00+09:00')
        self.assertFalse(before_start(dict(race, start_time='0000'), now, now))
        self.assertFalse(before_start(race, datetime.fromisoformat('2026-10-09T07:59:59+09:00'), now))
        self.assertFalse(before_start(race, datetime.fromisoformat('2026-10-10T08:01:00+09:00'), now))

    def test_timezone_is_required(self):
        with self.assertRaises(ValueError):
            before_start({}, datetime(2026,10,10), datetime(2026,10,10))


if __name__ == '__main__':
    unittest.main()
