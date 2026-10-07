import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import weekend_personal_forecast as w


def payload():
    rid = '2026101005010101'
    race = dict(race_id=rid, venue='05', distance='1600', track='11', grade='',
                race_class='005', start_time='1000', registered='02', created='20261009')
    rows = [dict(race_id=rid, horse_id=f'202000000{i}', horse_number=str(i),
                 jockey_id='01234', trainer_id='01234', created='20261009') for i in (1, 2)]
    return dict(races=[race], runners=rows, workouts=[])


class PersonalForecastTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 10, 9, tzinfo=w.p.JST)

    def test_same_day_allowed_before_start(self):
        self.assertTrue(w.assess(payload(), self.now, self.now)['races'][0]['input_checks_passed'])

    def test_at_or_after_start_rejected(self):
        for hour in (10, 11):
            now = self.now.replace(hour=hour)
            self.assertFalse(w.assess(payload(), now, now)['races'][0]['input_checks_passed'])

    def test_unknown_start_stale_future_capture_rejected(self):
        card = payload()
        card['races'][0]['start_time'] = '0000'
        self.assertFalse(w.assess(card, self.now, self.now)['races'][0]['input_checks_passed'])
        for captured in (self.now - timedelta(hours=25), self.now + timedelta(seconds=1)):
            self.assertFalse(w.assess(payload(), captured, self.now)['races'][0]['input_checks_passed'])

    def test_mismatched_and_duplicate_roster_rejected(self):
        card = payload()
        card['races'][0]['registered'] = '03'
        self.assertFalse(w.assess(card, self.now, self.now)['races'][0]['input_checks_passed'])
        card = payload()
        card['runners'][1]['horse_number'] = '1'
        self.assertFalse(w.assess(card, self.now, self.now)['races'][0]['input_checks_passed'])

    def test_missing_cards_normal_wait_without_scoring(self):
        with patch.object(w.f, 'score_race', side_effect=AssertionError('must not score')):
            result = w.predict(dict(races=[], runners=[], workouts=[]), self.now, self.now,
                               dict(snapshot_through='20261009'))
        self.assertEqual(result['state'], 'awaiting_confirmed_race_cards')
        self.assertEqual(result['predicted_runners'], 0)

    def test_history_same_day_rejected(self):
        with patch.object(w.f, 'score_race', side_effect=AssertionError('must not score')):
            result = w.predict(payload(), self.now, self.now, dict(snapshot_through='20261010'))
        self.assertEqual(result['predicted_races'], 0)
        self.assertIn('history_not_before_race_day', result['input_checks']['races'][0]['blockers'])

    def test_only_baseline_saved(self):
        rows = [dict(horse_id=f'202000000{i}', horse_number=str(i), jockey_25=[.5, 1., 1.],
                     calibrated=[.7, 1., 1.], wood_14_1f_25=[.6, 1., 1.]) for i in (1, 2)]
        with patch.object(w.f, 'restore_required_histories', return_value={}), patch.object(w.f, 'score_race', return_value=rows):
            result = w.predict(payload(), self.now, self.now, dict(snapshot_through='20261009'))
        self.assertEqual(result['state'], 'personal_predictions_saved')
        self.assertEqual(set(result['predictions'][0]['runners'][0]), {'horse_id', 'horse_number', 'jockey_25'})

    def test_db_not_readonly_fails(self):
        with self.assertRaises(ValueError):
            w.acquire(self.now, lambda sql: {'transaction_read_only': 'off', 'default_transaction_read_only': 'on'})

    def test_acquisition_excludes_result_fields(self):
        queries = []
        card = payload()
        def fake(sql):
            queries.append(sql)
            if 'current_setting' in sql:
                return w.READONLY
            return card['races'] if 'race_shosai' in sql else card['runners']
        self.assertEqual(w.acquire(self.now, fake), card)
        self.assertFalse(any('kakutei_chakujun' in sql for sql in queries))
        self.assertTrue(any("keibajo_code IN ('05','08')" in sql for sql in queries))

    def test_cancellation_and_metadata_mismatch_blocked(self):
        card = payload()
        metadata = dict(runner_status=[dict(race_id=r['race_id'], horse_id=r['horse_id'], abnormal_code='0') for r in card['runners']])
        self.assertTrue(w.assess(card, self.now, self.now, metadata)['races'][0]['input_checks_passed'])
        metadata['runner_status'][0]['abnormal_code'] = '1'
        result = w.assess(card, self.now, self.now, metadata)
        self.assertFalse(result['races'][0]['input_checks_passed'])
        self.assertEqual(result['blocker_counts']['cancellation_or_abnormal_runner_status'], 1)
        metadata['runner_status'].pop()
        self.assertIn('runner_status_roster_mismatch', w.assess(card, self.now, self.now, metadata)['races'][0]['blockers'])

    def test_source_changes_rejected_after_scoring(self):
        card = payload()
        metadata = dict(runner_status=[dict(race_id=r['race_id'], horse_id=r['horse_id'], horse_name='馬', abnormal_code='0') for r in card['runners']])
        def fake(sql):
            if 'current_setting' in sql:
                return w.READONLY
            if 'abnormal_code' in sql:
                return metadata['runner_status']
            return card['races'] if 'race_shosai' in sql else card['runners']
        self.assertEqual(w.verify_source_unchanged(card, metadata, self.now, fake), dict(payload=card,metadata=metadata))
        original = dict(races=card['races'], runners=[dict(r) for r in card['runners']], workouts=[])
        card['runners'][0]['jockey_id'] = '09999'
        with self.assertRaisesRegex(ValueError, 'changed during prediction'):
            w.verify_source_unchanged(original, metadata, self.now, fake)
        original_metadata = dict(runner_status=[dict(r) for r in metadata['runner_status']])
        metadata['runner_status'][0]['abnormal_code'] = '1'
        with self.assertRaisesRegex(ValueError, 'changed during prediction'):
            w.verify_source_unchanged(card, original_metadata, self.now, fake)

    def test_forecast_invalid_mass_fails(self):
        rows = [dict(horse_id=f'202000000{i}', horse_number=str(i), jockey_25=[.6, 1., 1.]) for i in (1, 2)]
        with patch.object(w.f, 'restore_required_histories', return_value={}), patch.object(w.f, 'score_race', return_value=rows):
            with self.assertRaises(ValueError):
                w.predict(payload(), self.now, self.now, dict(snapshot_through='20261009'))


if __name__ == '__main__':
    unittest.main()
