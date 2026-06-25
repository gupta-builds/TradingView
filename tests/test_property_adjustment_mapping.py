"""Property-based tests for normalizer price adjustment mapping (Property 18).

Property 18: Normalizer Price Adjustment Mapping
For any provider response with a given adjustment_policy, the Normalizer SHALL
map it to the correct PriceAdjustment enum value:
- "raw", "unadjusted" -> PriceAdjustment.RAW
- "split_adjusted", "split" -> PriceAdjustment.SPLIT_ADJUSTED
- "split_dividend_adjusted", "fully_adjusted", "adjusted" -> PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED
- Anything else -> PriceAdjustment.UNKNOWN

The mapping is case-insensitive (the function lowercases input).

**Validates: Requirements 4.2, 4.4**
"""

import sys

sys.path.insert(0, "src")

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from research_data.models import PriceAdjustment
from research_data.normalization import map_adjustment_policy

# ---------------------------------------------------------------------------
# Known policy mappings
# ---------------------------------------------------------------------------

_RAW_POLICIES = ["raw", "unadjusted"]
_SPLIT_POLICIES = ["split_adjusted", "split"]
_SPLIT_DIVIDEND_POLICIES = ["split_dividend_adjusted", "fully_adjusted", "adjusted"]

_ALL_KNOWN_POLICIES = _RAW_POLICIES + _SPLIT_POLICIES + _SPLIT_DIVIDEND_POLICIES

_EXPECTED_MAPPING: dict[str, PriceAdjustment] = {}
for p in _RAW_POLICIES:
    _EXPECTED_MAPPING[p] = PriceAdjustment.RAW
for p in _SPLIT_POLICIES:
    _EXPECTED_MAPPING[p] = PriceAdjustment.SPLIT_ADJUSTED
for p in _SPLIT_DIVIDEND_POLICIES:
    _EXPECTED_MAPPING[p] = PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Strategy for known policies with random casing and surrounding whitespace
_known_policy_strategy = st.sampled_from(_ALL_KNOWN_POLICIES).flatmap(
    lambda policy: st.tuples(
        st.just(policy),
        # Apply random case transformations and optional whitespace
        st.builds(
            lambda chars, leading_ws, trailing_ws: leading_ws + chars + trailing_ws,
            # Randomly uppercase each character
            st.builds(
                lambda p, mask: "".join(
                    c.upper() if m else c.lower() for c, m in zip(p, mask)
                ),
                st.just(policy),
                st.lists(
                    st.booleans(), min_size=len(policy), max_size=len(policy)
                ),
            ),
            st.text(alphabet=" \t", min_size=0, max_size=3),
            st.text(alphabet=" \t", min_size=0, max_size=3),
        ),
    )
)

# Strategy for unknown/random strings that don't match any known policy
_KNOWN_LOWER = set(_ALL_KNOWN_POLICIES)

_unknown_policy_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.lower().strip() not in _KNOWN_LOWER)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestProperty18NormalizerPriceAdjustmentMapping:
    """Property 18: Normalizer Price Adjustment Mapping.

    Use Hypothesis to generate provider responses with various adjustment
    policies and verify correct PriceAdjustment mapping.

    **Validates: Requirements 4.2, 4.4**
    """

    @given(data=_known_policy_strategy)
    @settings(max_examples=200, deadline=None)
    def test_known_policies_map_correctly_regardless_of_case(self, data):
        """For any known policy string with arbitrary casing and whitespace,
        map_adjustment_policy returns the correct PriceAdjustment value."""
        canonical_policy, variant = data
        expected = _EXPECTED_MAPPING[canonical_policy]
        result = map_adjustment_policy(variant)
        assert result == expected, (
            f"Expected {expected} for policy variant '{variant}' "
            f"(canonical: '{canonical_policy}'), got {result}"
        )

    @given(policy=_unknown_policy_strategy)
    @settings(max_examples=200, deadline=None)
    def test_unknown_policies_map_to_unknown(self, policy):
        """For any string that doesn't match a known policy (after lowercasing
        and stripping), map_adjustment_policy returns PriceAdjustment.UNKNOWN."""
        result = map_adjustment_policy(policy)
        assert result == PriceAdjustment.UNKNOWN, (
            f"Expected PriceAdjustment.UNKNOWN for unknown policy '{policy}', "
            f"got {result}"
        )

    @given(policy=st.just(""))
    @settings(max_examples=1, deadline=None)
    def test_empty_string_maps_to_unknown(self, policy):
        """An empty string maps to PriceAdjustment.UNKNOWN."""
        result = map_adjustment_policy(policy)
        assert result == PriceAdjustment.UNKNOWN, (
            f"Expected PriceAdjustment.UNKNOWN for empty policy, got {result}"
        )
