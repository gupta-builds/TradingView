---
name: kiro-status
description: Reconcile .kiro/specs/data-ingestion-foundation/tasks.md checkbox state against what actually exists in src/research_data/ and tests/, and report what's really done, in-progress, or missing.
---

# kiro-status

Report the true implementation status of the data-ingestion-foundation spec, since `tasks.md` checkboxes can drift from the real codebase.

## Steps

1. Read `.kiro/specs/data-ingestion-foundation/tasks.md` and list every task with its checkbox state (`[x]`, `[-]`, `[~]`, `[ ]`).
2. For each task, identify the file(s)/function(s)/test(s) it names and check whether they actually exist:
   - `ls`/`grep` the named file under `src/research_data/` or `tests/`.
   - For property tests, confirm the file exists in `tests/test_property_*.py` and contains a test function (not just a stub).
   - Run `pytest <path> -q` for tests tied to the task, where feasible, to confirm pass/fail rather than just file existence.
3. Build a table: task id | tasks.md state | actual state (done / partial / missing) | evidence (file:line or test result).
4. Flag every mismatch between tasks.md state and actual state — both directions: tasks marked done that aren't, and tasks marked open/in-progress that are actually complete.
5. End with a short "next task to pick up" recommendation, respecting the `Task Dependency Graph` wave ordering in `tasks.md` (don't recommend a task whose dependencies are still open).

Do not edit `tasks.md` as part of this skill — report findings only. Use the `spec-implementer` agent to actually implement or check off a task.
