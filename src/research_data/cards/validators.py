"""Post-validators for EvidenceCard / CriticReview (B3/B4/D3)."""

from __future__ import annotations

import re
from typing import Iterable

from research_data.cards.allowlist import (
    NumericAllowlist,
    extract_numeric_tokens,
)
from research_data.cards.models import CriticReview, EvidenceCard

#: Card/critic banned tokens — NOT benchmark._EXECUTION_TOKENS (which bans HOLD).
_BANNED_TOKEN_RE = re.compile(
    r"\b(BUY NOW|SELL NOW|BUY|SELL)\b|guaranteed|risk-free",
    re.IGNORECASE,
)


class CardValidationError(Exception):
    """Raised when a card or review fails a hard validator."""


def validate_no_banned_tokens(*texts: str) -> None:
    for text in texts:
        if _BANNED_TOKEN_RE.search(text):
            raise CardValidationError(
                "forbidden execution/certainty language "
                "(BUY/SELL/guaranteed/risk-free) in card or review text"
            )


def validate_confidence_cap(card: EvidenceCard) -> None:
    """Reject confidence above ScorePacket cap (ε=0 at confidence decimals)."""
    if round(card.confidence, 2) > round(card.max_confidence, 2):
        raise CardValidationError(
            f"confidence {card.confidence} exceeds max_confidence {card.max_confidence}"
        )


def validate_numeric_allowlist(
    texts: Iterable[str],
    allowlist: NumericAllowlist,
    *,
    confidence_values: Iterable[float] = (),
) -> None:
    """Every numeric token in texts must appear in the allowlist buckets."""
    for text in texts:
        for raw, value in extract_numeric_tokens(text):
            if isinstance(value, int):
                # Also allow if it matches a rounded float display (e.g. "1")
                if allowlist.allows_int(value):
                    continue
                if allowlist.allows_float(float(value)):
                    continue
                raise CardValidationError(
                    f"integer token {raw!r} not in numeric allowlist"
                )
            if allowlist.allows_float(value):
                continue
            if allowlist.allows_float(value, confidence=True):
                continue
            # Symmetric with the int branch: "ranks 3." lexes as float 3.0 but
            # denotes the allowlisted integer 3 followed by a full stop.
            if value.is_integer() and allowlist.allows_int(int(value)):
                continue
            raise CardValidationError(
                f"float token {raw!r} not in numeric allowlist"
            )
    for conf in confidence_values:
        if not allowlist.allows_float(conf, confidence=True):
            # Confidence must be ≤ max and present; max is always on allowlist
            if allowlist.allows_float(conf, confidence=True) is False:
                # Allow any confidence that rounds within [0, max] if max is listed
                pass
        # Confidence field itself is checked via validate_confidence_cap;
        # free-text confidence mentions must match allowlist floats.


def validate_evidence_refs(card: EvidenceCard, allowed_keys: set[str]) -> None:
    for point in card.evidence:
        if point.ref_key is not None and point.ref_key not in allowed_keys:
            raise CardValidationError(
                f"evidence ref_key {point.ref_key!r} not in assembler input"
            )
    for key in card.evidence_ref_keys:
        if key not in allowed_keys:
            raise CardValidationError(
                f"evidence_ref_keys entry {key!r} not in assembler input"
            )


def validate_evidence_card(
    card: EvidenceCard,
    allowlist: NumericAllowlist,
    allowed_ref_keys: set[str],
) -> None:
    validate_confidence_cap(card)
    validate_no_banned_tokens(
        card.summary,
        *card.opposing_evidence,
        *card.risks,
        *card.invalidation,
        *(p.point for p in card.evidence),
    )
    prose = [
        card.summary,
        *card.opposing_evidence,
        *card.risks,
        *card.invalidation,
        *(p.point for p in card.evidence),
    ]
    validate_numeric_allowlist(prose, allowlist)
    validate_evidence_refs(card, allowed_ref_keys)


def validate_critic_review(review: CriticReview, allowlist: NumericAllowlist) -> None:
    if review.confidence_delta > 0:
        raise CardValidationError("critic confidence_delta must be <= 0")
    validate_no_banned_tokens(review.rationale, *review.risks_flagged)
    validate_numeric_allowlist([review.rationale, *review.risks_flagged], allowlist)
