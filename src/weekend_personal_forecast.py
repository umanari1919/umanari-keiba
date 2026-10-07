"""Personal pre-start baseline forecasts; never research capture/evaluation evidence."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import math
import prospective_forecast as f
from weekend_engine_check import before_start
from sample_extract import query

p = f.p
OUT = p.ROOT / 'artifacts/jwk-weekend-personal-v1'
END = '20261012'
READONLY = {'transaction_read_only': 'on', 'default_transaction_read_only': 'on'}


def acquire(now, query_fn=query, metadata=None):
    first = max(now.strftime('%Y%m%d'), '20261010')
    if first > END:
        return {'races': [], 'runners': [], 'workouts': []}
    if query_fn("SELECT json_build_object('transaction_read_only',current_setting('transaction_read_only'),'default_transaction_read_only',current_setting('default_transaction_read_only'))") != READONLY:
        raise ValueError('Read-only DB connection required')
    where = p.date_predicate(first, END) + " AND keibajo_code IN ('05','08')"
    races = query_fn(f"""SELECT coalesce(json_agg(t),'[]'::json) FROM (
      SELECT trim(race_code) race_id,trim(keibajo_code) venue,trim(kyori) distance,
      trim(track_code) track,trim(grade_code) grade,trim(kyoso_joken_code_saijakunen) race_class,
      trim(hasso_jikoku) start_time,trim(toroku_tosu) registered,trim(data_sakusei_nengappi) created
      FROM public.race_shosai WHERE {where} ORDER BY race_code)t""")
    runners = query_fn(f"""SELECT coalesce(json_agg(t),'[]'::json) FROM (
      SELECT trim(race_code) race_id,trim(ketto_toroku_bango) horse_id,trim(umaban) horse_number,
      trim(kishu_code) jockey_id,trim(chokyoshi_code) trainer_id,trim(data_sakusei_nengappi) created
      FROM public.umagoto_race_joho WHERE {where} ORDER BY race_code,umaban)t""")
    payload = {'races': races, 'runners': runners, 'workouts': []}
    p.validate_payload(payload, first, END, now.strftime('%Y%m%d'))
    if metadata is not None:
        rows = query_fn(f"""SELECT coalesce(json_agg(t),'[]'::json) FROM (
          SELECT trim(race_code) race_id,trim(ketto_toroku_bango) horse_id,
          trim(bamei) horse_name,trim(ijo_kubun_code) abnormal_code
          FROM public.umagoto_race_joho WHERE {where} ORDER BY race_code,umaban)t""")
        metadata['runner_status'] = rows
    return payload


def assess(payload, captured_at, now, metadata=None):
    # Reuse structural checks only; personal timing has its own strict start clock.
    previous_day = now - timedelta(days=1)
    entry = dict(payload=payload, capture_finished_at=previous_day.isoformat(), sequence=0)
    checks = f.readiness.assess(entry, previous_day)
    races = {r['race_id']: r for r in payload['races']}
    for checked in checks['races']:
        reasons = set(checked['blockers'])
        race = races.get(checked['race_id'])
        if metadata is not None:
            status_rows = [row for row in metadata.get('runner_status', []) if row['race_id'] == checked['race_id']]
            source_keys = {(row['horse_id']) for row in payload['runners'] if row['race_id'] == checked['race_id']}
            if len(status_rows) != checked['runner_count'] or {r['horse_id'] for r in status_rows} != source_keys:
                reasons.add('runner_status_roster_mismatch')
            if any(row['abnormal_code'] != '0' for row in status_rows):
                reasons.add('cancellation_or_abnormal_runner_status')
        if race is None or not before_start(race, captured_at, now):
            reasons.add('not_before_start_or_invalid_capture_clock')
        checked['blockers'] = sorted(reasons)
        checked['input_checks_passed'] = not reasons
    checks.update(assessed_at=now.isoformat(), capture_finished_at=captured_at.isoformat(),
                  input_checks_passed_races=sum(r['input_checks_passed'] for r in checks['races']),
                  blocked_races=sum(not r['input_checks_passed'] for r in checks['races']))
    checks['blocker_counts'] = dict(Counter(reason for row in checks['races'] for reason in row['blockers']))
    checks.pop('limitations', None)
    return checks


def load_history(now, include_histories):
    seal = p.read(p.BASE / 'model-seal.json')
    for name, expected in seal['files'].items():
        if f.history_cache.file_hash(p.ROOT / name) != expected:
            raise ValueError('Sealed model asset changed: ' + name)
    pointer = p.ROOT / 'artifacts/prospective-history-refresh-v1/latest.json'
    if pointer.with_name('blocked.json').exists():
        raise ValueError('Latest history refresh failed')
    receipt = p.read(pointer)
    base = p.read(f.history.OUT / 'verification.json')
    if not receipt['history_roundtrip_verified'] or receipt['base_history_sha256'] != base['state_sha256']:
        raise ValueError('History refresh receipt does not verify current base')
    path = (p.ROOT / receipt['state_path']).resolve()
    if not path.is_relative_to((pointer.parent / 'assets').resolve()):
        raise ValueError('History path outside refresh assets')
    state = f.history_cache.load(path, receipt['state_sha256'], include_histories)
    code_hash = state['refresh_implementation_sha256']
    for asset in (pointer.parent / 'assets' / (code_hash + '.py'), p.ROOT / 'src/refresh_prospective_history.py'):
        if f.history_cache.file_hash(asset) != code_hash:
            raise ValueError('History refresh implementation changed')
    for name, expected in state['source_hashes'].items():
        if f.history_cache.file_hash(p.ROOT / name) != expected:
            raise ValueError('History source changed: ' + name)
    if state['builder_sha256'] != f.history_cache.file_hash(p.ROOT / 'src/build_prospective_history.py'):
        raise ValueError('History builder changed')
    if datetime.fromisoformat(state['built_at']) > now:
        raise ValueError('History built in the future')
    return state, receipt, seal, path


def predict(payload, captured_at, now, state, metadata=None):
    checks = assess(payload, captured_at, now, metadata)
    races = {r['race_id']: r for r in payload['races']}
    runners = defaultdict(list)
    for runner in payload['runners']:
        runners[runner['race_id']].append(runner)
    fresh = f.history_is_fresh(state['snapshot_through'], now)
    batches = []
    for checked in checks['races']:
        if checked['race_id'][:8] <= state['snapshot_through']:
            checked['blockers'].append('history_not_before_race_day')
            checked['input_checks_passed'] = False
        if checked['input_checks_passed'] and fresh:
            batches.append((races[checked['race_id']], runners[checked['race_id']]))
    predictions = []
    names = {(r['race_id'], r['horse_id']): r.get('horse_name', '') for r in (metadata or {}).get('runner_status', [])}
    if batches:
        stores = f.restore_required_histories(state, batches)
        for race, rows in batches:
            # Empty workout input means only the sealed jockey-25 baseline is retained.
            scored = f.score_race(state, race, rows, [], stores=stores)
            saved = []
            for runner in scored:
                values = runner['jockey_25']
                if not all(math.isfinite(v) and 0 <= v <= 1 for v in values) or values != sorted(values):
                    raise ValueError('Invalid baseline probabilities')
                saved.append({key: runner[key] for key in ('horse_id', 'horse_number', 'jockey_25')})
                if names.get((race['race_id'], runner['horse_id'])):
                    saved[-1]['horse_name'] = names[(race['race_id'], runner['horse_id'])]
            for k in range(3):
                if abs(sum(r['jockey_25'][k] for r in saved) - min(k+1, len(saved))) > 1e-9:
                    raise ValueError('Invalid baseline target mass')
            predictions.append(dict(race_id=race['race_id'], venue=race['venue'], start_time=race['start_time'],
                                    distance=race['distance'], runners=saved))
    checks['input_checks_passed_races'] = sum(r['input_checks_passed'] for r in checks['races'])
    checks['blocked_races'] = len(checks['races']) - checks['input_checks_passed_races']
    checks['blocker_counts'] = dict(Counter(reason for row in checks['races'] for reason in row['blockers']))
    status = ('awaiting_confirmed_race_cards' if not checks['observed_races'] else
              'awaiting_history_update' if not fresh else
              'personal_predictions_saved' if predictions else 'input_checks_blocked')
    return dict(state=status, predictions=predictions, input_checks=checks,
                predicted_races=len(predictions), predicted_runners=sum(len(r['runners']) for r in predictions))


def verify_source_unchanged(payload, metadata, now, query_fn=query):
    latest_metadata = {}
    latest = acquire(now, query_fn=query_fn, metadata=latest_metadata)
    original = dict(payload=payload, metadata=metadata)
    if p.digest(p.encoded(original)) != p.digest(p.encoded(dict(payload=latest, metadata=latest_metadata))):
        raise ValueError('Race roster or status changed during prediction; retry')
    return original


def main():
    started = datetime.now(p.JST)
    metadata = {}
    payload = acquire(started, metadata=metadata)
    captured = datetime.now(p.JST)
    if started.date() != captured.date():
        raise ValueError('Acquisition crossed midnight; retry')
    eligible = assess(payload, captured, captured, metadata)['input_checks_passed_races'] > 0
    state, receipt, seal, path = load_history(captured, eligible)
    result = predict(payload, captured, captured, state, metadata)
    source = dict(payload=payload, metadata=metadata)
    if result['predictions']:
        source = verify_source_unchanged(payload, metadata, datetime.now(p.JST))
    finished = datetime.now(p.JST)
    # Re-check the clock after scoring; refuse races that started during computation.
    race_map = {r['race_id']: r for r in payload['races']}
    if any(not before_start(race_map[r['race_id']], captured, finished) for r in result['predictions']):
        raise ValueError('Race started during prediction; retry')
    if f.history_cache.file_hash(path) != receipt['state_sha256']:
        raise ValueError('History changed while predicting; retry')
    result.update(created_at=finished.isoformat(), captured_at=captured.isoformat(),
        use='personal_betting_decision_support', research_evidence=False, model='jockey_25',
        automatic_betting=False, production_promotion=False, database_modified=False,
        read_only_connection=READONLY, source_sha256=p.digest(p.encoded(source)), payload_sha256=p.digest(p.encoded(payload)), runner_status_sha256=p.digest(p.encoded(metadata)),
        history_sha256=receipt['state_sha256'], history_snapshot_through=state['snapshot_through'],
        model_seal_sha256=p.digest(p.encoded(seal)),
        limitations=['Local roster consistency does not prove official completeness or late cancellation coverage.',
                     'Prior-day refreshed result delivery and revision availability is unproven.',
                     'Probabilities support personal judgment; no profitability validation.'])
    OUT.mkdir(parents=True, exist_ok=True)
    if result['predictions']:
        asset = OUT / 'assets' / ('source-' + result['source_sha256'] + '.json')
        asset.parent.mkdir(exist_ok=True)
        if not asset.exists():
            with asset.open('xb') as handle:
                handle.write(p.encoded(source))
        if p.digest(asset.read_bytes()) != result['source_sha256']:
            raise ValueError('Frozen personal input asset mismatch')
        result['source_path'] = asset.relative_to(p.ROOT).as_posix()
    frozen = OUT / 'runs' / (p.digest(p.encoded(result)) + '.json')
    frozen.parent.mkdir(exist_ok=True)
    if not frozen.exists():
        with frozen.open('xb') as handle:
            handle.write(p.encoded(result))
    if result['predictions']:
        # A forecast must receive its local freeze receipt BEFORE latest.json can publish it.
        import forward_blind
        forward_blind.freeze_run(frozen)
    (OUT / 'latest.json').write_bytes(p.encoded(result))
    print(result['state'], result['predicted_races'], result['predicted_runners'])


if __name__ == '__main__':
    main()
