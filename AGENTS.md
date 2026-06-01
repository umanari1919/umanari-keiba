# AGENTS.md

## Project Purpose

`umanari-keiba` is a horse-racing AI repository for the うまなり地蔵 workflow. The foundation should support a practical prediction pipeline that turns NAR racing inputs into validated outputs that can be consumed by API and frontend tooling.

## Current Priority

Work in this priority order unless the user explicitly changes it:

1. NAR Prediction
2. EV
3. 激走馬
4. Base44 JSON
5. FastAPI `/docs`

## Safety Rules

- Inspect repository state before editing.
- Keep changes small and focused.
- Back up before risky edits or destructive operations.
- Prefer free and local tools before paid or remote services.
- Minimize token use by reading only the files needed for the task.
- Do not modify existing application code unless the user explicitly asks for implementation work.
- Do not introduce large rewrites, framework migrations, or broad refactors without explicit approval.
- Preserve existing behavior until tests or verification prove a change is safe.

## Verification Commands

Use the smallest relevant checks for the change. For workflow-only changes, run:

```bash
git status --short
find workflows -maxdepth 1 -type f -name '*.toml' -print | sort
python - <<'PY'
from pathlib import Path
required = [
    Path('AGENTS.md'),
    Path('workflows/nar_to_base44.toml'),
    Path('workflows/repair_and_verify.toml'),
    Path('workflows/db_api_frontend_check.toml'),
]
missing = [str(path) for path in required if not path.is_file()]
if missing:
    raise SystemExit(f"missing files: {missing}")
print('foundation files present')
PY
```

When application code is added later, also run the repository's relevant test, lint, type-check, and API startup commands as they become available.

## Coding Policy

- Prefer simple, explicit code over clever abstractions.
- Keep data contracts documented near the workflow or code that emits them.
- Validate JSON and API contracts before wiring frontend assumptions.
- Keep NAR prediction logic, EV calculations, 激走馬 selection, Base44 JSON export, and FastAPI integration separated until interfaces are stable.
- Use local fixtures and deterministic checks where possible.
- Never hide import failures with broad import-time `try`/`catch` or equivalent exception wrappers.

## No Large Rewrites

This repository should evolve in small, reviewable steps. Avoid sweeping reorganizations, generated code dumps, or replacing core architecture without a clear plan and explicit user approval.
