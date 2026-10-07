"""Append-only observation of future race inputs; no predictions or result fields."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sample_extract import query

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'datasets/prospective-capture-v1'
JST = timezone(timedelta(hours=9))
FIELDS = {
    'races': ('race_id', 'venue', 'distance', 'track', 'grade', 'race_class', 'start_time', 'registered', 'created'),
    'runners': ('race_id', 'horse_id', 'horse_number', 'jockey_id', 'trainer_id', 'created'),
    'workouts': ('horse_id', 'day', 'created', 'center', 'time', 'f4', 'f1'),
}
ASSETS = ('artifacts/temperature-calibration-v1/model.json',
          'artifacts/temperature-calibration-v1/future-validation-protocol.json',
          'artifacts/oos-2026-training-v1/protocol.json',
          'src/training_three_targets.py', 'src/temperature_calibration.py',
          'src/personnel_experiments.py', 'src/parallel_experiments.py',
          'src/decade_evaluate.py', 'src/condition_audit.py')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def validate_payload(payload, start, end, captured_day):
    for name, rows in payload.items():
        if name not in FIELDS or any(set(row) != set(FIELDS[name]) for row in rows):
            raise ValueError('Unexpected input fields: ' + name)
        for row in rows:
            datetime.strptime(row['created'], '%Y%m%d')
            if row['created'] > captured_day:
                raise ValueError('Source creation date is later than capture day')
            if name == 'workouts':
                datetime.strptime(row['day'], '%Y%m%d')
                if row['day'] > captured_day or not row['horse_id']:
                    raise ValueError('Invalid workout date or identity')
            else:
                if len(row['race_id']) != 16 or not row['race_id'].isdigit() or not start <= row['race_id'][:8] <= end:
                    raise ValueError('Race outside future capture window or invalid identity')
    if set(payload) != set(FIELDS):
        raise ValueError('Incomplete payload sections')
    race_ids = [r['race_id'] for r in payload['races']]
    runner_keys = [(r['race_id'], r['horse_id']) for r in payload['runners']]
    if len(set(race_ids)) != len(race_ids) or len(set(runner_keys)) != len(runner_keys):
        raise ValueError('Duplicate race or runner identities')
    if any(not r['horse_id'] for r in payload['runners']):
        raise ValueError('Missing horse identity')


def verify(base=BASE):
    previous = None
    previous_finish = None
    entries = []
    for number, path in enumerate(sorted((base / 'captures').glob('*.json')), 1):
        if path.name != f'{number:09d}.json':
            raise ValueError('Capture sequence has a gap')
        envelope = read(path)
        if set(envelope) != {'entry', 'sha256'} or digest(encoded(envelope['entry'])) != envelope['sha256']:
            raise ValueError('Capture content hash mismatch')
        entry = envelope['entry']
        implementation = entry.get('capture_implementation_sha256')
        if implementation and digest((base / 'assets' / implementation).read_bytes()) != implementation:
            raise ValueError('Capture implementation asset mismatch')
        if entry['sequence'] != number or entry['previous_sha256'] != previous:
            raise ValueError('Capture chain mismatch')
        begin = datetime.fromisoformat(entry['capture_started_at'])
        finish = datetime.fromisoformat(entry['capture_finished_at'])
        if begin.utcoffset() != timedelta(hours=9) or finish.utcoffset() != timedelta(hours=9):
            raise ValueError('Capture timestamps must use JST')
        if begin > finish or begin.date() != finish.date():
            raise ValueError('Invalid capture interval')
        if previous_finish is not None and begin < previous_finish:
            raise ValueError('Capture clock moved backwards')
        day = finish.strftime('%Y%m%d')
        if entry['race_start'] <= day:
            raise ValueError('Same-day or past races cannot establish pre-race evidence')
        seal = read(base / 'model-seal.json')
        if not seal['future_start'] <= entry['race_start'] <= entry['race_end'] <= seal['future_end']:
            raise ValueError('Capture window outside frozen future period')
        if entry['read_only_connection'] != {'transaction_read_only': 'on', 'default_transaction_read_only': 'on'}:
            raise ValueError('Missing read-only connection evidence')
        validate_payload(entry['payload'], entry['race_start'], entry['race_end'], day)
        if entry['model_seal_sha256'] != digest(encoded(read(base / 'model-seal.json'))):
            raise ValueError('Model seal differs from capture')
        for name, expected in read(base / 'model-seal.json')['files'].items():
            if digest((base / 'assets' / expected).read_bytes()) != expected:
                raise ValueError('Sealed asset content mismatch: ' + name)
        previous = envelope['sha256']
        previous_finish = finish
        entries.append(envelope)
    return entries


def seal_models(base):
    files = {name: digest((ROOT / name).read_bytes()) for name in ASSETS}
    model = read(ROOT / ASSETS[0])
    protocol = read(ROOT / ASSETS[1])
    if model['alpha'] != 2.3 or protocol['state'] != 'awaiting_future_data' or not protocol['parameters_fixed']:
        raise ValueError('Unexpected locked future model')
    seal = {'files': files, 'alpha': model['alpha'], 'future_start': protocol['evaluation_start'], 'future_end': protocol['evaluation_end'], 'production_approved': False}
    path = base / 'model-seal.json'
    if path.exists():
        if read(path) != seal:
            raise ValueError('Locked model changed; a new capture version is required')
    else:
        (base / 'assets').mkdir(parents=True, exist_ok=True)
        for name, expected in files.items():
            asset = base / 'assets' / expected
            if not asset.exists():
                with asset.open('xb') as handle:
                    handle.write((ROOT / name).read_bytes())
            if digest(asset.read_bytes()) != expected:
                raise ValueError('Asset changed while sealing')
        with path.open('xb') as handle:
            handle.write(encoded(seal))
    return seal


def date_predicate(first, last):
    begin = datetime.strptime(first, '%Y%m%d')
    end = datetime.strptime(last, '%Y%m%d')
    if begin > end: raise ValueError('Reversed date range')
    pieces = []
    for year in range(begin.year, end.year + 1):
        low = first[4:] if year == begin.year else '0101'
        high = last[4:] if year == end.year else '1231'
        pieces.append(f"(kaisai_nen='{year}' AND kaisai_gappi BETWEEN '{low}' AND '{high}')")
    return '(' + ' OR '.join(pieces) + ')'


def capture(base=BASE):
    base.mkdir(parents=True, exist_ok=True)
    lock = base / 'capture.lock'
    # Exclusive creation serializes captures; never remove another process's lock.
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.close(descriptor)
        previous = verify(base)
        seal = seal_models(base)
        started = datetime.now(JST)
        first = max((started + timedelta(days=1)).strftime('%Y%m%d'), seal['future_start'])
        last = min((started + timedelta(days=14)).strftime('%Y%m%d'), seal['future_end'])
        if first > last:
            raise ValueError('No remaining future validation window')
        today = started.strftime('%Y%m%d')
        venues = "('01','02','03','04','05','06','07','08','09','10')"
        where = f"{date_predicate(first, last)} AND keibajo_code IN {venues}"
        sql = {
            'races': f"""SELECT coalesce(json_agg(t),'[]'::json) FROM (
              SELECT trim(race_code) AS race_id,trim(keibajo_code) AS venue,
              trim(kyori) AS distance,trim(track_code) AS track,trim(grade_code) AS grade,
              trim(kyoso_joken_code_saijakunen) AS race_class,trim(hasso_jikoku) AS start_time,
              trim(toroku_tosu) AS registered,trim(data_sakusei_nengappi) AS created
              FROM public.race_shosai WHERE {where} ORDER BY race_code) t""",
            'runners': f"""SELECT coalesce(json_agg(t),'[]'::json) FROM (
              SELECT trim(race_code) AS race_id,trim(ketto_toroku_bango) AS horse_id,
              trim(umaban) AS horse_number,trim(kishu_code) AS jockey_id,
              trim(chokyoshi_code) AS trainer_id,trim(data_sakusei_nengappi) AS created
              FROM public.umagoto_race_joho WHERE {where} ORDER BY race_code,ketto_toroku_bango) t""",
        }
        connection = query("SELECT json_build_object('transaction_read_only',current_setting('transaction_read_only'),'default_transaction_read_only',current_setting('default_transaction_read_only'))")
        if connection != {'transaction_read_only': 'on', 'default_transaction_read_only': 'on'}:
            raise ValueError('Read-only DB connection required')
        payload = {name: query(statement) for name, statement in sql.items()}
        horse_filter = f"SELECT ketto_toroku_bango FROM public.umagoto_race_joho WHERE {where}"
        sql['workouts'] = f"""SELECT coalesce(json_agg(t),'[]'::json) FROM (
          SELECT trim(ketto_toroku_bango) AS horse_id,trim(chokyo_nengappi) AS day,
          trim(data_sakusei_nengappi) AS created,trim(tracen_kubun) AS center,
          trim(chokyo_jikoku) AS time,trim(time_gokei_4furlong) AS f4,
          trim(laptime_1furlong) AS f1 FROM public.woodchip_chokyo
          WHERE ketto_toroku_bango IN ({horse_filter})
          AND chokyo_nengappi BETWEEN '{(started-timedelta(days=14)).strftime('%Y%m%d')}' AND '{today}'
          AND data_sakusei_nengappi BETWEEN '19000101' AND '{today}'
          ORDER BY ketto_toroku_bango,chokyo_nengappi,chokyo_jikoku,tracen_kubun) t"""
        payload['workouts'] = query(sql['workouts'])
        finished = datetime.now(JST)
        if finished.date() != started.date():
            raise ValueError('Capture crossed midnight; retry without saving')
        validate_payload(payload, first, last, today)
        implementation_bytes = Path(__file__).read_bytes()
        implementation = digest(implementation_bytes)
        implementation_path = base / 'assets' / implementation
        if not implementation_path.exists():
            with implementation_path.open('xb') as handle:
                handle.write(implementation_bytes)
        entry = {'version': 1, 'sequence': len(previous) + 1,
                 'capture_implementation_sha256': implementation,
                 'previous_sha256': previous[-1]['sha256'] if previous else None,
                 'capture_started_at': started.isoformat(), 'capture_finished_at': finished.isoformat(),
                 'race_start': first, 'race_end': last, 'model_seal_sha256': digest(encoded(seal)),
                 'read_only_connection': connection, 'sql': sql, 'payload': payload,
                 'purpose': 'future input observation only; predictions not computed',
                 'transaction_scope': 'separate read-only queries within the recorded interval'}
        envelope = {'entry': entry, 'sha256': digest(encoded(entry))}
        folder = base / 'captures'
        folder.mkdir(exist_ok=True)
        with (folder / f'{entry["sequence"]:09d}.json').open('xb') as handle:
            handle.write(encoded(envelope))
        verify(base)
        return envelope
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        rows = verify()
        print(f'Capture chain verified: {len(rows)} entries; no DB connection')
    else:
        snapshot = capture()
        print(json.dumps({'sequence': snapshot['entry']['sequence'], 'sha256': snapshot['sha256'], 'counts': {k: len(v) for k, v in snapshot['entry']['payload'].items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
