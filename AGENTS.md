# AGENTS.md — Cursor working agreement for research_data

## What this project is
Personal AI market research desk (`research_data`). Not a broker, not TradingView.com, not a trading bot.

## Read first (in order)
1. `Docs/YEAR_AHEAD_BASE.md` — architecture contract
2. `Docs/PHASE3_AI_BRAIN_SOLUTION_DESIGN.md` + `Docs/PHASE3_AI_BRAIN_RUNBOOK.md` — AI hub SoT
3. `Docs/PHASE2_STRATEGY_PACK.md` — production strategy pack (Phase 2a)
4. `Docs/PHASE2B_PROBLEM_STATEMENT.md` + `Docs/PHASE2B_SOLUTION_DESIGN.md` — Phase 2b SoT
5. `Docs/HISTORY_DEPTH.md` — Cursor deepen ops
6. `Docs/GITHUB_WORKFLOW.md` — branch/PR/CI
7. `Docs/fable5_run_memory.md` — short lessons
8. Vault (jarvis): `Session Findings — AI Brain Hub (2026-07-12)`

## Phase 2b go/no-go (one page)

**Do not start Fable Phase 2b coding until every box is green.**

| # | Check | Owner | Pass criterion |
|---|---|---|---|
| 0 | Pack branch / PR #1 | Human | Phase 2a CI green; merge when ready (separate from 2b) |
| 1 | Provider depth | Human + Cursor | **Resolved 2026-07-11: Tiingo** (live probe reached recommended tier, N=1511 from 2020-07-06 — deeper than the registry's assumed 5.0y minimum-only estimate) |
| 2 | Probe | Cursor | `deepen_history.py --probe-only` not truncated below tier start |
| 3 | **V1** prices | Cursor | All 14 symbols `n ≥ 1135` (target ≥ 1513); `lo` ≤ 2022-01 / 2020-07 |
| 4 | **V2** | Cursor | One source; `split_dividend_adjusted`; 0 null adjusted_close |
| 5 | **V3** | Cursor | Calendar identical to VOO |
| 6 | **V4** | Cursor | No \|1-day adj move\| > 35% |
| 7 | **V5** fundamentals | Cursor | SEC quarterly depth matches price start (~20–23 qtrs); BRKB SEC-only |
| 8 | No mixed sources | Cursor | Do not add second price provider until **F1** ships |
| 9 | Gates untouched | Both | 504/126/126, min_windows=3, etc. |
| 10 | Fable coding | Fable | Only then: F1 → F2 → F3 → study on new `feat/...` |

If deepen truncates after a believed upgrade → **stop and ping** (no auto-loop, no filler source).

**Quota:** Cursor = deepen + V1–V5 + `.cursor` hygiene. Fable = F1–F3 + promotion study after go/no-go. Do not burn Fable on Massive plan / backfill / notes.

## Graphify
After large landings: `/graphify --update`. Outputs: `graphify-out/GRAPH_REPORT.md`.

## Claude Code parity
`.claude/` remains Claude Code tooling. Cursor mirrors: `.cursor/rules/`, `.cursor/agents/`. Keep guardrails in sync.

## Current phase
- **Done:** year-ahead base; Phase 2a/2b (`demo_eligible` on tiingo); Cursor Phase 3 AI hub prereqs + questionnaire locks; **Fable Phase 3 LLM seam** (2026-07-12, branch `feat/phase3-llm-seam`): `LiveLLMClient` (litellm.Router Gemini→Groq→Ollama + instructor, sole site `agents/llm_client.py`), evidence-bound analyst/critic prompts, CLI happy path, `scripts/live_ai_card_smoke.py` NVDA smoke; Cursor polish (`critique-spec` FactorEngine path, smoke vault mirror, tiingo CLI default).
- **Next:** human opens/merges the Phase 3 seam PR; V1.1 candidates (StrategySpec proposer, DuckDB `evidence_cards` build #2) stay parked per non-goals. No Phase 3b required for V1 locks.
- Vault SoT: `Session Findings — AI Brain Hub (2026-07-12)`; full Q&A: `Session Recap — AI Brain Hub Questionnaire (2026-07-12)`.
