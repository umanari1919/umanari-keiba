"""Rebuild recent history from immutable base plus a read-only result snapshot."""
import gzip
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import prospective_capture as p
import build_prospective_history as h
import training_three_targets as t
from sample_extract import query

BASE = p.ROOT / 'datasets/prospective-history-refresh-v1'
OUT = p.ROOT / 'artifacts/prospective-history-refresh-v1'


def advance(base_state, payload, through, observed_at):
    first = (datetime.strptime(base_state['snapshot_through'], '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')
    if not first <= through < observed_at.strftime('%Y%m%d'):
        raise ValueError('History refresh must end before observation day')
    conditions = {r['race_id']: r for r in payload['conditions']}
    raw = payload['runners']
    if len(conditions) != len(payload['conditions']) or len({(r['race_id'], r['horse_id']) for r in raw}) != len(raw):
        raise ValueError('Duplicate refresh records')
    if set(conditions) != {r['race_id'] for r in raw}:
        raise ValueError('Race conditions and runners are incomplete')
    for row in payload['conditions'] + raw:
        if len(row['race_id']) != 16 or not row['race_id'].isdigit() or not first <= row['race_id'][:8] <= through:
            raise ValueError('Result outside refresh interval')
        if 'created' in row:
            datetime.strptime(row['created'], '%Y%m%d')
            if row['created'] > observed_at.strftime('%Y%m%d'):
                raise ValueError('Future-dated result source')
    stores = {name: h.restore_history(base_state[name]) for name in ('general', 'local', 'jockey', 'workout')}
    wood = defaultdict(list)
    for row in payload['workouts']:
        wood[row['horse']].append((t.ordinal(row['day']), t.ordinal(row['created']), row['center'], t.number(row['f4']), t.number(row['f1']), row['time']))
    for values in wood.values(): values.sort(key=lambda e: (e[0], e[5], e[1], e[2]))
    days = defaultdict(lambda: defaultdict(list))
    for row in raw: days[row['race_id'][:8]][row['race_id']].append(row)
    learned = scored = tied = inactive = 0
    last_day = base_state['last_result_day']
    for day, races in sorted(days.items()):
        for store in stores.values(): store.set_day(day)
        updates, training_updates = [], []
        for rid, records in sorted(races.items()):
            c = conditions[rid]
            if not (c['distance'] or '').isdigit() or int(c['distance'] or '0') <= 0 or not (c['track'] or '').isdigit() or len(c['track'] or '') != 2 or c['track'] == '00' or not c['race_class']:
                raise ValueError('Unusable refresh conditions: ' + rid)
            if any(not r['horse_id'] or not (r['jockey_id'] or '').isdigit() or int(r['jockey_id']) <= 0 or r['abnormal'] not in tuple('01234567') for r in records):
                raise ValueError('Unusable refresh identity/status: ' + rid)
            active = [r for r in records if r['abnormal'] not in ('1', '2', '3')]
            inactive += len(records) - len(active)
            if not active: continue
            if any(not isinstance(r['finish'], str) or not r['finish'].isdigit() or (int(r['finish']) <= 0 and r['abnormal'] != '4') for r in active):
                raise ValueError('Unresolved prior-day result; history not activated: ' + rid)
            winners = sum(int(r['finish']) == 1 for r in active)
            if not winners: raise ValueError('Prior-day winner unresolved: ' + rid)
            if winners == 1:
                values = [h.strength(r['horse_id'], c, r['jockey_id'], stores['general'], stores['local'], stores['jockey']) for r in active]
                win = t.marginals(values)[0]
                rows = [[r['horse_id'], int(r['finish']), s] for r, s in zip(active, values)]
                bins = t.feature_bins(rid, rows, {'wood': wood}, 14, 'wood', '1f')
                training_updates.extend((key, int(rows[i][1] == 1), win[i]) for i, key in bins.items())
                scored += 1
            else: tied += 1
            updates.extend((r['horse_id'], h.context(r['horse_id'], c), r['jockey_id'], int(r['finish']) == 1) for r in active)
        # Never allow a same-day result to affect another same-day expected probability.
        for horse, key, rider, win in updates:
            stores['general'].add(horse, int(win)); stores['local'].add(key, int(win)); stores['jockey'].add(rider, int(win))
        for key, win, expected in training_updates:
            stores['workout'].add(key, win); stores['workout'].add(('expected',) + key, expected)
        learned += len(updates)
        if updates: last_day = day
    for store in stores.values(): store.set_day(through)
    state = dict(base_state, snapshot_through=through, last_result_day=last_day, built_at=observed_at.isoformat(),
                 **{name: h.dump_history(store) for name, store in stores.items()})
    return state, {'learned_rows': learned, 'unique_winner_races': scored, 'win_tie_history_races': tied,
                   'excluded_nonstarter_rows': inactive, 'empty_source_interval': not bool(raw)}


def run_refresh():
    verification = p.read(h.OUT / 'verification.json')
    base_path = h.OUT / 'history.json.gz'
    base_hash = p.digest(base_path.read_bytes())
    if base_hash != verification['state_sha256']: raise ValueError('Base history hash mismatch')
    with gzip.open(base_path, 'rt', encoding='utf-8') as handle: base_state = json.load(handle)
    for name, expected in base_state['source_hashes'].items():
        if p.digest((p.ROOT / name).read_bytes()) != expected: raise ValueError('Base history source changed')
    if p.digest((p.ROOT / 'src/build_prospective_history.py').read_bytes()) != base_state['builder_sha256']:
        raise ValueError('Base builder changed')
    observed = datetime.now(p.JST)
    first = (datetime.strptime(base_state['snapshot_through'], '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')
    through = (observed - timedelta(days=1)).strftime('%Y%m%d')
    if first > through: raise ValueError('No new prior day to refresh')
    where = f"kaisai_nen BETWEEN '{first[:4]}' AND '{through[:4]}' AND kaisai_nen||kaisai_gappi BETWEEN '{first}' AND '{through}' AND keibajo_code IN ('01','02','03','04','05','06','07','08','09','10')"
    sql = f"""SELECT json_build_object(
      'read_only',json_build_object('transaction_read_only',current_setting('transaction_read_only'),'default_transaction_read_only',current_setting('default_transaction_read_only')),
      'runners',(SELECT coalesce(json_agg(t),'[]'::json) FROM (
        SELECT trim(race_code) AS race_id,trim(ketto_toroku_bango) AS horse_id,
        trim(kakutei_chakujun) AS finish,trim(ijo_kubun_code) AS abnormal,
        trim(kishu_code) AS jockey_id,trim(data_sakusei_nengappi) AS created
        FROM public.umagoto_race_joho WHERE {where} ORDER BY race_code,ketto_toroku_bango) t),
      'conditions',(SELECT coalesce(json_agg(t),'[]'::json) FROM (
        SELECT trim(race_code) AS race_id,trim(kyori) AS distance,trim(track_code) AS track,
        trim(grade_code) AS grade,trim(kyoso_joken_code_saijakunen) AS race_class,
        trim(data_sakusei_nengappi) AS created FROM public.race_shosai
        WHERE {where} ORDER BY race_code) t),
      'workouts',(SELECT coalesce(json_agg(t),'[]'::json) FROM (
        SELECT trim(ketto_toroku_bango) AS horse,trim(chokyo_nengappi) AS day,
        trim(data_sakusei_nengappi) AS created,trim(tracen_kubun) AS center,
        trim(chokyo_jikoku) AS time,trim(time_gokei_4furlong) AS f4,trim(laptime_1furlong) AS f1
        FROM public.woodchip_chokyo WHERE ketto_toroku_bango IN
        (SELECT ketto_toroku_bango FROM public.umagoto_race_joho WHERE {where})
        AND chokyo_nengappi BETWEEN '{(datetime.strptime(first,'%Y%m%d')-timedelta(days=14)).strftime('%Y%m%d')}' AND '{through}'
        AND data_sakusei_nengappi BETWEEN '19000101' AND '{observed.strftime('%Y%m%d')}'
        ORDER BY ketto_toroku_bango,chokyo_nengappi,chokyo_jikoku,tracen_kubun) t))"""
    payload = query(sql)
    if payload['read_only'] != {'transaction_read_only': 'on', 'default_transaction_read_only': 'on'}:
        raise ValueError('Read-only connection required')
    finished = datetime.now(p.JST)
    if finished.date() != observed.date(): raise ValueError('Refresh crossed midnight; retry')
    snapshot = {'capture_started_at': observed.isoformat(), 'capture_finished_at': finished.isoformat(),
                'first': first, 'through': through, 'sql': sql, 'payload': payload}
    BASE.mkdir(parents=True, exist_ok=True)
    snapshot_path = BASE / (p.digest(p.encoded(snapshot)) + '.json')
    with snapshot_path.open('xb') as handle: handle.write(p.encoded(snapshot))
    # Build from the original base each time so revised results cannot be counted twice.
    state, audit = advance(base_state, payload, through, finished)
    state['source_hashes'] = dict(state['source_hashes'], **{snapshot_path.relative_to(p.ROOT).as_posix(): p.digest(snapshot_path.read_bytes())})
    state['refresh_implementation_sha256'] = p.digest(Path(__file__).read_bytes())
    OUT.mkdir(parents=True, exist_ok=True)
    assets = OUT / 'assets'
    assets.mkdir(exist_ok=True)
    code_path = assets / (state['refresh_implementation_sha256'] + '.py')
    if not code_path.exists():
        with code_path.open('xb') as handle: handle.write(Path(__file__).read_bytes())
    data = gzip.compress(p.encoded(state), mtime=0)
    state_path = assets / (p.digest(data) + '.json.gz')
    if not state_path.exists():
        with state_path.open('xb') as handle: handle.write(data)
    restored = json.loads(gzip.decompress(state_path.read_bytes()))
    for name in ('general', 'local', 'jockey', 'workout'):
        if h.dump_history(h.restore_history(restored[name])) != state[name]: raise ValueError('Refreshed history round-trip failed')
    if p.digest(base_path.read_bytes()) != base_hash: raise ValueError('Original base history changed')
    receipt = {'base_history_sha256': base_hash, 'state_sha256': p.digest(data),
               'state_path': state_path.relative_to(p.ROOT).as_posix(), 'snapshot_through': through,
               'source_snapshot': snapshot_path.relative_to(p.ROOT).as_posix(), 'read_only': payload['read_only'],
               'history_roundtrip_verified': True, 'base_history_unchanged': True,
               'source_runners': len(payload['runners']), 'source_races': len(payload['conditions']),
               'source_workouts': len(payload['workouts']), **audit,
               'official_empty_day_proven': False, 'production_decision': 'REJECT'}
    # Atomic active pointer: only a fully built and checked state becomes available.
    temporary = OUT / 'latest.json.tmp'
    temporary.write_bytes(p.encoded(receipt))
    temporary.replace(OUT / 'latest.json')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / 'refresh.lock'
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.close(descriptor)
        run_refresh()
    except Exception as error:
        (OUT / 'blocked.json').write_bytes(p.encoded({'blocked': True, 'failed_at': datetime.now(p.JST).isoformat(),
            'error_type': type(error).__name__, 'reason': str(error)}))
        raise
    else:
        barrier = OUT / 'blocked.json'
        if barrier.exists(): barrier.unlink()
    finally:
        lock.unlink()


if __name__ == '__main__': main()
