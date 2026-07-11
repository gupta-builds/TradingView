"""Numeric allowlist for evidence cards (B3).

Display precision and allowlist matching are the **same** decision:

- Performance floats (returns, Sharpe, vol, gate whitelist): round to
  ``FLOAT_DISPLAY_DECIMALS`` (4) then compare exactly — matches gate note
  formatting (``.4f``) without requiring raw ScorePacket bit-identity.
- Confidence: ``CONFIDENCE_DISPLAY_DECIMALS`` (2), same as CLI confidence_cap.
- Structural ints (rank, universe_size, …): exact match, no tolerance.

Pinned in golden/property tests — do not drift these constants silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from research_data.cards.gate_projection import GateSummaryProjection
from research_data.factors.packets import ScorePacket

#: Card text + allowlist precision for returns / Sharpe / vol / gate floats.
FLOAT_DISPLAY_DECIMALS = 4

#: Confidence and max_confidence display/match precision.
CONFIDENCE_DISPLAY_DECIMALS = 2

_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?(?:\d+\.\d+|\d+\.|\.\d+|\d+)(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])"
)


@dataclass
class NumericAllowlist:
    """Two typed buckets: floats (rounded) and ints (exact)."""

    floats: set[float] = field(default_factory=set)  # already rounded
    ints: set[int] = field(default_factory=set)
    float_decimals: int = FLOAT_DISPLAY_DECIMALS
    confidence_decimals: int = CONFIDENCE_DISPLAY_DECIMALS

    def add_float(self, value: float | None, *, confidence: bool = False) -> None:
        if value is None:
            return
        decimals = self.confidence_decimals if confidence else self.float_decimals
        self.floats.add(round(float(value), decimals))

    def add_int(self, value: int | None) -> None:
        if value is None:
            return
        self.ints.add(int(value))

    def allows_float(self, value: float, *, confidence: bool = False) -> bool:
        decimals = self.confidence_decimals if confidence else self.float_decimals
        return round(float(value), decimals) in self.floats

    def allows_int(self, value: int) -> bool:
        return int(value) in self.ints


def build_allowlist_from_score_packet(packet: ScorePacket) -> NumericAllowlist:
    """Collect every number the analyst may quote from a ScorePacket."""
    al = NumericAllowlist()
    al.add_float(packet.data_quality.max_confidence, confidence=True)

    m = packet.momentum_score
    al.add_int(m.rank)
    al.add_int(m.universe_size)
    al.add_int(m.ranked_count)
    al.add_float(m.twelve_minus_one_return)

    s = packet.safety_score
    al.add_int(s.rank)
    al.add_int(s.universe_size)
    al.add_int(s.ranked_count)
    al.add_float(s.realized_vol_annualized)

    q = packet.quality_fcf_score
    al.add_int(q.universe_size)
    al.add_int(q.ranked_count)
    al.add_float(q.value)
    c = q.components
    al.add_float(c.fcf_ev)
    al.add_float(c.fcf_margin)
    al.add_float(c.op_margin_stability)
    al.add_float(c.debt_to_equity)
    al.add_float(c.enterprise_value)
    al.add_float(c.market_cap)

    v = packet.valuation
    al.add_float(v.fcf_ev)
    al.add_float(v.p_fcf)

    for w in packet.etf_baseline.windows:
        al.add_int(w.window_sessions)
        al.add_int(w.overlapping_sessions)
        al.add_float(w.symbol_return)
        al.add_float(w.benchmark_return)

    ta = packet.ta_context
    al.add_float(ta.sma_50)
    al.add_float(ta.sma_200)
    al.add_float(ta.rsi_14)
    al.add_float(ta.bollinger_position)
    al.add_float(ta.drawdown_from_52w_high)

    al.add_int(packet.data_quality.price_rows_used)
    return al


def build_allowlist_from_gate_summary(summary: GateSummaryProjection) -> NumericAllowlist:
    al = NumericAllowlist()
    al.add_float(summary.oos_net_sharpe)
    al.add_float(summary.mc_p5_return)
    al.add_float(summary.wf_pct_positive)
    al.add_float(summary.deflated_sharpe_probability)
    return al


def merge_allowlists(*lists: NumericAllowlist) -> NumericAllowlist:
    out = NumericAllowlist()
    for al in lists:
        out.floats |= al.floats
        out.ints |= al.ints
    return out


def extract_numeric_tokens(text: str) -> list[tuple[str, float | int]]:
    """Parse numeric tokens from free text; ints vs floats by lexical form."""
    found: list[tuple[str, float | int]] = []
    for m in _NUMBER_RE.finditer(text):
        raw = m.group(0)
        if any(ch in raw for ch in ".eE"):
            found.append((raw, float(raw)))
        else:
            found.append((raw, int(raw)))
    return found
