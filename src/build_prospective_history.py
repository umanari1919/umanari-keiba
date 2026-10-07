"""Rebuild research histories from sealed results; verify every stored jockey score."""
import gzip
import json
from collections import Counter, defaultdict, deque
import math
from pathlib import Path
import prospective_capture as p
import training_three_targets as t
from personnel_experiments import History

OUT = p.ROOT / 'artifacts/prospective-history-v1'


def context(horse, c):
    return (horse, c['track'], int(c['distance']) // 800, c['grade'] or '0', c['race_class'])


def strength(horse, c, jockey_id, general, local, jockey):
    runs, wins = general[horse]
    nr, nw = local[context(horse, c)]
    baseline = (wins + 1) / (runs + 12)
    specific = (nw + 2.) / (nr + 24)
    weight = min(.5, nr / (nr + 5))
    base = (1 - weight) * baseline + weight * specific
    jr, jw = jockey[jockey_id]
    jweight = .25 * jr / (jr + 100)
    return (1 - jweight) * base + jweight * ((jw + 10) / (jr + 120))


def dump_history(history):
    return {'config': history.config, 'today': history.today,
            'records': [[list(key) if isinstance(key, tuple) else key, isinstance(key, tuple),
                         state, list(history.events.get(key, []))] for key, state in history.states.items()]}


def restore_history(value):
    if value['config'] != {'kind': 'window', 'days': 1095}:
        raise ValueError('Unexpected history window')
    result = History(value['config'])
    result.today = value['today']
    for key, is_tuple, state, events in value['records']:
        key = tuple(key) if is_tuple else key
        if key in result.states or len(state) != 3 or not all(math.isfinite(v) for v in state):
            raise ValueError('Invalid serialized history')
        if state[0] != len(events) or abs(state[1] - sum(e[1] for e in events)) > 1e-8:
            raise ValueError('History totals differ from events')
        if state[2] > result.today or any(e[0] > result.today for e in events) or [e[0] for e in events] != sorted(e[0] for e in events):
            raise ValueError('History contains future or unordered events')
        result.states[key] = list(state)
        result.events[key] = deque(tuple(e) for e in events)
    return result


def main():
    from prospective_forecast import score_race
    root = p.ROOT
    metadata = t.load(t.OUT / 'baseline-verification.json')
    hashes = {}
    for name, expected in metadata['input_hashes'].items():
        path = root / 'artifacts/decade-2016-2025' / name
        if t.sha(path) != expected:
            raise ValueError('Historical input changed: ' + name)
        hashes[path.relative_to(root).as_posix()] = expected
    for name, expected in metadata['personnel_hashes'].items():
        path = root / 'datasets/rider-trainer-v1' / name
        if t.sha(path) != expected:
            raise ValueError('Historical personnel input changed')
        hashes[path.relative_to(root).as_posix()] = expected
    for name, expected in metadata['score_hashes'].items():
        if t.sha(t.OUT / name) != expected:
            raise ValueError('Frozen baseline scores changed')
        hashes[(t.OUT / name).relative_to(root).as_posix()] = expected
    oos = root / 'datasets/oos-2026-training-v1'
    for name in ('runners-2026.json', 'conditions-2026.json'):
        path = oos / name
        hashes[path.relative_to(root).as_posix()] = t.sha(path)
    diagnostic = root / 'artifacts/oos-2026-training-diagnostics-v1/runner-probabilities.jsonl.gz'
    hashes[diagnostic.relative_to(root).as_posix()] = t.sha(diagnostic)
    reference = defaultdict(list)
    with gzip.open(diagnostic, 'rt', encoding='utf-8') as handle:
        for line in handle:
            row = json.loads(line)
            reference[row['race_id']].append(row)
    stores = [History({'kind': 'window', 'days': 1095}) for _ in range(4)]
    general, local, jockey, workout = stores
    matched = rows_2026 = 0
    training_totals = t.empty()
    prior_training = t.empty()
    excluded = Counter()
    last_day = ''
    # No source query may be made: use only the previously captured workout cache.
    t.query = lambda *a: (_ for _ in ()).throw(RuntimeError('Offline history build prohibits DB refetch'))
    for year in range(2011, 2027):
        if year < 2026:
            base = root / 'artifacts/decade-2016-2025'
            condition_rows = t.load(base / 'conditions' / f'{year}.json')['rows']
            raw = [row for month in range(1, 13) for row in t.load(base / 'raw-cache' / f'{year}-{month:02}.json')['rows']]
            personnel = t.load(root / 'datasets/rider-trainer-v1' / f'{year}.json')['rows']
            ids = {(r['race_id'], r['horse_id']): r['jockey_id'] for r in personnel}
        else:
            condition_rows = t.load(oos / 'conditions-2026.json')['rows']
            raw = t.load(oos / 'runners-2026.json')['rows']
            ids = {(r['race_id'], r['horse_id']): r['jockey_id'] for r in raw}
        conditions = {r['race_id']: r for r in condition_rows}
        condition_counts = Counter(r['race_id'] for r in condition_rows)
        day_races = defaultdict(lambda: defaultdict(list))
        for row in raw:
            day_races[row['race_id'][:8]][row['race_id']].append(row)
        cache = t.CACHE
        if year == 2026:
            t.CACHE = oos / 'workouts'
        wood = t.collect(year, 'wood')[0] if year >= 2016 else {}
        if year >= 2016:
            workout_path = t.CACHE / f'wood-{year}.json.gz'
            hashes[workout_path.relative_to(root).as_posix()] = t.sha(workout_path)
        t.CACHE = cache
        handle = gzip.open(t.OUT / f'{year}-scores.jsonl.gz', 'rt', encoding='utf-8') if 2016 <= year <= 2025 else None
        try:
            for day, races in sorted(day_races.items()):
                last_day = day
                for store in stores:
                    store.set_day(day)
                updates, workout_updates = [], []
                for rid, records in sorted(races.items()):
                    c = conditions.get(rid)
                    if c is None or condition_counts[rid] != 1 or not (c['distance'] or '').isdigit() or int(c['distance'] or '0') <= 0 or not (c['track'] or '').isdigit() or len(c['track'] or '') != 2 or c['track'] == '00' or not c['race_class']:
                        excluded['invalid_conditions'] += 1
                        continue
                    if len({r['horse_id'] for r in records}) != len(records) or any(not r['horse_id'] or r['abnormal'] not in tuple('01234567') for r in records):
                        excluded['invalid_identity_or_status'] += 1
                        continue
                    active = [r for r in records if r['abnormal'] not in ('1', '2', '3')]
                    if not active or any(not r['finish'].isdigit() or (int(r['finish']) < 1 and r['abnormal'] != '4') for r in active):
                        excluded['unresolved_results'] += 1
                        continue
                    winners = sum(int(r['finish']) == 1 for r in active)
                    if not winners:
                        excluded['missing_winner'] += 1
                        continue
                    if year >= 2016 and winners == 1:
                        values = [strength(r['horse_id'], c, ids[(rid, r['horse_id'])], general, local, jockey) for r in active]
                        rows = [[r['horse_id'], int(r['finish']), s] for r, s in zip(active, values)]
                        if handle:
                            for row in rows:
                                if json.loads(next(handle)) != [rid] + row:
                                    raise ValueError('Independent jockey strength mismatch: ' + rid)
                                matched += 1
                        win = t.marginals(values)
                        if year == 2026:
                            expected = reference[rid]
                            if [r[0] for r in rows] != [r['horse_id'] for r in expected]:
                                raise ValueError('2026 population/order mismatch')
                            for k in range(3):
                                if any(abs(a - b['baseline'][k]) > 1e-12 for a, b in zip(win[k], expected)):
                                    raise ValueError('2026 baseline probability mismatch')
                            rows_2026 += len(rows)
                        bins = t.feature_bins(rid, rows, {'wood': wood}, 14, 'wood', '1f')
                        multipliers = [1.] * len(rows)
                        for i, key in bins.items():
                            n, correct = workout[key]
                            anticipated = workout[('expected',) + key][1]
                            ratio = max(.25, min(4., (correct + 10) / (anticipated + 10)))
                            weight = .25 * n / (n + 100)
                            multipliers[i] = 1 + weight * (ratio - 1)
                            workout_updates.append((key, int(rows[i][1] == 1), win[0][i]))
                        adjusted = t.marginals([s * m for s, m in zip(values, multipliers)])
                        t.add(training_totals if year == 2026 else prior_training, t.metrics(rows, adjusted))
                        if year == 2026:
                            for k in range(3):
                                if any(abs(a - b['candidate'][k]) > 1e-12 for a, b in zip(adjusted[k], expected)):
                                    raise ValueError('2026 workout probability mismatch')
                            inputs = [{'horse_id': r['horse_id'], 'horse_number': str(i + 1),
                                       'jockey_id': ids[(rid, r['horse_id'])]} for i, r in enumerate(active)]
                            api = score_race({'snapshot_through': '20251231'}, dict(c, race_id=rid), inputs, [],
                                             stores=dict(zip(('general', 'local', 'jockey', 'workout'), stores)), wood_store=wood)
                            for a, b in zip(api, expected):
                                if any(abs(a[name][k] - b[field][k]) > 1e-12 for name, field in (('jockey_25', 'baseline'), ('wood_14_1f_25', 'candidate')) for k in range(3)):
                                    raise ValueError('Future scoring API does not reproduce 2026 reference')
                    # All valid outcomes, including win ties, update baseline history after the entire day.
                    updates.extend((r['horse_id'], context(r['horse_id'], c), ids[(rid, r['horse_id'])], int(r['finish']) == 1) for r in active)
                for horse, key, rider, win in updates:
                    general.add(horse, int(win)); local.add(key, int(win)); jockey.add(rider, int(win))
                for key, win, anticipated in workout_updates:
                    workout.add(key, win); workout.add(('expected',) + key, anticipated)
            if handle and handle.readline():
                raise ValueError('Historical score file has extra rows')
        finally:
            if handle:
                handle.close()
        print(f'History replay {year} verified', flush=True)
    for actual, expected in ((t.finalize(prior_training), t.load(t.OUT / 'results/wood-14-1f-25.json')['overall']),
                             (t.finalize(training_totals), t.load(root / 'artifacts/oos-2026-training-v1/result.json')['candidate'])):
        for k in ('1', '2', '3'):
            for metric in ('logloss', 'brier', 'top_pick_observed_rate'):
                if abs(actual[k][metric] - expected[k][metric]) > 1e-12:
                    raise ValueError('Workout aggregate mismatch')
    if matched != 479100 or rows_2026 != 36511:
        raise ValueError('Unexpected replay population')
    if any(t.sha(root / name) != expected for name, expected in hashes.items()):
        raise ValueError('History source changed during replay')
    OUT.mkdir(parents=True, exist_ok=True)
    state = {'version': 1, 'built_at': p.datetime.now(p.JST).isoformat(), 'last_result_day': last_day, 'snapshot_through': '20261005',
             'general': dump_history(general), 'local': dump_history(local),
             'jockey': dump_history(jockey), 'workout': dump_history(workout),
             'source_hashes': hashes, 'builder_sha256': t.sha(Path(__file__)), 'production_approved': False}
    with gzip.open(OUT / 'history.json.gz', 'wb') as output:
        output.write(p.encoded(state))
    with gzip.open(OUT / 'history.json.gz', 'rt', encoding='utf-8') as handle:
        roundtrip = json.load(handle)
    for name in ('general', 'local', 'jockey', 'workout'):
        if dump_history(restore_history(roundtrip[name])) != state[name]:
            raise ValueError('Serialized history round-trip mismatch')
    verification = {'historical_strengths_exact': matched, '2026_probability_rows_verified': rows_2026,
                    'three_target_workout_metrics_reproduced': True, 'same_day_outcomes_excluded': True,
                    'last_result_day': last_day, 'snapshot_through': '20261005',
                    'state_sha256': t.sha(OUT / 'history.json.gz'), 'source_hashes_unchanged': True,
                    'history_roundtrip_verified': True,
                    'future_scoring_api_reproduced_2026': True,
                    'db_connection_used': False, 'predictions_computed_for_future': False,
                    'production_decision': 'REJECT'}
    (OUT / 'verification.json').write_bytes(p.encoded(verification))
    print(json.dumps(verification, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
