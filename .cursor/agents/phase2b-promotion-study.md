---
name: phase2b-promotion-study
description: Runs F1–F3 + promotion study only after Cursor V1–V5 go/no-go. Quotes Fable Phase 2b design.
---

# Phase 2b promotion study (Fable implementer)

**Do not run this agent until Cursor’s go/no-go is green.** SoT:
`Docs/PHASE2B_SOLUTION_DESIGN.md` §2–§5 and `Docs/PHASE2B_PROBLEM_STATEMENT.md`.

## Preconditions (verify with tools — all required)
1. `python scripts/deepen_history.py --probe-only --start-date 2022-01-02` (or `2020-07-06`) → depth sufficient
2. **V1:** every symbol `n ≥ 1135` (target ≥ 1513); `lo` ≤ tier start
3. **V2:** single `source` + `split_dividend_adjusted`; zero null `adjusted_close`
4. **V3:** calendar match vs VOO (0 mismatches)
5. **V4:** no 1-day adjusted move > 35% (split residue)
6. **V5:** quarterly fundamentals earliest_q ≤ tier target for all 10 equities (~20–23 quarters)
7. Gate constants untouched (504/126/126, min_windows=3, etc.)
8. Work on a **new** `feat/...` branch — do not dump onto PR #1 pack merge

If any check fails → **stop and report**. Do not loosen gates. Do not stitch a second price source.

## Implement (Fable coding only)
1. **F1 — source seam:** `--source` on `scripts/run_quality_momentum_study.py` →
   `price_source` on study/hook → `get_price_frame(source=...)`. Unit test with
   mixed-source fixture; single-source path unchanged.
2. **F2 — depth preflight:** print `N`, `R = N − 253` vs OOS/MC/WF/DSR minima;
   name which gate cannot pass if under-depth (informational; fail-closed unchanged).
3. **F3 — report:** per-window WF table; DSR intermediates (`sr_hat`, `SR0`,
   `n_trials`, skew/kurtosis); cash-session count; eligible cross-section size
   per rebalance. No execution language.
4. Re-run offline suite (prefix-invariance, eligibility, thin fail-closed, synthetic four-gate).
5. Promotion study (manual sequence from design §3): backup DuckDB → V1–V5 →
   study run → stdout artifact → human `--record-decision --approver anant`
   (always record; DEMO_ELIGIBLE only on 4/4 + agreement; HOLD/UNPROVEN on fail
   or trails-VOO).
6. Update docs/vault with **measured** numbers only. Guardrail-auditor before PR.

## Success split
- **Coding DoD:** all four gates *execute* on real bars; failures recorded; journal
  rules honored; CI green. Honest fail batch = valid artifact.
- **“Desk is real”:** 4/4 possible and, if pass, human promotion + replay vs VOO
  with trade count / costs / max DD. Do not redefine desk-is-real downward.

## Out of scope
New strategies, Kronos, UI, orchestration framework, universe change, gate edits,
auto-promote, concurrent ingest+study.
