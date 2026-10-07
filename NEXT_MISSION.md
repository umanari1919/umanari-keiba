# NEXT MISSION

Mission ID: `BAOZ-BASELINE-001`
更新日: 2026-10-08
Priority: P0
Status: IMPLEMENTATION READY / LOCAL EVIDENCE PENDING

## Goal

Freeze and measure BaoZ immediately after initial setup, before any customization.

Determine whether BaoZ standard marks actually identify strong horses and separately
whether single/place betting on those marks has positive or negative return.

## GitHub-side scope

GitHub contains only:

- evaluation contract
- pure aggregation code
- tests
- CI
- aggregate result format
- research policy

Do not upload MDB files, service keys, PostgreSQL DB files, or licensed raw data.

## Local one-shot evidence required later

Use a read-only local step to produce only the minimum research CSV defined in:

`docs/BAOZ_BASELINE_001.md`

Required fields:

- race_id
- runner_id
- mark
- finish_position

Preferred fields:

- popularity
- win_return_yen
- place_return_yen

Optional slice fields:

- surface
- distance_m
- class_name
- track
- field_size

## Required outputs

1. Target period.
2. Race count.
3. Runner count.
4. ◎ / ○ / ▲ / △ starts.
5. Win rate.
6. Top-2 rate.
7. Top-3 rate.
8. Popularity-band performance.
9. Win ROI when payout data is available.
10. Place ROI when payout data is available.

## Safety

- Do not change BaoZ settings.
- Do not write to BaoZ MDB.
- Do not delete or move BaoZ / JV-Link / UmaConn files.
- Do not change PostgreSQL data.
- Do not expose service keys.
- Do not use BaoZ-derived values in public/commercial prediction outputs.
- No automatic wagering.

## Completion

PASS requires reproducible aggregate evidence from the untouched baseline.

If local extraction is blocked, return PARTIAL/BLOCKED with the exact missing
table/field/path/interface and do not compensate by manually changing BaoZ settings.

## After this Mission

Only after baseline PASS:

`BAOZ-FAILURE-002` — analyze races where the BaoZ top mark fails and identify
conditions for dangerous favorites without changing the frozen baseline.
