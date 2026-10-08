# ATLAS CI Incident — 2026-10-08 — pre-job startup_failure / BuildFailed

**Source:** GitHub Actions API for `umanari1919/umanari-keiba` (no licensed JRA/NAR records involved). This is a record of observed workflow metadata, **not** a proven GitHub backend root cause. Keep PR #65 Draft.

## Verified behavior

- Branch: `feat/atlas-jvdata-map-003`, PR #65, base `feat/atlas-jvlink-acquire-002`.
- Healthy earlier parent/stacked CI: `https://github.com/umanari1919/umanari-keiba/actions/runs/37738797249` (synthetic mapper tests, before later changes).
- Repeated failing run: `https://github.com/umanari1919/umanari-keiba/actions/runs/37740327270`; event push/PR, `conclusion=startup_failure`, `name=""`, `path="BuildFailed"`, **zero jobs**, no Python runner or test execution.
- Further failure after offline fallback added: `https://github.com/umanari1919/umanari-keiba/actions/runs/37741906902`; same zero-job signature.
- PR #65 remains **mergeable but Draft**, and #61/#63/#64 remain Draft/unmerged. Mergeable != verified/tested.
- The connected GitHub action to update PR metadata also returned 403 with the text `At least one email address must be verified to do that.` This **may be a separate account or connection permission requirement**; it does not prove it caused zero-job BuildFailed.
- One attempt to rerun a synthetic zero-job failure was rejected by GitHub (403 `This workflow run cannot be retried`).

## Third-party reports — **similar, not necessarily the same cause**

- [GitHub community issue #207492](https://github.com/orgs/community/discussions/207492): zero-job BuildFailed, active workflows and subsequent manual workflow_dispatch failures.
- [GitHub community issue #208822](https://github.com/orgs/community/discussions/208822): multiple private repos, repeated startup_failure even with a minimal workflow.
- These are community reports and cannot independently establish this repository's cause.

## Safe next checks

1. The user can confirm at `https://github.com/settings/emails` whether their GitHub email is verified; **do not share any verification email, tokens, or passwords**.
2. From repository Actions UI, check whether workflows are enabled, whether runs on other branches/default `main` still start, and whether any account quota/policy is shown. Avoid destructive reinstallation or unnecessary repository migrations.
3. If a known-valid minimal run on default `main` also produces `BuildFailed` and zero jobs, include the exact run IDs, UTC timestamps, branch/SHA, and `workflow_id` above in a GitHub Support case.
4. In parallel, use `tools/ATLAS-OFFLINE-SELFTEST.cmd` **only after code has been safely synced to Windows**. Its synthetic tests deliberately remove local DB DSNs, integration flags, and SDK keys from subprocess environments.
5. Do **not** merge PR #65 or promote production data while CI/preflight and the user's actual SDK + local DB are unverified.

## Strict progress vocabulary

- `CODE_PRESENT`: files are committed to this repository.
- `SYNTHETIC_TEST_PASSED`: only for exact commit SHA with actual completed green jobs.
- `CI_UNAVAILABLE`: GitHub didn't start a job; **never call it PASS**.
- `REAL_SDK_UNVERIFIED`: user's Windows JV-Link has not been invoked.
- `ATLAS_DB_UNCREATED_LOCALLY`: no confirmation of actual user-PC `neo_jizo_atlas` creation.
- `PRODUCTION_HOLD`: model promotion and use in production forbidden.

**No local hardware, user databases, Windows services, or original racing datasets have been modified by this GitHub-only operation.**
