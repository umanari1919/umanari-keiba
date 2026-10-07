# NEO-JIZO-DIRT-EDGE-025

Status: EVALUATION CORE IMPLEMENTED / LOCAL EVIDENCE PENDING  
Date: 2026-10-08

## Mission

Build an independent NEO JIZO benchmark for the regime where the untouched BaoZ baseline lost market-relative selection strength:

- dirt
- popularity 7-9 as an evaluation slice
- BaoZ private benchmark: 馬券評価順位=1

BaoZ must not be used as a teacher label.

## Frozen BaoZ benchmark

### 2019-2023

- market base: 3,915 / 199,966 = 1.958%
- BaoZ selected: 158 / 3,483 = 4.536%
- market-relative lift: 2.317x
- selection OR vs non-selected: 2.438
- 95% CI [2.071, 2.869]

### 2024-2026-10-08

- market base: 2,137 / 113,832 = 1.877%
- BaoZ selected: 62 / 2,098 = 2.955%
- market-relative lift: 1.574x
- selection OR vs non-selected: 1.609
- 95% CI [1.245, 2.080]

### Regime change

- selected win-rate difference: -1.581pt
- p = 0.003281
- base market difference: -0.081pt
- p = 0.114896
- post/pre selection-OR ratio: 0.660
- 95% CI [0.487, 0.894]
- p = 0.007374

Interpretation:

The decline is supported as a BaoZ-selection-strength change within this specific regime. It is not evidence that BaoZ is globally worse.

Historical BaoZ evidence remains retrospective evaluation, not a certified archived-forecast backtest.

## NEO JIZO hypothesis

Recent BaoZ component-level evidence suggests that useful signal still exists in:

- expected-time / speed signal
- early-position / pace signal
- running-style suitability
- bloodline track suitability
- bloodline overall suitability
- draw/context signal
- time-index regression signal

Some other BaoZ-side signals weakened or reversed in this regime, including:

- jockey evaluation
- trainer evaluation
- some B-series bloodline evaluations
- time-index rise coefficient
- composite V1/V2 discrimination

These are benchmark observations only. NEO JIZO must independently define and validate its own features.

## Model targets

Train/evaluate separate probability targets:

1. win
2. top-2
3. top-3

Do not optimize only for winner classification.

## Core NEO JIZO feature families

1. Speed / expected time
2. Pace / early-position ability
3. Running-style fit
4. Bloodline distance/track fit
5. Course, draw, field size, going and distance context
6. Field Strength
7. Training
8. Jockey/trainer with time-aware statistics
9. Recent form / class movement / layoff
10. Race-level firmness/upset context

## Evaluation slices

Required:

- 2019-2023 reference
- 2024 onward recent
- JRA / NAR
- venue
- field size
- distance
- going
- odds bands
- popularity bands
- race firmness class

Popularity and odds are evaluation/market-comparison variables first. They must not silently leak into independent ability estimation.

## Metrics

Required:

- win rate
- top-2 rate
- top-3 rate
- calibration / Brier or equivalent
- market-relative lift
- odds-ratio advantage vs comparable non-selected runners
- confidence intervals
- yearly stability
- recent-vs-reference stability

Betting/ROI is downstream and must not replace predictive validation.

## Comparison hierarchy

For each evaluation slice compare:

1. raw market baseline
2. BaoZ frozen private benchmark
3. NEO JIZO independent ability/probability model

The objective is not to beat BaoZ historically at any cost.

The objective is to preserve recent predictive discrimination without temporal leakage or overfitting.

## Temporal safety

Every historical feature must be as-of-race-date safe.

Disallowed:

- current/latest aggregate statistics applied retrospectively
- future results in historical feature generation
- post-race odds/results in pre-race model inputs
- tuning against the 2024-2026 target until the reference/recent split contract is frozen

## Acceptance gate

PASS requires:

- reproducible recent-period evaluation
- win/top2/top3 reported together
- no temporal leakage
- market-relative comparison
- BaoZ private benchmark comparison
- recent lift that is stable enough to justify further model work

If the NEO JIZO signal does not improve or remain stable in recent data, return PARTIAL/FAIL and diagnose instead of repeatedly tuning.

## Operating rule

Keep BaoZ untouched.

No BaoZ setting changes are permitted under this mission.

## Implemented evaluation contract

GitHub-side evaluator:

- `src/neo_jizo_dirt_edge.py`
- `tests/test_neo_jizo_dirt_edge.py`
- `.github/workflows/neo-jizo-dirt-edge-025.yml`

Required row fields:

- `race_id`
- `runner_id`
- `finish_position`
- `model_rank`
- `p_win`
- `p_top2`
- `p_top3`

Evaluation/slice fields:

- `race_date`
- `popularity`
- `odds`
- `surface`
- `organizer`

The evaluator enforces:

- unique `race_id + runner_id`;
- positive finish position and model rank;
- probabilities in [0, 1];
- `p_win <= p_top2 <= p_top3`;
- popularity/odds positivity when supplied.

Outputs include:

- base and selected win/top2/top3 rates;
- average predicted probabilities;
- calibration gaps for all three targets;
- Brier scores for all three targets;
- market-relative lift for all three targets;
- win odds-ratio vs non-selected runners;
- yearly splits;
- organizer splits.

The first local evidence step must provide only the minimum sanitized prediction/result rows needed by this contract. No MDB or PostgreSQL dump is required.
