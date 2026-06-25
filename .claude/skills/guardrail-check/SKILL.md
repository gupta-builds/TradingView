---
name: guardrail-check
description: Grep the working tree (or a diff) for violations of this project's non-negotiable safety rules — execution language, forbidden action labels, secrets, banned dependencies, and out-of-scope asset classes — operationalizing .kiro task 13 (scope boundary enforcement).
---

# guardrail-check

Mechanical sweep for the hard rules in `design.md` ("Guardrails to Preserve", "Non-Goals") and `CLAUDE.md`. This is grep-based triage, not judgment — hand anything found to the `guardrail-auditor` agent (or the user) for a real review; don't silently fix or dismiss matches.

## Checks to run

1. **Execution / certainty language** in source, docstrings, CLI strings, fixtures, and Docs:
   `grep -rniE "\b(buy now|sell now|guaranteed|risk-free|can't lose)\b" src/ tests/ Docs/ README.md CLAUDE.md 2>/dev/null`
   Also check bare `\bBUY\b|\bSELL\b` outside of test names/comments discussing the *rule itself*.
2. **Forbidden action labels** — any string literal that looks like an action/recommendation field should be one of `WATCH HOLD ACCUMULATE REDUCE AVOID INSUFFICIENT_DATA`. Grep for quoted action-like strings and check against this list.
3. **Secrets** — `grep -rniE "(api[_-]?key|secret|token|password)\s*=\s*['\"][A-Za-z0-9]" src/ tests/ config/` and confirm no real-looking key material; confirm `.env` is listed in `.gitignore` and `git check-ignore .env` succeeds.
4. **Banned dependencies** — check `pyproject.toml` / any `requirements*.txt` for broker/order-routing SDKs (e.g. `alpaca-trade-api`, `ib_insync`, `ccxt`) or options/futures/crypto-specific packages. None should be present in this phase.
5. **Out-of-scope asset/venue paths** — grep for `intraday`, `tick`, `options`, `futures`, `crypto`, `margin`, `leverage`, `scrape` (case-insensitive) across `src/` and flag any hit for human review (some may be legitimate comments about what's excluded — read context before flagging).
6. **LLM calls in the ingestion path** — grep `src/research_data/{models,config,storage,normalization,calendar,quality,read_api}.py` (and `cli.py`/`evidence.py`/`benchmark.py` once they exist) for `openai`, `anthropic`, `requests.post.*chat`, or similar — none should appear.

Report every match with file:line and a one-line verdict (real violation / false positive with reason). End with a pass/fail summary.
