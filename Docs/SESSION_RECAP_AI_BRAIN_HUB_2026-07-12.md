---
type: session-recap
status: active
created: 2026-07-12
updated: 2026-07-12
related_progress:
  - "[[Session Findings — AI Brain Hub (2026-07-12)]]"
  - "[[Session Findings — Post Base (2026-07-11)]]"
  - "[[Fable 5 — Read Order (TradingView folder)]]"
tags:
  - trading
  - session
  - ai-brain
  - questionnaire
track:
  - trading
  - ai
next: "Paste Docs/FABLE5_PHASE3_AI_BRAIN_PROMPT.md into Fable 5; human opens PR after green branch"
---

# Session Recap — AI Brain Hub Design → Cursor Prereqs → Fable Prompt (2026-07-12)

==Full questionnaire transcript + verification. Decision SoT remains [[Session Findings — AI Brain Hub (2026-07-12)]]. This note is the narrative audit trail.==

## What this session was

Cursor (Ask → Agent) ran a **design questionnaire** then **implemented Cursor-owned prereqs** for the personal US stocks/ETFs research desk (`research_data` in `tradingview/`). Goal: unlock a **one-shot Fable 5** build of the LLM analyst/critic seam on top of `quality_momentum_tilt_top3` (**demo_eligible**, tiingo N=1511, PR #3).

Verified on machine before prompt rewrite:
- `pytest -q` → **483 passed** (~7 min)
- `python -m research_data.cli analyze-symbol NVDA --quality missing` → `action=INSUFFICIENT_DATA confidence=0.0`
- D5 study-script wiring + citation/projection tests added after audit (`tests/test_citations_and_projection.py` green)

## North star vs V1 (scope correction)

User clarified early: fuller vision (self-improving brain + sibling PM app + polished UI) is **north star**, not V1. Captured in repo `Docs/NORTH_STAR_DESK.md`. V1 = AI hub only. PM/Kalshi parked per postmortem until stocks/ETFs paper is real-use ready. No UI.

## Questionnaire — questions, options lean, answers

### Block A — Scope

| Q | Asked | Recommended | **Answer** |
|---|---|---|---|
| **A1** | V1 AI hub: (A) symbol card CLI only (B) analyst+critic on demo_eligible only (C) full proposer (D) A+B (E) A+B+C | D | **D** — card CLI + Analyst/Critic on pack; proposer → V1.1; no PM; no UI |
| **A2** | Self-improve close: (A) lesson→Citation only (B) LLM proposer (C) auto-approve tweaks (D) critic demotion only (E) A+D | E | **E (A+D)** — Citations + critic HOLD/DEMOTE; no LLM proposer; `anant` decides |
| **A3** | Desk bar: (A) offline only (B) one live holding (C) full watchlist (D) A+B+critic artifact (E) UI | D | **D** — offline Properties + live card + CriticReview; later locked symbol **NVDA** |

### Block B — Packets

| Q | Asked | Recommended | **Answer** |
|---|---|---|---|
| **B1** | Packet set for LLM | D | **D** + amendments: numbers from **ScorePacket only**; DataEvidencePacket = **evidence_refs only** (no dual quality blocks); critic gets **GateSummaryProjection** whitelist (`oos_net_sharpe`, `mc_p5_return`, `wf_pct_positive`, `deflated_sharpe_probability`) mapped from live keys; + PromotionDecision + JournalEntry; Kronos forbidden |
| **B2** | EvidenceCard storage | B | **B** — Pydantic in `cards/models.py`, `data/cards/{symbol}_{as_of}_{card_id}.json`; CriticReview separate; DuckDB table = **build #2** after live card stable |
| **B3** | Number invention tripwire | D | **D** — allowlist + critic; **tolerance buckets**: floats round to display precision then match; ints exact; ε pinned in Properties |
| **B4** | Confidence capping | D | **D** — cap = `ScorePacket.data_quality.max_confidence`; critic `confidence_delta ≤ 0`; final = min(analyst, critic-adjusted, cap) |

**B3 pin later:** `FLOAT_DISPLAY_DECIMALS=4`, `CONFIDENCE_DISPLAY_DECIMALS=2` in `cards/allowlist.py`.

### Block C — Topology

| Q | Asked | Recommended | **Answer** |
|---|---|---|---|
| **C1** | Roles | B | **B** Analyst+Critic. TradingAgents Trader/PM = LLM approve → forbidden by `validate_human_identity`. Tutor + research-proposer swarm deferred (not topology) |
| **C2** | Orchestration | E | **E** Python runner + Typer; **no LangGraph**; path `agents/runner.py`; instructor/pydantic-ai + litellm; fixture like csv_fixture |
| **C3** | Provider | E | **E** litellm pluggable; live default **Gemini Flash**; alt **Groq**; GitHub Models excluded (retires 2026-07-30); Azure reserve; free-tier training disclaimer in `.env.example` |
| **C4** | When LLM may run | E | **E** LLM only under `agents/`; sole litellm import = `llm_client.py`; Router fallback Gemini→Groq→Ollama (robustness, not daemon) |

### Block D — Citations / human gate

| Q | Asked | Recommended | **Answer** |
|---|---|---|---|
| **D1** | Citation ingest | E | **E** cite-add + vault + journal; LLM claims deferred. Stable id = `hash(path+claims_content)` not mtime; insert-only; empty claims OK at ingest, required at PROPOSED use; warn on title/author dup |
| **D2** | StrategySpec contract | D | **D** tightened: global `count_tested_specs()` only; **no** `declared_n_trials`; `params_delta`/`parent_spec_id` provenance; `params` fully merged; `resolve_hook` at **propose-time** |
| **D3** | Forbidden classes | D | **D** + structural tests (gate params defaults outside tests/; hooks never read universe/cost from params; no kronos under agents/). Card banned tokens = BUY/SELL/guaranteed/risk-free (**not** HOLD) |
| **D4** | Human UX | D | **D** Typer on `cli.py` (via `cli_desk.py`): propose/approve/reject/decide + analyze/critique; one-way **DB→vault** mirror in V1 |
| **D5** | Lesson→next | D | **D** callback on `PaperEngine._journal` for lesson/exit; CLI/study supplies closure; default cite on; `--no-cite-lesson` for synthetic only |

### Block E — Eval / cost

| Q | Asked | Recommended | **Answer** |
|---|---|---|---|
| **E1** | Offline eval | D | **D** as Property series; hypothesis ε boundary; **zero LLM** on MISSING/CONTRADICTORY; citation hallucination like kronos tests |
| **E2** | Live eval | C | **C** live smoke + planted false Sharpe; not in pytest; symbol **NVDA** |
| **E3** | Secrets/cost | C | **C** `.env` keys; no raw bars to model; max_tokens + Router fail-fast; pass/fail verbosity |
| **E4** | Calibration | C | **C** + `Thesis.source_card_id`; no Brier yet; north-star must say Brier needs named binary event |

### Block F — Structure

| Q | Asked | Recommended | **Answer** |
|---|---|---|---|
| **F1** | Code home | C | **C** `cards/` five files + empty store; `agents/` with assemble split; small edits to brain/paper models |
| **F2** | Docs | D | **D** PHASE3 problem/solution/runbook + NORTH_STAR_DESK |
| **F3** | Vault rearrange | (custom) | **Executed:** Canon / Session Findings / Phases / Research / Archive; moves only; Read Order → this SoT |

### Block G — Cursor vs Fable

| Q | Asked | Recommended | **Answer** |
|---|---|---|---|
| **G1** | Cursor before Fable | D | **D** full prereq pack; brain Typer **complete**; analyze/critique partial until LLM; pin ε |
| **G2** | Fable cut line | C | **C** LLM+prompts+happy path+NVDA smoke+CriticReview+vault mirror; no proposer/DuckDB cards/Tutor |
| **G3** | Non-goals + merge | C + (i) | **C** expanded (execution language, fabrication, intraday/etc, LLM outside agents, no TV.com surface, gate **order**, cost-model bullet) + merge **(i)** human opens PR |

## Repo artifacts Cursor shipped

| Area | Paths |
|---|---|
| Cards | `src/research_data/cards/{models,gate_projection,allowlist,validators,writer,store}.py` |
| Agents | `src/research_data/agents/{llm_client,assemble,runner,analyst,critic}.py` |
| Brain/paper | `citations.py`; D2 fields; `source_card_id`; `on_lesson_journaled`; study `--no-cite-lesson` |
| CLI | `cli_desk.py` registered on Typer app |
| Tests | `test_property_ai_hub_cards.py`, `test_ai_hub_security.py`, `test_citations_and_projection.py` |
| Docs | `PHASE3_AI_BRAIN_*.md`, `NORTH_STAR_DESK.md`, `FABLE5_PHASE3_AI_BRAIN_PROMPT.md`, YEAR_AHEAD/AGENTS patches |
| Env | `.env.example` LLM stubs |

## Fable owns (do not do in Cursor)

`litellm.Router` + instructor/pydantic-ai in `llm_client.py` only; real prompts; FactorEngine happy-path analyze; `scripts/live_ai_card_smoke.py`; leave green branch for human PR.

## Anti-patterns rejected this session

Student-toy knowledge dump; LangGraph; TradingAgents approve topology; declared_n_trials; mtime citation ids; dual quality serialization; benchmark HOLD ban on cards; auto-promote; UI-as-desk-is-real.
