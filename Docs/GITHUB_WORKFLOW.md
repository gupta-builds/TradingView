# GitHub workflow — how this repo stays clean after the year-ahead base

**Rule from 2026-07-10:** `main` is the frozen year-ahead base. Do not push feature work straight to `main` again. Open a branch, open a PR, wait for CI, then merge.

## Branch model

| Branch | Purpose |
|---|---|
| `main` | Always green. Year-ahead base + ingestion foundation. Protected by CI. |
| `setup` | Historical base branch — closed as of the year-ahead base commit. Do not continue feature work here. |
| `feat/*`, `fix/*`, `chore/*` | All new work. One concern per branch. |

## Required loop for every change

1. `git checkout main && git pull`
2. `git checkout -b feat/<short-name>` (or `fix/` / `chore/`)
3. Implement + run locally: `source .venv/bin/activate && pytest -q`
4. Push the branch: `git push -u origin HEAD`
5. Open a PR into `main` (GitHub UI or `gh pr create`)
6. Wait for **CI** (`.github/workflows/ci.yml`) — pytest on Python 3.11 and 3.12 + guardrail job
7. Merge only when CI is green
8. Delete the feature branch after merge

## What CI enforces

- Full offline `pytest` suite (no network, no real API keys)
- Package invariant canaries (year-ahead modules import; docs/workflow files present; 14-symbol universe; no PM packages; Kronos stays inference-free)
- Security/scope tests (`.env` gitignored, no broker SDKs, no execution language in CLI help)

## Local preflight (run before every PR)

```bash
source .venv/bin/activate
pip install -e .
pytest -q
```

If anything fails locally, do not open the PR.

## Secrets

- Keep keys in `.env` only (`POLYGON_API_KEY`, `FMP_API_KEY`, `SEC_USER_AGENT`)
- Never commit `.env` — CI fails if `.env` is tracked
- Use `.env.example` as the empty template

## Related

- Architecture contract: `Docs/YEAR_AHEAD_BASE.md`
- Guardrails: `CLAUDE.md`
