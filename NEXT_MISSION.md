# NEXT MISSION

Mission ID: `WEEKEND-REALITY-GATE-001`
更新日: 2026-10-07
Priority: P0
Status: READY

## Goal

Use the already-restored local code and local read-only data to determine the real
operational state for the upcoming JRA weekend and the requested historical replay.

Do not repeat source rescue.

## Required checks

1. Run the local portfolio/weekend status from the existing
   `neo-jizo-keiba` workspace.
2. Verify PostgreSQL `mykeibadb` access is read-only for the prediction path.
3. Re-check confirmed race-card availability for 2026-10-10 through 2026-10-12,
   Tokyo / Kyoto.
4. Keep special registrations separate from confirmed race cards.
5. Execute or finish the pre-race-only replay for 2026-10-03 and 2026-10-04.
6. For real cards that pass timing/roster gates, produce jockey-25
   win / top-2 / top-3 predictions.
7. Do not inject the unpromoted workout candidate into the personal output.
8. Report only operational blockers and usable predictions/results.

## Safety

- No source-file transport is needed.
- Do not delete the local workspace or database.
- Do not reset/clean the unborn local repository.
- No automatic wagering.
- No automatic research-to-production promotion.
- Prefer read-only DB access for this gate.

## Completion

Mission completes when we have:

- actual weekend source state,
- actual history/readiness state,
- 10/3–10/4 replay status,
- real predicted race/runner counts if cards are available,
- exact blockers if predictions are not yet possible.

After completion, the next mission should be chosen from actual runtime evidence,
not from the old rescue backlog.
