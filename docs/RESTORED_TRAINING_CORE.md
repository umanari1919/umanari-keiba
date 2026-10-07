# Restored jockey-25 / 3-target / training core

Restored on 2026-10-07 from the preserved local-worktree branch:

- source repository: `umanari1919-zeus/keiba-ai`
- source branch: `rescue/neo-jizo-local-20261007-140123`
- preserved rescue commit: `0986a471ca0220259d0cdb1c7626830875186625`

## Restored scope

This first restoration slice contains the minimum coherent dependency closure for:

- frozen `jockey-25` baseline score replay,
- three targets: win / top-2 / top-3,
- 48 chronological workout candidates,
- locked 2026 out-of-sample evaluation,
- diagnostics / finalization / publication helpers.

The central implementation is `src/training_three_targets.py`.

## Important model semantics

The restored implementation does **not** train three independent target models.
It starts from frozen win strengths and derives exact Plackett-Luce top-1 / top-2 / top-3 marginals.

The 48 workout candidates are the Cartesian product of:

- source: hanro / wood / both,
- window: 7 / 14 days,
- feature: presence / count / 4F / 1F,
- cap: 0.10 / 0.25.

Historical workout records are admitted only when both workout day and source creation day are strictly before race day.

## Status

Restoration is preservation and reproducibility work, **not production approval**.

- baseline: jockey-25 retained,
- 48 workout candidates: research evaluation,
- selected prior candidate: wood-14-1f-25,
- 2026 evaluation: locked OOS workflow present,
- production approval: false in the restored code.

Database writes, service changes, and automatic wagering are not part of this restoration.
