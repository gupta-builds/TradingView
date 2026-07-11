# Phase 3 — Solution design: AI brain hub

> Locks the questionnaire (A1–G3). Implement against this file + vault
> `Session Findings — AI Brain Hub (2026-07-12)`.

## Module map (add to YEAR_AHEAD_BASE)

```text
src/research_data/
  cards/                 # no LLM imports
    models.py            # EvidenceCard, CriticReview (schema_version)
    gate_projection.py   # TestRunRecord → whitelist floats
    allowlist.py         # FLOAT_DISPLAY_DECIMALS=4, CONFIDENCE=2
    validators.py        # numbers, confidence cap, banned tokens (no HOLD ban)
    writer.py            # data/cards/*.json + one-way vault markdown
    store.py             # RESERVED empty — DuckDB build #2 later
  agents/                # sole LLM boundary (C4)
    llm_client.py        # fixture now; Fable: litellm.Router only here
    assemble.py          # ScorePacket numbers + evidence_refs only
    runner.py            # assemble → validate → write; block LLM on MISSING/CONTRADICTORY
    analyst.py / critic.py  # prompt placeholders → Fable
  brain/citations.py     # cite-add / vault / journal (deterministic)
  cli_desk.py            # Typer: propose/approve/reject/decide/cite-*/analyze/critique
  paper/                 # Thesis.source_card_id; PaperEngine.on_lesson_journaled
```

## Data flow

```text
ScorePacket (+ evidence_refs from DataEvidencePacket)
  → assemble (block LLM if MISSING|CONTRADICTORY → deterministic INSUFFICIENT_DATA card)
  → [Fable] structured LLM → EvidenceCard
  → NumericAllowlist + confidence clamp validators
  → data/cards/{symbol}_{as_of}_{card_id}.json
  → optional one-way vault markdown (DB wins)

Gate batch → GateSummaryProjection (oos_net_sharpe, mc_p5_return,
  wf_pct_positive, deflated_sharpe_probability)
  → CriticReview (confidence_delta ≤ 0; hold/demote suggestion)
  → human `decide` via BrainStore.record_decision / loop helper
```

## Packet rules (B1)

- Numbers: **ScorePacket only**
- Provenance refs: **DataEvidencePacket.evidence_refs only** (do not dual-serialize quality blocks)
- Critic gates: **whitelist projection only** (not raw inputs/outputs)
- Kronos: never attached

## Allowlist (B3)

- Floats: round both sides to `FLOAT_DISPLAY_DECIMALS` (4) then exact compare
- Confidence: `CONFIDENCE_DISPLAY_DECIMALS` (2)
- Ints: exact
- ε pinned in `tests/test_property_ai_hub_cards.py` (Property 20)

## StrategySpec propose contract (D2)

- Non-empty claims on cited citations at propose-time
- `resolve_hook` at propose-time
- `params` fully merged; `params_delta` + `parent_spec_id` provenance only
- `n_trials` = global `count_tested_specs()` only — **no** `declared_n_trials`

## Citation ingest (D1)

- Stable vault id = `hash(vault_relpath + content_hash(claims_section))` — no mtime
- Insert-only store → content change = new row (old citations immutable)
- Empty claims OK at ingest; required non-empty at PROPOSED/decision use
- Journal: `PaperEngine._journal` → injected `on_lesson_journaled` (default on for real runs)

## Eval

- Offline: Properties 20–22 (+ structural C4/D3 tests); zero LLM on blocked quality
- Live: `scripts/live_ai_card_smoke.py` (Fable) — NVDA; not default pytest

## Non-goals

Full list in problem statement. North-star deferrals in `Docs/NORTH_STAR_DESK.md`.
