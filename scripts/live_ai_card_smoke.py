"""Live AI card smoke (E2) — env-gated, never part of default pytest.

Run:
    RESEARCH_DATA_LLM=live python scripts/live_ai_card_smoke.py \
        --db data/market.duckdb --symbol NVDA

Produces one live EvidenceCard and one CriticReview under data/cards/, then
proves the planted-false-Sharpe path fails closed. Default stdout is
pass/fail lines only — no prompt or payload dumps.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DEFAULT_SPEC_ID = "5f003778-42bc-4d8a-ac12-839699d98a02"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/market.duckdb")
    parser.add_argument("--symbol", default="NVDA")
    parser.add_argument("--spec-id", default=DEFAULT_SPEC_ID)
    parser.add_argument("--price-source", default="tiingo")
    parser.add_argument("--cards-dir", default=str(PROJECT_ROOT / "data" / "cards"))
    parser.add_argument(
        "--vault-mirror",
        default=None,
        help="Optional path for one-way DB→markdown mirror of the live card "
        "(default: data/cards/NVDA_live_mirror.md under --cards-dir)",
    )
    args = parser.parse_args()

    from research_data.cli import load_dotenv_if_present

    load_dotenv_if_present(PROJECT_ROOT)

    if os.environ.get("RESEARCH_DATA_LLM", "").strip().lower() != "live":
        print("FAIL: RESEARCH_DATA_LLM=live is required (env-gated smoke)")
        return 2

    import duckdb

    from research_data.brain.loop import latest_gate_batch
    from research_data.brain.store import BrainStore
    from research_data.cards.allowlist import build_allowlist_from_gate_summary
    from research_data.cards.models import CriticReview
    from research_data.cards.validators import (
        CardValidationError,
        validate_critic_review,
    )
    from research_data.cli_desk import build_happy_path_bundle
    from research_data.agents.runner import run_analyze_symbol, run_critique_spec
    from research_data.models import QualityStatus
    from research_data.paper.models import ActionLabel

    symbol = args.symbol.upper()
    failures: list[str] = []

    conn = duckdb.connect(args.db, read_only=False)
    try:
        store = BrainStore(conn)
        store.init_schema()
        spec = store.get_spec(args.spec_id)
        gate_runs = latest_gate_batch(store, args.spec_id)
        decisions = store.list_decisions(args.spec_id)
        decision = decisions[-1] if decisions else None

        as_of = conn.execute(
            "SELECT max(trading_date) FROM daily_ohlcv WHERE symbol = ? AND source = ?",
            [symbol, args.price_source],
        ).fetchone()[0]
        if as_of is None:
            print(f"FAIL: no {args.price_source} rows for {symbol} in {args.db}")
            return 1

        bundle = build_happy_path_bundle(
            conn,
            symbol=symbol,
            as_of=as_of,
            price_source=args.price_source,
            spec_id=spec.spec_id,
            gate_runs=gate_runs,
            promotion_decision=decision,
        )
        if bundle.score_packet.data_quality.status in (
            QualityStatus.MISSING,
            QualityStatus.CONTRADICTORY,
        ):
            print("FAIL: packet quality blocks LLM; smoke needs usable data")
            return 1

        from research_data.agents.llm_client import LLMClientError
        from research_data.agents.runner import RunnerError

        # 1) Live analyst card — validators (allowlist, cap, refs, tokens) run inside.
        card = None
        mirror_path = args.vault_mirror
        if mirror_path is None:
            mirror_path = str(Path(args.cards_dir) / f"{symbol}_live_mirror.md")
        try:
            card = run_analyze_symbol(
                bundle,
                cards_dir=args.cards_dir,
                vault_mirror_path=mirror_path,
            )
            assert isinstance(card.action, ActionLabel)
            if round(card.confidence, 2) > round(card.max_confidence, 2):
                raise CardValidationError("card confidence exceeds cap")
            print(
                f"PASS: live EvidenceCard ({symbol} action={card.action.value} "
                f"card_id={card.card_id})"
            )
            print(f"PASS: vault mirror written ({mirror_path})")
        except (CardValidationError, RunnerError, LLMClientError) as e:
            failures.append(f"analyst card: {e}")
            print(f"FAIL: analyst card: {e}")

        # 2) Live critic review on the true gate whitelist.
        try:
            review = run_critique_spec(bundle, card, cards_dir=args.cards_dir)
            if review.confidence_delta > 0:
                raise CardValidationError("critic raised confidence")
            print(
                f"PASS: live CriticReview (suggestion={review.suggestion} "
                f"delta={review.confidence_delta})"
            )
        except (CardValidationError, RunnerError, LLMClientError) as e:
            failures.append(f"critic review: {e}")
            print(f"FAIL: critic review: {e}")

        # 3) Planted false Sharpe must fail closed: a review quoting a number
        #    absent from the true whitelist is rejected by the validator layer
        #    no matter what any model says.
        assert bundle.gate_summary is not None
        true_allowlist = build_allowlist_from_gate_summary(bundle.gate_summary)
        planted = CriticReview(
            spec_id=spec.spec_id,
            suggestion="ok",
            confidence_delta=0.0,
            rationale="Out-of-sample net Sharpe of 9.4321 clears every bar.",
        )
        try:
            validate_critic_review(planted, true_allowlist)
            failures.append("planted false Sharpe was NOT rejected")
            print("FAIL: planted false Sharpe was NOT rejected")
        except CardValidationError:
            print("PASS: planted false Sharpe rejected (fail closed)")
    finally:
        conn.close()

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: live AI card smoke complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
