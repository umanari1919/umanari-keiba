# PHASE D AUTONOMY LANE

Created: 2026-06-13
Issue: #2

## Mission

Codex / Hermes should move Phase D forward with broad autonomy, while preserving the core safety rule:

> 壊さず吸収する。

The goal is not to keep auditing forever. The goal is to turn Phase C evidence into useful UmanariGenesis development direction.

## Current status

Phase C Final Audit Gate completed:

- Final verdict: PASS_WITH_WARN
- Final gate fail: 0
- Adaptive OK before: 6
- Adaptive errors before: 4
- Light retry OK: 4
- Light retry errors: 0
- Total available results: 10
- Skipped quarantine: 5
- Adoption candidates: 10

## Primary local evidence files

These files are expected on the local Windows workspace:

- `C:\Users\uchih\work\UmanariDiskCare\phase_c_adoption_candidates_latest.csv`
- `C:\Users\uchih\work\UmanariDiskCare\phase_c_final_audit_gate_latest.csv`
- `C:\Users\uchih\work\UmanariDiskCare\PHASE_C_FINAL_AUDIT_GATE_SUMMARY_latest.md`
- `C:\Users\uchih\work\keiba_ai_system\keiba_ai_system\docs\legacy_review_selected\PHASE_C_FINAL_AUDIT_GATE_INDEX.md`

## Allowed autonomy

Codex / Hermes may freely work on:

1. Phase D adoption triage
2. Non-destructive VIEW blueprint documents
3. Audit report specifications
4. API/UI improvement proposals
5. Roadmaps and implementation backlogs
6. Docs/reports organization
7. Dry-run / read-only / report-only scripts
8. Static checks and syntax checks
9. PR-ready summaries
10. Next-chat handovers

## Hard guardrails

Do not do these:

- No DB deletion
- No DB writes
- No `INSERT`
- No `UPDATE`
- No `DELETE`
- No `DROP`
- No `ALTER`
- No `TRUNCATE`
- No `COPY`
- No immediate `CREATE TABLE`
- No immediate `CREATE OR REPLACE VIEW`
- No direct legacy SQL execution
- No SQL-izing quarantine items
- No `.env` or credential changes
- No destructive filesystem operations

## SQL policy

Permitted, when necessary:

- `SELECT`
- `WITH`
- `LIMIT`
- `information_schema`
- `pg_class` / `pg_namespace`
- CSV/MD report output

`CREATE VIEW` must first be represented only as a blueprint or `.sql.txt` review artifact.

## Phase D candidate order

1. `FEATURE_SOURCE_COUNT`
   - Bucket: `NON_DESTRUCTIVE_VIEW_CANDIDATE`
   - Purpose: TOP10 feature coverage and missing-data readiness.

2. `JRA_CANONICAL_COUNT`
   - Bucket: `NON_DESTRUCTIVE_VIEW_CANDIDATE`
   - Purpose: JRA race identity / canonical mapping / race_code-hidden UI quality.

3. `NAR_DIAGNOSTICS_COUNT`
   - Bucket: `AUDIT_REPORT_CANDIDATE`
   - Purpose: NAR daily operations, missing data detection, backfill planning.

4. `AI_MYOMI_GEIKISO_COUNT`
   - Bucket: `AI_MYOMI_AUDIT_AND_SERVICE_CANDIDATE`
   - Purpose: AI妙味指数 and 激走馬 explanation quality.

5. `JRA_LOADER_DRYRUN_COUNT`
   - Bucket: `LIGHTWEIGHT_JRA_ODDS_REVIEW_HOLD`
   - Purpose: Keep bounded evidence; avoid full `odds_unified` scans until an index strategy is reviewed.

## Expected outputs

Target local outputs:

- `phase_d_adoption_triage_latest.csv`
- `phase_d_non_destructive_backlog_latest.csv`
- `PHASE_D_ADOPTION_TRIAGE_SUMMARY_latest.md`
- `PHASE_D_NON_DESTRUCTIVE_BLUEPRINT_PACK_latest.md`
- `CEO_PHASE_D_AUTONOMY_BRIEF_latest.md`
- `CODEX_PHASE_D_AUTONOMY_PACKET_latest.md`
- `HERMES_PHASE_D_AUTONOMY_PACKET_latest.md`
- `NEXT_CHAT_HANDOVER_UMANARI_DISKCARE_PHASE_D_latest.md`

Target repo docs:

- `docs/legacy_review_selected/PHASE_D_ADOPTION_TRIAGE_INDEX.md`
- `docs/legacy_review_selected/PHASE_D_NON_DESTRUCTIVE_BLUEPRINT_INDEX.md`

## Completion criteria

Phase D is considered ready for the next stage when:

- All 10 adoption candidates are classified.
- Quarantine 5 remains quarantined.
- Each high-value item has a non-destructive next action.
- No DB write or DDL is performed.
- A Codex/Hermes handover exists.
- A CEO brief exists.

## CEO note

Stop over-auditing. Move with controlled autonomy.

The project needs forward momentum: classify, blueprint, propose, summarize, and prepare PR-ready work.

Safety guardrails stay on. The horses can run, but not off the cliff.
