"""Critic prompts — gate-whitelist review, monotone confidence pressure (B1/B4).

The critic sees only the four-key GateSummaryProjection (never raw gate
inputs/outputs) plus the card under review. It may only lower confidence
(``confidence_delta <= 0``) and may only suggest hold / demote / ok /
insufficient_data. Banned words below are quoted as forbidden tokens
(enforcement text, benchmark.py precedent).
"""

from __future__ import annotations

import json

from research_data.agents.assemble import AnalystInputBundle
from research_data.cards.allowlist import build_allowlist_from_gate_summary
from research_data.cards.models import EvidenceCard
from research_data.cards.writer import format_card_float

CRITIC_SYSTEM_PROMPT = """\
You are the skeptical critic on a personal market research desk. You review one
strategy's promotion evidence (a fixed four-number gate summary) and optionally
the analyst's EvidenceCard, and you push back. You are not an adviser; the words
"BUY", "SELL", "guaranteed" and "risk-free" are forbidden anywhere in your text.

Hard rules — a validator rejects your review if any is broken:
1. suggestion must be exactly one of: hold, demote, ok, insufficient_data.
   You have no authority to promote, approve, or raise confidence.
2. confidence_delta must be zero or negative. Zero means "no objection";
   negative means the card's confidence should come down by that amount.
3. Numbers: you may only quote the gate numbers listed in QUOTABLE_NUMBERS,
   copied exactly as written (including sign). No other digits in prose —
   no dates, ids, counts, thresholds, or derived figures. If a gate value is
   missing, say so in words.
4. Only the four whitelisted gate metrics exist for you: oos_net_sharpe,
   mc_p5_return, wf_pct_positive, deflated_sharpe_probability. Never reference
   or invent any other metric value.
5. If a quoted metric looks inconsistent with the whitelist you were given,
   set rejected=true and explain in reject_reasons (words only, no digits).
6. rationale must be substantive: name overfitting, regime, and sample-size
   caveats where honest, grounded in the given numbers.
"""


def build_critic_user_prompt(
    bundle: AnalystInputBundle,
    card: EvidenceCard | None = None,
) -> str:
    """The critic's entire evidence view: whitelist projection (+ card prose)."""
    if bundle.gate_summary is None:
        raise ValueError("critic prompt requires a GateSummaryProjection on the bundle")
    allowlist = build_allowlist_from_gate_summary(bundle.gate_summary)
    quotable = [format_card_float(v) for v in sorted(allowlist.floats)]
    parts = [
        f"Symbol under review: {bundle.symbol}",
        f"spec_id (structured field only — never write it in prose): {bundle.spec_id}",
        "",
        "GATE_SUMMARY_PROJECTION (whitelist — the only gate facts that exist):",
        json.dumps(bundle.gate_summary.model_dump(mode="json"), indent=2),
        "",
        "QUOTABLE_NUMBERS (the only numbers you may write in prose):",
        *(f"  {q}" for q in quotable),
    ]
    if bundle.promotion_decision is not None:
        parts += [
            "",
            f"Recorded human decision: {bundle.promotion_decision.decision.value} "
            f"→ {bundle.promotion_decision.to_state.value} (ids are structured "
            "fields; never write them in prose).",
        ]
    if card is not None:
        parts += [
            "",
            "ANALYST CARD UNDER REVIEW (summary and action only):",
            f"action={card.action.value} "
            f"confidence={format_card_float(card.confidence, confidence=True)}",
            card.summary,
        ]
    parts += [
        "",
        "Write the CriticReview now. Set card_id/spec_id structured fields from "
        "the values above; keep every digit out of prose except QUOTABLE_NUMBERS.",
    ]
    return "\n".join(parts)
