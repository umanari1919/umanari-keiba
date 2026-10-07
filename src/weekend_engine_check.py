"""Isolated personal-use timing check and synthetic engine smoke; no live forecasts."""
import argparse
import math
from datetime import datetime, timedelta
import prospective_forecast as f

OUT = f.p.ROOT / 'artifacts/jwk-weekend-engine-check-v1'


def before_start(race, captured_at, as_of, max_age_hours=24):
    """Reject unknown clocks, stale/future captures and races already starting."""
    if any(value.tzinfo is None or value.utcoffset() != timedelta(hours=9)
           for value in (captured_at, as_of)):
        raise ValueError('JST-aware timestamps required')
    if captured_at > as_of or as_of - captured_at > timedelta(hours=max_age_hours):
        return False
    rid, clock = race.get('race_id', ''), race.get('start_time', '')
    if not isinstance(rid, str) or not isinstance(clock, str) or len(clock) != 4 or not clock.isdigit() or clock == '0000':
        return False
    try:
        start = datetime.strptime(rid[:8] + clock, '%Y%m%d%H%M').replace(tzinfo=f.p.JST)
    except ValueError:
        return False
    return captured_at <= as_of < start


def main():
    seal = f.p.read(f.p.BASE / 'model-seal.json')
    for name, expected in seal['files'].items():
        if f.p.digest((f.p.ROOT / name).read_bytes()) != expected:
            raise ValueError('Sealed asset changed: ' + name)
    receipt = f.p.read(f.p.ROOT / 'artifacts/prospective-history-refresh-v1/latest.json')
    path = f.p.ROOT / receipt['state_path']
    state = f.history_cache.load(path, receipt['state_sha256'])
    horses = [row[0] for row in state['general']['records'] if isinstance(row[0], str)][:18]
    jockey = state['jockey']['records'][0][0]
    day = (datetime.strptime(state['snapshot_through'], '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')
    race = dict(race_id=day+'05010101', track='11', distance='1600', grade='', race_class='005')
    runners = [dict(horse_id=horse, horse_number=str(i+1), jockey_id=jockey) for i, horse in enumerate(horses)]
    stores = f.restore_required_histories(state, [(race, runners)])
    predictions = f.score_race(state, race, runners, [], stores=stores)
    for row in predictions:
        values = row['jockey_25']
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in values) or values != sorted(values):
            raise ValueError('Invalid baseline probabilities')
        if row['workout_multiplier'] != 1 or row['eligible_workout']:
            raise ValueError('Missing workouts changed baseline')
    masses = [sum(row['jockey_25'][k] for row in predictions) for k in range(3)]
    if any(abs(value-(k+1)) > 1e-10 for k, value in enumerate(masses)):
        raise ValueError('Invalid target mass')
    if f.history_cache.file_hash(path) != receipt['state_sha256']:
        raise ValueError('History changed during smoke')
    result = dict(checked_at=datetime.now(f.p.JST).isoformat(), sealed_assets_verified=True,
                  synthetic_runners=len(predictions), target_masses=masses,
                  jockey25_probabilities_computed=True, live_predictions_saved=False,
                  database_connected=False, source_history_sha256=receipt['state_sha256'],
                  scope='Synthetic roster using actual saved histories; does not establish weekend roster availability')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'latest.json').write_bytes(f.p.encoded(result))
    (OUT/'report.md').write_text('# Weekend baseline engine smoke\n\nSealed jockey-25 produced three coherent target probabilities for '+str(len(predictions))+' synthetic entrants using actual saved histories. Missing workouts use neutral multiplier. No live forecasts or DB writes.\n', encoding='utf-8')
    print(result)


if __name__ == '__main__':
    main()
