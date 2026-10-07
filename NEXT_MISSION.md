# NEXT MISSION

Mission ID: `NEO-JIZO-DIRT-EDGE-025`
更新日: 2026-10-08
Priority: P0
Status: EVALUATION CORE IMPLEMENTED / LOCAL EVIDENCE PENDING

## Goal

Turn the confirmed BaoZ baseline weakness in
`馬券評価順位=1 x popularity 7-9 x dirt`
into an independent NEO JIZO benchmark and model-design test.

The mission is not to copy or tune BaoZ.
BaoZ remains a private benchmark.

## Frozen evidence

For P7-9 dirt:

- market base win rate:
  - 2019-2023: 1.958%
  - 2024-2026: 1.877%
- BaoZ-selected win rate:
  - 2019-2023: 4.536%
  - 2024-2026: 2.955%
- market-relative lift:
  - 2.317x -> 1.574x
- selection advantage OR:
  - 2.438 -> 1.609
- post/pre OR ratio:
  - 0.660
  - 95% CI [0.487, 0.894]
  - p = 0.007374

## Research question

Can NEO JIZO preserve or improve market-relative discrimination in this regime
using independent, time-aware features?

## Feature families to test

1. speed / expected time
2. pace and forward-position ability
3. running-style suitability
4. bloodline track/distance suitability
5. course / draw / field-size context
6. Field Strength
7. training
8. jockey/trainer, evaluated with strict time-aware validation

## Required probability targets

Evaluate separately:

- win probability
- top-2 probability
- top-3 probability

Do not optimize win rate alone.

## Evaluation design

Primary comparison windows:

- reference: 2019-2023
- recent: 2024 onward

Primary target regime:

- dirt
- popularity 7-9 used only for benchmark slicing, not as a model input unless explicitly approved
- compare NEO JIZO score/rank against market and BaoZ private benchmark

Required metrics:

- win / top2 / top3
- calibration
- market-relative lift
- odds-band stability
- JRA / NAR split
- venue split
- field-size split
- yearly stability
- confidence intervals where practical

## Guardrails

- Keep BaoZ settings unchanged.
- Do not use BaoZ outputs as public/commercial prediction content.
- Do not train NEO JIZO to imitate BaoZ rank/score.
- Do not leak future statistics into historical rows.
- Keep raw MDB/licensed data local.
- GitHub receives only code, contracts, tests, sanitized aggregate evidence, and hashes.
- No destructive DB changes.
- No automatic wagering.

## Completion gate

PASS requires a reproducible NEO JIZO benchmark showing whether independent
features improve recent P7-9 dirt discrimination relative to:

1. market baseline;
2. BaoZ frozen private benchmark;
3. NEO JIZO's own older-period performance.

If recent lift does not improve, report FAIL/PARTIAL rather than tuning until it does.


## Current implementation state

Completed on GitHub:

- independent three-target evaluation core;
- duplicate runner guard;
- monotonic probability guard;
- calibration/Brier metrics;
- market-relative lift;
- selection odds-ratio;
- year and organizer aggregation;
- Windows/Linux x Python 3.13/3.14 CI contract.

Next local dependency:

Produce a read-only, time-safe NEO JIZO prediction/result extract matching
`docs/NEO_JIZO_DIRT_EDGE_025.md`.

Do not run a new BaoZ probe for this step.
