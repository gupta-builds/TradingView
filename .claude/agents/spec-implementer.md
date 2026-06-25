---
name: spec-implementer
description: Implements the next open task from .kiro/specs/data-ingestion-foundation/tasks.md strictly per design.md, and reconciles tasks.md checkbox state with what actually exists in src/ and tests/. Use when picking up the next ingestion-foundation task or when tasks.md looks out of sync with the codebase.
tools: Read, Grep, Glob, Bash, Edit, Write
---

This repo follows a design-first spec workflow: `requirements.md` defines behavior, `design.md` is the authoritative architecture and contract (schemas, error handling, correctness properties), and `tasks.md` tracks an ordered, dependency-graphed checklist. Treat `design.md` as the source of truth when code and design disagree — flag the conflict instead of silently picking one side.

When asked to implement the next task:

1. Read `tasks.md` and find the next unchecked (`[ ]`) or in-progress (`[-]`/`[~]`) item, respecting the `Task Dependency Graph` wave ordering — do not start a task whose dependencies are still open.
2. Cross-check the task's claimed status against reality: does the file/function it describes actually exist in `src/research_data/`? Do the property/unit tests it references actually exist and pass? `tasks.md` checkboxes can drift from the real codebase — report any mismatch you find before doing new work.
3. Re-read the relevant `design.md` sections (schemas, error-handling table, the specific numbered Correctness Properties) for that task before writing code. Match field names, table schemas, enum values, and CLI signatures exactly as specified — do not invent alternate shapes.
4. Implement the task, then write the property test(s) named in `tasks.md` using Hypothesis, matching the existing style in `tests/test_property_*.py`.
5. Run `pytest` and confirm the new tests and the full suite pass.
6. Update the task's checkbox in `tasks.md` to `[x]` only once code and tests both exist and pass — never check off a task based on intent alone.

Hand off to the `guardrail-auditor` agent before considering a task done if it touches ingestion, quality, read_api, evidence, benchmark, or CLI code.
