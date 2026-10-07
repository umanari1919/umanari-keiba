"""Offline input checks against the latest sealed prospective observation."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import prospective_capture as p

OUT = p.ROOT / 'artifacts/prospective-readiness-v1'


def digits(value):
    return isinstance(value, str) and bool(value) and value.isdigit()


def assess(entry, as_of):
    captured = datetime.fromisoformat(entry['capture_finished_at'])
    if as_of.tzinfo is None or as_of.utcoffset() != p.JST.utcoffset(as_of):
        raise ValueError('Assessment timestamp must use JST')
    if as_of < captured:
        raise ValueError('Assessment cannot precede acquisition')
    payload = entry['payload']
    conditions = defaultdict(list)
    runners = defaultdict(list)
    for row in payload['races']:
        conditions[row['race_id']].append(row)
    for row in payload['runners']:
        runners[row['race_id']].append(row)
    workouts = defaultdict(list)
    for row in payload['workouts']:
        workouts[row['horse_id']].append(row)
    results = []
    for rid in sorted(set(conditions) | set(runners)):
        reasons = set()
        if (as_of.date() - captured.date()).days > 1:
            reasons.add('stale_capture')
        rows = runners[rid]
        race = conditions[rid][0] if len(conditions[rid]) == 1 else None
        if race is None:
            reasons.add('missing_or_duplicate_race_conditions')
        if not rows:
            reasons.add('missing_runners')
        if rid[:8] <= as_of.strftime('%Y%m%d'):
            reasons.add('same_day_or_past_race')
        if race:
            clock = race['start_time']
            if not digits(clock) or len(clock) != 4 or not (0 <= int(clock[:2]) <= 23 and 0 <= int(clock[2:]) <= 59) or clock == '0000':
                reasons.add('missing_or_invalid_start_time')
            if not digits(race['registered']) or int(race['registered']) < 2:
                reasons.add('missing_or_invalid_registered_count')
            elif len(rows) != int(race['registered']):
                reasons.add('registered_count_mismatch')
            if not digits(race['distance']) or int(race['distance']) <= 0:
                reasons.add('invalid_distance')
            if not digits(race['track']) or len(race['track']) != 2 or race['track'] == '00' or not race['race_class']:
                reasons.add('missing_or_invalid_race_conditions')
            if race['venue'] != rid[8:10] or race['venue'] not in tuple(f'{n:02}' for n in range(1, 11)):
                reasons.add('invalid_venue')
        numbers = [int(r['horse_number']) if digits(r['horse_number']) else None for r in rows]
        if any(n is None or n <= 0 for n in numbers) or len(set(numbers)) != len(numbers):
            reasons.add('missing_or_duplicate_horse_number')
        if len({r['horse_id'] for r in rows}) != len(rows) or any(not digits(r['horse_id']) or len(r['horse_id']) != 10 for r in rows):
            reasons.add('missing_or_duplicate_horse_identity')
        for name in ('jockey_id', 'trainer_id'):
            if any(not digits(r[name]) or int(r[name]) <= 0 for r in rows):
                reasons.add('missing_' + name)
        race_day = datetime.strptime(rid[:8], '%Y%m%d').date()
        eligible = 0
        for row in rows:
            for workout in workouts[row['horse_id']]:
                day = datetime.strptime(workout['day'], '%Y%m%d').date()
                created = datetime.strptime(workout['created'], '%Y%m%d').date()
                if 0 < (race_day - day).days <= 14 and created < race_day and digits(workout['f1']) and int(workout['f1']) > 0 and workout['center']:
                    eligible += 1
                    break
        results.append({'race_id': rid, 'runner_count': len(rows), 'input_checks_passed': not reasons,
                        'blockers': sorted(reasons), 'eligible_workout_runner_count': eligible,
                        'warnings': ['missing_workouts_use_neutral_multiplier'] if eligible < len(rows) else []})
    return {'assessed_at': as_of.isoformat(), 'capture_finished_at': entry['capture_finished_at'],
            'capture_sequence': entry['sequence'], 'races': results,
            'observed_races': len(results), 'input_checks_passed_races': sum(r['input_checks_passed'] for r in results),
            'blocked_races': sum(not r['input_checks_passed'] for r in results),
            'blocker_counts': dict(Counter(reason for r in results for reason in r['blockers'])),
            'state': 'awaiting_source_data' if not results else 'input_checks_completed',
            'prediction_pipeline_ready': False, 'predictions_computed': False,
            'production_decision': 'REJECT',
            'limitations': ['Checks establish local input consistency only, not official roster completeness.',
                            'Registered count equality does not establish final starter identity or late cancellations.',
                            'Input checks alone do not verify historical feature freshness or a frozen prediction.',
                            'Latest observation only; old roster snapshots are not substituted.',
                            'Same-day prediction is conservatively disabled.']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', help='JST ISO timestamp for offline replay; default current time')
    args = parser.parse_args()
    entries = p.verify()
    if not entries:
        raise ValueError('Capture data is required')
    # Fail closed when the active implementation/model differs from the frozen assets.
    seal = p.read(p.BASE / 'model-seal.json')
    for name, expected in seal['files'].items():
        if p.digest((p.ROOT / name).read_bytes()) != expected:
            raise ValueError('Current model or helper differs from sealed version: ' + name)
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(p.JST)
    before = {path.name: p.digest(path.read_bytes()) for path in (p.BASE / 'captures').glob('*.json')}
    result = assess(entries[-1]['entry'], as_of)
    result.update(capture_sha256=entries[-1]['sha256'], model_seal_sha256=p.digest(p.encoded(seal)),
                  checker_sha256=p.digest(Path(__file__).read_bytes()), db_connection_used=False)
    if before != {path.name: p.digest(path.read_bytes()) for path in (p.BASE / 'captures').glob('*.json')}:
        raise ValueError('Capture changed during input checks')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'result.json').write_bytes(p.encoded(result))
    print(f'Input checks: {result["observed_races"]} races, {result["input_checks_passed_races"]} passed, {result["blocked_races"]} blocked; {result["state"]}')


if __name__ == '__main__':
    main()
