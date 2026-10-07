"""Read-only validation of locked OOS inputs, outputs and probability population."""
import ast, json, sys
from pathlib import Path
import training_three_targets as t
OUT=t.ROOT/'artifacts/oos-2026-training-v1'

def main():
    manifest=OUT/'manifest.json'
    if not manifest.exists():
        print('Initial OOS run; no completion manifest yet');return
    for name,expected in t.load(manifest)['files'].items():
        if t.sha(t.ROOT/name)!=expected:raise ValueError('Frozen OOS input/output changed: '+name)
    result=t.load(OUT/'result.json');protocol=t.load(OUT/'protocol.json');impl=t.load(OUT/'implementation.json')
    assert result['protocol']==protocol
    assert impl['protocol_sha256']==t.sha(OUT/'protocol.json')
    assert impl['runner_sha256']==t.sha(t.ROOT/'src/evaluate_training_oos_2026.py')
    for name,expected in impl['helpers'].items():assert t.sha(t.ROOT/'src'/name)==expected
    raw=t.load(t.ROOT/'datasets/oos-2026-training-v1/runners-2026.json')['rows']
    assert len(raw)==len({(r['race_id'],r['horse_id']) for r in raw})
    assert all(protocol['evaluation_start']<=r['race_id'][:8]<=protocol['evaluation_end'] for r in raw)
    assert all(r['jockey_id'] and r['trainer_id'] for r in raw)
    pairs=t.load(OUT/'jockey-2026-pairs.json')
    assert len(pairs)==len({r['race_id'] for r in pairs})
    assert result['last_scored_day']==max(r['day'] for r in pairs)
    assert all(a['day']<b['day'] for a,b in zip(result['paired_days'],result['paired_days'][1:]))
    for k in ('1','2','3'):
        a=result['baseline'][k];b=result['candidate'][k]
        assert (a['rows'],a['races'])==(b['rows'],b['races'])
        for metric in ('logloss','brier','top_pick_observed_rate'):
            assert abs(result['delta'][k][metric]-(b[metric]-a[metric]))<1e-12
    improved=all(result['delta'][k][m]<0 for k in ('1','2','3') for m in ('logloss','brier'))
    safe=all(result['delta'][k]['top_pick_observed_rate']>=0 for k in ('1','2','3'))
    promote=improved and safe and all(r['p_holm']<.05 for r in result['paired_tests'])
    expected='PROMOTE' if promote else 'KEEP' if improved else 'REJECT'
    assert result['experiment_decision']==expected and result['production_decision']=='REJECT'
    assert result['previous_candidate_reproduced']
    capture=t.load(OUT/'capture-verification.json');assert capture['all_prior_scores_exactly_matched'] and capture['matched_rows']==479100
    for name in ('evaluate_training_oos_2026.py','publish_training_oos_2026.py','check_training_oos_2026.py'):
        ast.parse((t.ROOT/'src'/name).read_text(encoding='utf-8-sig'))
    t.save(OUT/'regression-checks.json',{'passed':True,'checks':['frozen input/result hashes','protocol and implementation hashes','unique runner identities and locked date range','unique races and chronological daily updates','matched candidate/baseline evaluation population','metric differences independently recalculated','fixed acceptance decision reproduced','all 479100 prior baseline strengths matched','prior workout candidate metrics reproduced','new code syntax parsed']})
    print('Locked OOS manifest and all ten consistency checks passed')
if __name__=='__main__':main()
