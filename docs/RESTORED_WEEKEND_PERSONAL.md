# Restored weekend personal forecast chain

Restored on 2026-10-07 from the preserved local-worktree branch
`umanari1919-zeus/keiba-ai:rescue/neo-jizo-local-20261007-140123`.

## Scope

This slice restores the personal JRA weekend chain used by the rescued workspace:

1. source-status inspection,
2. history refresh,
3. prospective capture,
4. readiness checks,
5. sealed jockey-25 forecast,
6. personal pre-start forecast,
7. local UI publication,
8. `jwk run weekend-run` orchestration.

The weekend target encoded in the rescued implementation is
2026-10-10 through 2026-10-12, Tokyo and Kyoto.

## Safety semantics

- personal decision support only,
- no automatic wagering,
- no production-model promotion,
- DB query path requires read-only PostgreSQL settings,
- same-race start boundary is fail-closed,
- cancelled / abnormal or roster-mismatched races are blocked,
- saved personal output contains only the jockey-25 probabilities,
  not the unpromoted workout candidate.

The code still depends on local sealed historical artifacts and the local
PostgreSQL database for real execution. GitHub CI validates only the offline
logic and UI contracts.
