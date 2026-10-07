# NEO JIZO FORWARD — RESULT-002

Updated: 2026-10-08. Draft implementation and synthetic tests only; no real database query performed.

## Purpose
Connect pre-start sealed jockey-25 forecasts to local JRA final-result records, without leaking post-race data into the ability model or copying licensed rows to GitHub.

## Source and protections
- Source: public.umagoto_race_joho, using race_code, ketto_toroku_bango, kakutei_chakujun and ijo_kubun_code only.
- One SQL statement for read-only flags and one strictly SELECT-only fixed results query. The existing psql helper sets default_transaction_read_only=on and statement_timeout.
- The flag check and data query run in separate psql subprocess sessions: this is not a same-transaction attestation.
- Only verified pre-start receipt race IDs are used; strictly 16 ASCII digits, at most 96 races.
- All forecast and result rows stay under local artifacts/; never commit results, database dumps, model assets, or private data.

## Operation
1. python src/forward_results.py --receipt <LOCAL_RECEIPT_PATH>
   Offline check only: no DB access and no service startup. Reports safe result window and race count.
2. python src/forward_results.py --receipt <LOCAL_RECEIPT_PATH> --extract
   Explicit read-only extraction for an authorized, already reachable database only. No retry loops or service recovery.
3. The resulting local output is content-hash-addressed and the existing BLIND-001 scorer is invoked.

All races in the receipt must be at least 90 minutes past their scheduled start. A 90-minute guard is not proof of official result finalization. Invalid, missing, unknown or duplicate result identities are rejected or quarantined; they are never assigned a false loss.

## Outcome schema
- abnormal_code=0 plus numeric positive placing: FINISHED.
- abnormal_code=4 plus empty or zero placing: DID_NOT_FINISH.
- abnormal_code=1,2,3: NON_STARTER (whole race quarantined by current BLIND-001).
- Unknown, empty, invalid: UNRESOLVED (quarantined).
- Duplicate IDs, unexpected races or unexpected schema: hard error.
- Full pre-start/final runner reconciliation is required for scoring.

## Three-target output
Only fully reconcilable races get win, top2 and top3 Brier, calibration gap, actual rates and top1 pick accuracy, including JRA/year aggregates. All others remain quarantined. Scores and result rows stay local, outside GitHub.

## Trust and scope
- LOCAL_PRESTART_SEALED_UNATTESTED and SCORED_LOCAL_ONLY are *not* PROSPECTIVE_VERIFIED.
- Independent timestamp certification, official racecard coverage, licensed usage rights and official result finality remain unresolved.
- PostgreSQL 18 was previously observed offline, and this GitHub-only mission does not attempt a connection, restart or file repair.
- No DB migration, no automatic betting, no unapproved candidate promotion and no claim of profitability.
- Only JRA is handled here; NAR needs its own result-identity bridge.

## Automated checks
python -m unittest discover -s tests -p test_forward_results.py -v
CI: Windows/Linux, Python 3.13/3.14 with synthetic data and no external DB.

Stacked on BLIND-001 (PR #58). Unrelated ongoing PRs #54/#55/#57 remain untouched.
