"""Research-only future prediction from sealed inputs and verified history."""
import gzip
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import prospective_capture as p
import prospective_readiness as readiness
import build_prospective_history as history
import training_three_targets as t
from temperature_calibration import recalibrate
import forecast_history_cache as history_cache
import fast_history_restore

OUT = p.ROOT / 'artifacts/prospective-forecast-v1'


def history_is_fresh(through, as_of):
    datetime.strptime(through, '%Y%m%d')
    return (as_of - timedelta(days=1)).strftime('%Y%m%d') <= through <= as_of.strftime('%Y%m%d')


def prepare_workouts(workouts):
    wood = defaultdict(list)
    for row in workouts:
        wood[row['horse_id']].append((t.ordinal(row['day']), t.ordinal(row['created']), row['center'], t.number(row['f4']), t.number(row['f1']), row['time']))
    for events in wood.values():
        events.sort(key=lambda e: (e[0], e[5], e[1], e[2]))
    return wood


def restore_required_histories(state, race_batches):
    """Only for states loaded from a cache with full validation and hash checks."""
    keys = {'general': set(), 'local': set(), 'jockey': set()}
    for race, runners in race_batches:
        for runner in runners:
            horse = runner['horse_id']
            keys['general'].add(horse)
            keys['local'].add(history.context(horse, race))
            keys['jockey'].add(runner['jockey_id'])
    stores = {}
    for name in ('general', 'local', 'jockey', 'workout'):
        value = state[name]
        records = value['records'] if name == 'workout' else [record for record in value['records']
            if (tuple(record[0]) if record[1] else record[0]) in keys[name]]
        stores[name] = fast_history_restore.restore_history(dict(value, records=records))
    return stores


def score_race(state, race, runners, workouts, alpha=2.3, stores=None, wood_store=None):
    if race['race_id'][:8] <= state['snapshot_through']:
        raise ValueError('Prediction date must follow the history cutoff')
    if stores is None:
        stores = {name: fast_history_restore.restore_history(state[name]) for name in ('general', 'local', 'jockey', 'workout')}
    for store in stores.values():
        store.set_day(race['race_id'][:8])
    rows = [[r['horse_id'], 0, history.strength(r['horse_id'], race, r['jockey_id'], stores['general'], stores['local'], stores['jockey'])] for r in runners]
    base = t.marginals([r[2] for r in rows])
    wood = wood_store
    if wood is None:
        wood = prepare_workouts(workouts)
    bins = t.feature_bins(race['race_id'], rows, {'wood': wood}, 14, 'wood', '1f')
    multipliers = [1.] * len(rows)
    for i, key in bins.items():
        n, correct = stores['workout'][key]
        expected = stores['workout'][('expected',) + key][1]
        multipliers[i] = 1 + .25 * n / (n + 100) * (max(.25, min(4., (correct + 10) / (expected + 10))) - 1)
    adjusted = t.marginals([row[2] * m for row, m in zip(rows, multipliers)])
    calibrated = recalibrate(adjusted[0], alpha)
    result = []
    for i, row in enumerate(runners):
        result.append({'horse_id': row['horse_id'], 'horse_number': row['horse_number'],
                       'jockey_25': [base[k][i] for k in range(3)],
                       'wood_14_1f_25': [adjusted[k][i] for k in range(3)],
                       'calibrated': [calibrated[k][i] for k in range(3)],
                       'workout_multiplier': multipliers[i], 'eligible_workout': i in bins})
    return result


def main():
    entries = p.verify()
    if not entries:
        raise ValueError('Prospective captures required')
    capture = entries[-1]
    locked = p.read(p.ROOT / 'artifacts/oos-2026-training-v1/manifest.json')
    for name, expected in locked['files'].items():
        if name.startswith('datasets/') and p.digest((p.ROOT / name).read_bytes()) != expected:
            raise ValueError('Locked 2026 data changed')
    seal = p.read(p.BASE / 'model-seal.json')
    for name, expected in seal['files'].items():
        if p.digest((p.ROOT / name).read_bytes()) != expected:
            raise ValueError('Locked model or code changed')
    verification = p.read(history.OUT / 'verification.json')
    path = history.OUT / 'history.json.gz'
    refresh_pointer = p.ROOT / 'artifacts/prospective-history-refresh-v1/latest.json'
    if refresh_pointer.with_name('blocked.json').exists():
        raise ValueError('Latest history refresh failed; resolve it before forecasting')
    refresh_receipt = None
    if refresh_pointer.exists():
        refresh_receipt = p.read(refresh_pointer)
        if refresh_receipt['base_history_sha256'] != verification['state_sha256'] or not refresh_receipt['history_roundtrip_verified']:
            raise ValueError('History refresh must be rebuilt from current verified base')
        path = (p.ROOT / refresh_receipt['state_path']).resolve()
        if not path.is_relative_to((p.ROOT / 'artifacts/prospective-history-refresh-v1/assets').resolve()):
            raise ValueError('Refreshed history path is outside its asset folder')
        verification = dict(verification, state_sha256=refresh_receipt['state_sha256'])
    if p.digest(path.read_bytes()) != verification['state_sha256']:
        raise ValueError('History state hash mismatch')
    now = datetime.now(p.JST)
    checks = readiness.assess(capture['entry'], now)
    include_histories = any(checked['input_checks_passed'] for checked in checks['races'])
    state = history_cache.load(path, verification['state_sha256'], include_histories)
    if refresh_receipt is not None:
        code_hash = state['refresh_implementation_sha256']
        code_asset = p.ROOT / 'artifacts/prospective-history-refresh-v1/assets' / (code_hash + '.py')
        if p.digest(code_asset.read_bytes()) != code_hash or p.digest((p.ROOT / 'src/refresh_prospective_history.py').read_bytes()) != code_hash:
            raise ValueError('Refreshed history implementation changed')
    for name, expected in state['source_hashes'].items():
        if p.digest((p.ROOT / name).read_bytes()) != expected:
            raise ValueError('History source changed: ' + name)
    if state['builder_sha256'] != p.digest((p.ROOT / 'src/build_prospective_history.py').read_bytes()):
        raise ValueError('History builder changed')
    if datetime.fromisoformat(state['built_at']) > now:
        raise ValueError('History build timestamp is in the future')
    fresh = history_is_fresh(state['snapshot_through'], now)
    payload = capture['entry']['payload']
    races = {r['race_id']: r for r in payload['races']}
    runners = defaultdict(list)
    for row in payload['runners']:
        runners[row['race_id']].append(row)
    predictions = []
    if fresh and any(checked['input_checks_passed'] for checked in checks['races']):
        batches = [(races[checked['race_id']], runners[checked['race_id']]) for checked in checks['races'] if checked['input_checks_passed']]
        stores = restore_required_histories(state, batches)
        # Predictions need metadata and restored stores, not duplicate serialized histories.
        for name in history_cache.HISTORIES: del state[name]
        wood = prepare_workouts(payload['workouts'])
        for checked in checks['races']:
            if checked['input_checks_passed']:
                rid = checked['race_id']
                predictions.append({'race_id': rid, 'runners': score_race(state, races[rid], runners[rid], payload['workouts'], seal['alpha'], stores=stores, wood_store=wood)})
    result = {'created_at': now.isoformat(), 'capture_sha256': capture['sha256'],
              'history_sha256': verification['state_sha256'], 'history_snapshot_through': state['snapshot_through'],
              'model_seal_sha256': p.digest(p.encoded(seal)), 'forecaster_sha256': p.digest(Path(__file__).read_bytes()),
              'history_loader_sha256': history_cache.implementation_hash(),
              'history_restore_sha256': p.digest(Path(fast_history_restore.__file__).read_bytes()),
              'state': 'awaiting_history_update' if not fresh else 'awaiting_source_data' if not checks['observed_races'] else 'research_predictions_saved' if predictions else 'input_checks_blocked',
              'input_checks': checks, 'predictions': predictions, 'predicted_races': len(predictions),
              'predicted_runners': sum(len(r['runners']) for r in predictions),
              'production_decision': 'REJECT', 'future_evaluated': False, 'db_connection_used': False,
              'limitations': ['Local input capture and known-history cutoff only; official completeness is unproven.', 'Result collection and roster checks run in a separate process; betting-profit evaluation is unimplemented.', 'History refresh uses current prior-day DB results; original delivery/revision availability is unproven.', 'PC timestamps are not external timestamp certification.']}
    OUT.mkdir(parents=True, exist_ok=True)
    if p.verify()[-1]['sha256'] != capture['sha256'] or p.digest(path.read_bytes()) != verification['state_sha256']:
        raise ValueError('Capture or history changed during forecasting; retry')
    assets = OUT / 'assets'
    assets.mkdir(exist_ok=True)
    for suffix, content in (('.json.gz', path.read_bytes()), ('.py', Path(__file__).read_bytes()), ('.py', Path(history_cache.__file__).read_bytes()), ('.py', Path(fast_history_restore.__file__).read_bytes())):
        asset = assets / (p.digest(content) + suffix)
        if not asset.exists():
            with asset.open('xb') as handle:
                handle.write(content)
        if p.digest(asset.read_bytes()) != p.digest(content):
            raise ValueError('Frozen forecast asset mismatch')
    if predictions:
        folder = OUT / 'frozen'
        folder.mkdir(exist_ok=True)
        target = folder / (p.digest(p.encoded(result)) + '.json')
        with target.open('xb') as handle:
            handle.write(p.encoded(result))
    (OUT / 'status.json').write_bytes(p.encoded(result))
    print(f'Future research predictions: {len(predictions)} races; {result["state"]}')


if __name__ == '__main__':
    main()
