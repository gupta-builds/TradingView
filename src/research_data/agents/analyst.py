"""Analyst prompts — evidence-bound EvidenceCard generation (B1/B3/B4).

The analyst sees ScorePacket numbers and evidence_refs only. Every numeric
token it emits in prose must survive ``validate_numeric_allowlist``, so the
user prompt hands the model the exact quotable representations up front.
The words banned below are quoted as *forbidden* tokens (enforcement text,
same precedent as benchmark.py) — they are never emitted by this desk.
"""

from __future__ import annotations

import json

from research_data.agents.assemble import AnalystInputBundle, score_packet_to_analyst_dict
from research_data.cards.allowlist import (
    NumericAllowlist,
    build_allowlist_from_score_packet,
)
from research_data.cards.writer import format_card_float

ANALYST_SYSTEM_PROMPT = """\
You are the analyst on a personal, beginner-safe market research desk. You write
one EvidenceCard summarizing the factor evidence for one symbol. You are not a
financial adviser and this is not investment advice; it is a research summary of
precomputed numbers.

Hard rules — a validator rejects your card if any is broken:
1. action must be exactly one of: WATCH, HOLD, ACCUMULATE, REDUCE, AVOID,
   INSUFFICIENT_DATA. No other action words. In particular the words "BUY",
   "SELL", "guaranteed" and "risk-free" are forbidden anywhere in your text.
2. Numbers: you may only quote numbers that appear in the QUOTABLE_NUMBERS list,
   copied exactly as written there (including the sign). Do NOT write any other
   digits anywhere in prose — no dates, no years, no window lengths, no counts,
   no percentages you compute yourself. Write things like "the twelve-minus-one
   momentum window" or "about a year of sessions" in words instead. Indicator
   names carry digits too — write "the fourteen-day RSI", "the fifty-day moving
   average", "the two-hundred-day moving average", never RSI-14 / SMA 50 / 200.
3. Never invent, recompute, derive, or extrapolate a metric. If a score has
   status "insufficient_data", say the input is unavailable — never guess it.
4. confidence must be less than or equal to the stated max_confidence cap.
5. evidence[].ref_key and evidence_ref_keys may only use keys from
   ALLOWED_EVIDENCE_REF_KEYS. If the list is empty, leave them empty/null.
6. Fill symbol, as_of, data_quality_status and max_confidence exactly as given
   in the user message. Leave next_review_date null. Structured date fields may
   hold dates; prose may not.
7. Be balanced: populate opposing_evidence, risks and invalidation with real
   content grounded in the packet (risk_flags, data-quality notes, valuation
   caveats), not boilerplate.
"""


def render_quotable_numbers(allowlist: NumericAllowlist) -> str:
    """Exact quotable representations — floats at display precision, ints raw."""
    floats = sorted(allowlist.floats)
    ints = sorted(allowlist.ints)
    lines = ["Floats (copy exactly, including sign):"]
    lines += [f"  {format_card_float(v)}" for v in floats]
    lines.append("Integers:")
    lines += [f"  {v}" for v in ints]
    return "\n".join(lines)


def build_analyst_user_prompt(bundle: AnalystInputBundle) -> str:
    """Assemble the analyst's entire evidence view — nothing else reaches it."""
    allowlist = build_allowlist_from_score_packet(bundle.score_packet)
    packet_json = score_packet_to_analyst_dict(bundle.score_packet)
    ref_keys = sorted(bundle.evidence_ref_keys)
    cap = bundle.score_packet.data_quality.max_confidence
    return (
        f"Symbol: {bundle.symbol}\n"
        f"as_of (copy into the as_of field): {bundle.as_of.isoformat()}\n"
        f"data_quality_status (copy exactly): {bundle.score_packet.data_quality.status.value}\n"
        f"max_confidence cap (copy exactly; confidence must not exceed it): "
        f"{format_card_float(cap, confidence=True)}\n\n"
        "SCORE_PACKET (the only source of facts; statuses of 'insufficient_data' "
        "mean that factor is unknown):\n"
        f"{json.dumps(packet_json, indent=2)}\n\n"
        "QUOTABLE_NUMBERS (the only numbers you may write in prose):\n"
        f"{render_quotable_numbers(allowlist)}\n\n"
        "ALLOWED_EVIDENCE_REF_KEYS (the only legal ref_key values):\n"
        f"{json.dumps(ref_keys)}\n\n"
        "Write the EvidenceCard now. Remember: no digits in prose except "
        "QUOTABLE_NUMBERS copied verbatim; never write ids or dates in prose."
    )
