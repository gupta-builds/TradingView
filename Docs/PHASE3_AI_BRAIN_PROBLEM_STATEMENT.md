# Phase 3 — Problem statement: AI brain hub (analyst + critic)

> Cursor design questionnaire lock, 2026-07-11/12. Companion:
> `Docs/PHASE3_AI_BRAIN_SOLUTION_DESIGN.md`, `Docs/PHASE3_AI_BRAIN_RUNBOOK.md`,
> `Docs/NORTH_STAR_DESK.md`. Vault SoT:
> `Session Findings — AI Brain Hub (2026-07-12)`.

## Problem

The research desk already has a closed **Python** loop:

```text
citation → proposed spec → human approve → hook → four gates → promote/demote → journal
```

Phase 2b left `quality_momentum_tilt_top3` **demo_eligible** on tiingo depth
(spec `5f003778-42bc-4d8a-ac12-839699d98a02`, decision `6b46e5fb-…`). What is
missing is the **AI harness**: thin analyst/critic that only cites packets,
never invents numbers, never approves/promotes, and compounds journal lessons
into Citations — without dumping freeform “knowledge” into the brain
(student-toy failure mode).

## Why now

Self-evolving AI work starts **because** a promotion-grade artifact exists —
not before. V1 uses that pack; it does not invent a second research stack.

## V1 success bar (locked)

| ID | Lock |
|---|---|
| A1 | Symbol evidence-card CLI + Analyst/Critic on demo_eligible pack; **proposer → V1.1** |
| A2 | Lesson→Citation + critic HOLD/DEMOTE suggestions; human decides |
| A3 | Offline Properties + one **NVDA** live card + CriticReview artifact; no UI |
| B1–B4 | Packet contracts, `EvidenceCard`/`CriticReview`, numeric allowlist, confidence clamp |
| C1–C4 | Analyst+Critic; Python runner+CLI; litellm+fixture; LLM only under `agents/` |
| D1–D5 | Citation ingest; StrategySpec contract; forbidden classes; Typer+vault mirror; paper callback |
| E1–E4 | Property series; live smoke script; secrets/cost; defer Brier (+ `Thesis.source_card_id`) |
| F1–F3 | `cards/` + `agents/` layout; Phase 3 Docs; vault rearrange done |
| G1–G3 | Cursor prereqs vs Fable cut line; non-goals; merge policy (i) |

## Non-goals (Phase 3 V1)

See solution design §Non-goals and `Docs/NORTH_STAR_DESK.md`. Summarized:

- No LLM StrategySpec proposer, Tutor-as-core, multi-agent debate, LangGraph
- No DuckDB `evidence_cards` in the same PR as the first live card (build #2 later)
- No Brier math; no UI/Streamlit; no PM/Kalshi/Polymarket; no Kronos inference
- No gate-constant or gate-order changes; no universe expansion; no cost-model edits
- No execution language; no fabrication; no confidence above quality cap
- No intraday/tick/options/futures/crypto/margin/leverage; no TradingView.com record surface
- No LLM imports outside `agents/`

## Cursor vs Fable

| Owner | Work |
|---|---|
| **Cursor (this landing)** | Schemas, assemblers, validators, citation CLI, brain Typer, D5 callback, Properties, Docs, fixture LLM stub |
| **Fable** | Real prompts, `litellm.Router` + structured bind, happy-path runner, E2 NVDA live smoke, vault mirror of live card |

## Merge policy

**(i)** Leave a green branch; human opens the PR (matches PR #2 / #3 history).
