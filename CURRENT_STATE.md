# CURRENT STATE — NEO JIZO KEIBA / THE JOCKEY

更新日: 2026-10-07

## Canonical

- Repository: `umanari1919/umanari-keiba`
- Default branch: `main`
- Current restored main: `a8f27b4e54daedca88788e7459fd2d7e6e87dd08`
- GitHub is the canonical code/spec/history store.

## Local rescue result

Local workspace:

`C:\Users\uchih\Documents\Codex\2026-10-06\new-chat\neo-jizo-keiba`

SYNC-GATE-001 established:

- Git repository exists.
- Relation: `unborn`
- Local HEAD: `(unborn)`
- tracked changes: 0
- untracked files: 272

The rescue importer then preserved the safe code/document subset:

- Included: 248
- Conflicts preserved separately: 3
- Excluded: 2016 scanned items
- Secret-risk detections: 0
- Included size: 3.01 MB
- Rescue commit: `0986a471ca0220259d0cdb1c7626830875186625`
- Preservation branch: `umanari1919-zeus/keiba-ai:rescue/neo-jizo-local-20261007-140123`

The original local workspace was not modified by the rescue.

## Restored to canonical main

### PR #47 — jockey-25 / three targets / 48 workout candidates

Merged to main as:

`9b42572e085cc31ad720fa7ae152c8b3fdef1399`

Restored:

- frozen `jockey-25` score replay
- win / top-2 / top-3 probability evaluation
- 48 chronological workout candidates
- locked 2026 OOS evaluation
- diagnostic / finalization / publication helpers
- dependency closure

CI:

- Windows / Linux
- Python 3.13 / 3.14
- compile PASS
- 48 configs PASS
- Plackett-Luce target masses 1 / 2 / 3 PASS
- existing quality gates PASS

Important: restoration is not production promotion. The restored research code keeps production approval false.

### PR #48 — weekend personal forecast chain

Merged to main as:

`a8f27b4e54daedca88788e7459fd2d7e6e87dd08`

Restored:

- weekend source status
- prospective capture / readiness
- history refresh / history cache
- sealed jockey-25 forecast
- same-day pre-start personal forecast
- weekend orchestration
- local UI publication
- offline checks and unit tests
- `web/index.html`
- `jwk.cmd`

CI:

- Windows / Linux
- Python 3.13 / 3.14
- personal forecast tests PASS
- source/timing/orchestration/UI checks PASS
- restored training-core CI PASS
- existing quality gates PASS

## Current model/research state

- Baseline: `jockey-25`
- Three targets: win / top-2 / top-3
- Workout search: 48 candidates
- Previously selected workout candidate: `wood-14-1f-25`
- Workout candidate research status: KEEP
- Production status: REJECT / not promoted
- Personal weekend output intentionally saves jockey-25 probabilities only.
- Automatic wagering: disabled.

## Important correction

The earlier SYNC-GATE keyword count of 1 was a serialization artifact
(`System.Collections.Hashtable`) and is not model evidence.

## What is no longer required

- No more ZIP handoff.
- No more manual copying of rescued source files.
- No need to repeat RESCUE-MANIFEST-001 or RESCUE-IMPORT-001.
- Do not restart local/GitHub rescue from scratch.

## Remaining gap

GitHub now contains the restored code, but real execution still depends on the local
PostgreSQL/history/model artifacts and current race-card availability.

The next mission is therefore runtime reality verification, not more source rescue.
See `NEXT_MISSION.md`.
