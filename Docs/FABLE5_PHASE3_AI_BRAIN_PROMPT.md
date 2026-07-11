# Fable 5 — Phase 3 AI brain hub (one-shot)

You are Claude Fable 5 implementing the **LLM seam only** for personal research desk `research_data` at `/home/anant_gupta/projects/hub/tradingview`.

**Why:** Cursor landed schemas/validators/CLI/fixture path. You add live structured LLM + NVDA smoke so the desk can emit evidence-bound cards without inventing numbers. Human opens the PR after you leave a green branch.

**Effort:** high. Prefer first-shot correctness. Do not reopen questionnaire locks.

---

## Operating rules (Fable 5)

- When you have enough to act, act. Do not re-litigate locks below or survey options you will not pursue.
- Don't add features, refactors, or abstractions beyond this checklist. Simplest thing that works.
- Pause only for irreversible/destructive actions or input only the user can provide. Otherwise run end-to-end.
- Before claiming progress, audit each claim against a tool result from this session. If tests fail, report the failure with output.
- Do not echo or transcribe internal reasoning into user-facing text; use tool results and final outcome summary only.
- Store durable corrections in `Docs/fable5_run_memory.md` (one lesson per short bullet; no duplicates of repo/chat history).

---

## Read once (in order) — then code

1. `Docs/PHASE3_AI_BRAIN_SOLUTION_DESIGN.md` + `Docs/PHASE3_AI_BRAIN_RUNBOOK.md`
2. Vault SoT if available: `Session Findings — AI Brain Hub (2026-07-12)` (locks); else repo `Docs/SESSION_RECAP_AI_BRAIN_HUB_2026-07-12.md`
3. Existing code: `src/research_data/cards/`, `src/research_data/agents/` — **extend, do not redesign**
4. `Docs/PHASE2B_PROMOTION_STUDY_2026-07-11.md` — NVDA ground truth only

Confirm Gemini Flash **current** litellm model id at implement time (`.env.example` may lag).

---

## Fixed truth (do not invent)

| Item | Value |
|---|---|
| Spec | `quality_momentum_tilt_top3` / `5f003778-42bc-4d8a-ac12-839699d98a02` |
| Decision | `6b46e5fb-1674-45ce-9020-016c46b9e01b` (demo_eligible) |
| Live symbol | **NVDA** |
| Approver | `anant` |
| Actions | `WATCH\|HOLD\|ACCUMULATE\|REDUCE\|AVOID\|INSUFFICIENT_DATA` |
| Float display | `FLOAT_DISPLAY_DECIMALS=4`, confidence decimals=2 |
| Gate critic keys | `oos_net_sharpe`, `mc_p5_return`, `wf_pct_positive`, `deflated_sharpe_probability` |
| Cap | `ScorePacket.data_quality.max_confidence` only |
| `n_trials` | `BrainStore.count_tested_specs()` global — never declare |

---

## Deliverables (exactly these)

1. **`agents/llm_client.py`** — sole place that imports `litellm`. Implement `LiveLLMClient` with `litellm.Router` (Gemini Flash → Groq → Ollama), `DEFAULT_MAX_TOKENS`, fail-fast after `ROUTER_MAX_FAILURES`. Keep `FixtureLLMClient` + `RESEARCH_DATA_LLM=fixture` as CI default. Bind outputs via **instructor or pydantic-ai** to `EvidenceCard` / `CriticReview`. Add deps to `pyproject.toml`.

2. **`agents/analyst.py` + `agents/critic.py`** — replace placeholders with evidence-bound prompts. Analyst: ScorePacket numbers + evidence_refs only. Critic: gate whitelist + may only lower confidence / suggest hold|demote. Banned in prose: BUY, SELL, guaranteed, risk-free (HOLD is legal as ActionLabel).

3. **`agents/runner.py` + CLI** — wire happy path for USABLE packets: FactorEngine → assemble → LLM → validators → `data/cards/`. Keep E1: MISSING/CONTRADICTORY never call LLM. Optional `--vault-mirror` already supported by writer.

4. **`scripts/live_ai_card_smoke.py`** — env-gated (`RESEARCH_DATA_LLM=live`); NVDA card + CriticReview; assert allowlist; inject planted false Sharpe → critic/validator fail; default stdout = pass/fail only. **Not** in default pytest.

5. **Tests** — fixture happy-path unit/property coverage; `pytest -q` must stay green offline. Extend C4 greps if new SDK names appear outside `llm_client.py`.

6. **Docs** — touch `AGENTS.md` current-phase + `Docs/fable5_run_memory.md` with lessons only if you hit real corrections.

`cards/store.py` stays empty. No DuckDB `evidence_cards` table.

---

## Non-goals (hard stop)

No StrategySpec proposer; no Tutor; no LangGraph; no Brier; no UI; no PM/Kalshi; no Kronos inference; no gate-constant or gate-order edits; no universe expansion; no cost-model edits; no auto-promote; no news/sentiment fetch; no multi-agent debate; no LLM imports outside `agents/`; no raw OHLCV dumps to the model.

---

## DoD

```bash
source .venv/bin/activate
pytest -q                                          # must pass, fixture mode
RESEARCH_DATA_LLM=live python scripts/live_ai_card_smoke.py --db data/market.duckdb --symbol NVDA
# → NVDA EvidenceCard + CriticReview under data/cards/; planted-Sharpe path fails closed
```

Leave **green branch**. Do **not** open or merge the PR (policy i — human will).

Final user message: one sentence outcome, then paths changed, then exact commands you ran and their results.
