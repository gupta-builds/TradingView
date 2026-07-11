#!/usr/bin/env python
"""MANUAL/LIVE study runner: quality+momentum pack against a real DuckDB file.

Runs the production hook over whatever history the local database already
holds, pushes the result through the four-gate harness at UNCHANGED literature
defaults, records every executed gate in the brain, and (unless skipped)
writes a paper replay journal artifact under the standard paper rules.

This script performs NO network calls and NO ingestion — if the database has
no usable rows it says so and exits. On free-tier history depth (~400
sessions) the walk-forward gate is expected to fail closed; that failure is
recorded honestly, and the spec simply stays not demo-eligible.

Usage:
    source .venv/bin/activate
    python scripts/run_quality_momentum_study.py                # data/market.duckdb
    python scripts/run_quality_momentum_study.py --db path.duckdb
    python scripts/run_quality_momentum_study.py --record-decision --approver anant
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from research_data.brain import (
    BrainStore,
    Citation,
    SpecStatus,
    StrategySpec,
    is_demo_eligible,
    record_gate_outcome_decision,
    resolve_hook,
)
from research_data.config import load_config
from research_data.fundamentals.store import FundamentalsStore
from research_data.gates import GateHarness
from research_data.gates.metrics import (
    DEFAULT_COST_BPS_PER_SIDE,
    summarize,
    total_return,
)
from research_data.paper import ActionLabel, PaperEngine, PaperStore, ReplayRun, Thesis
from research_data.read_api import PriceReadAPI
from research_data.strategies.quality_momentum import (
    StrategyDataError,
    run_quality_momentum_study,
)

HOOK_REF = "research_data.strategies.quality_momentum:quality_momentum_tilt_hook"
SPEC_NAME = "quality_momentum_tilt_top3"
SPEC_PARAMS = {"top_k": 3}

CITATIONS = [
    dict(
        source_type="paper",
        title="Returns to Buying Winners and Selling Losers (Jegadeesh-Titman 1993)",
        url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=227214",
        claims=["12-1 month cross-sectional momentum persists out of sample"],
    ),
    dict(
        source_type="paper",
        title="The Other Side of Value: The Gross Profitability Premium (Novy-Marx 2013)",
        url="https://doi.org/10.1016/j.jfineco.2013.01.003",
        claims=["Profitable, cash-generative firms earn a cross-sectional premium"],
    ),
]


def fail(message: str) -> None:
    print(f"STUDY ABORTED: {message}")
    sys.exit(1)


def load_fundamentals(store: FundamentalsStore, symbols: list[str]) -> dict:
    """One source per symbol (most snapshots wins; FMP preferred on ties) so
    quarterly margin history is not double-counted across providers."""
    snapshots_by_symbol = {}
    for symbol in symbols:
        all_snapshots = store.get_snapshots(symbol)
        if not all_snapshots:
            continue
        by_source: dict[str, list] = {}
        for snapshot in all_snapshots:
            by_source.setdefault(snapshot.source, []).append(snapshot)
        best = max(
            by_source, key=lambda s: (len(by_source[s]), 1 if s == "fmp" else 0)
        )
        snapshots_by_symbol[symbol] = by_source[best]
    return snapshots_by_symbol


def get_or_register_spec(brain: BrainStore, approver: str) -> StrategySpec:
    """Reuse the approved study spec if present; otherwise register it
    (citations → proposed → human-approved)."""
    for spec in brain.list_specs():
        if (
            spec.name == SPEC_NAME
            and spec.hook_ref == HOOK_REF
            and spec.params == SPEC_PARAMS
            and spec.status == SpecStatus.APPROVED
        ):
            print(f"Reusing approved spec {spec.spec_id} ({SPEC_NAME}).")
            return spec

    now = datetime.now(timezone.utc)
    citation_ids = []
    for entry in CITATIONS:
        citation = Citation(retrieved_at=now, **entry)
        brain.add_citation(citation)
        citation_ids.append(citation.citation_id)
    spec = StrategySpec(
        name=SPEC_NAME,
        description=(
            "Monthly equal-weight tilt into top-3 names by 50/50 composite of "
            "12-1 momentum percentile and quality_fcf score (literature defaults)."
        ),
        proposed_by="human:study_runner",
        citation_ids=citation_ids,
        factor_dependencies=["momentum", "quality_fcf"],
        params=dict(SPEC_PARAMS),
        hook_ref=HOOK_REF,
    )
    brain.propose_spec(spec)
    approved = brain.approve_spec(spec.spec_id, approved_by=approver)
    print(f"Registered and approved spec {spec.spec_id} ({SPEC_NAME}) by {approver}.")
    return approved


def run_paper_replay(
    conn, price_api, spec, study, approver: str, end: date
) -> list[str]:
    """Write the study-window replay artifact under standard paper rules."""
    paper_store = PaperStore(conn)
    paper_store.init_schema()

    entry_record = next((r for r in study.rebalances if r.holdings), None)
    if entry_record is None:
        print(
            "Paper replay skipped: no rebalance produced holdings "
            "(insufficient eligible cross-section) — nothing to journal."
        )
        return []
    symbol = entry_record.holdings[0]
    window_dates = [d for d in study.strategy.dates if d >= entry_record.as_of]
    if len(window_dates) < 2:
        print("Paper replay skipped: no sessions after the first holdings decision.")
        return []
    window_end = window_dates[min(9, len(window_dates) - 1)]

    thesis = Thesis(
        spec_id=spec.spec_id,
        symbol=symbol,
        action=ActionLabel.ACCUMULATE,
        thesis_text=(
            f"Study replay for {SPEC_NAME}: {symbol} ranks first on the "
            f"quality+momentum composite as of {entry_record.as_of} "
            f"(composite {entry_record.composite[symbol]:.1f}, "
            f"momentum 12-1 {entry_record.momentum_12_1[symbol]:+.2%}, "
            f"quality {entry_record.quality_score[symbol]:.1f}). "
            "Small starter size inside the approved study window."
        ),
        invalidation_conditions=["Composite rank drops below universe median."],
        size_fraction=0.10,
        entry_window_start=window_dates[0],
        entry_window_end=window_end,
    )
    paper_store.propose_thesis(thesis)
    paper_store.approve_thesis(thesis.thesis_id, approved_by=approver)

    engine = PaperEngine(paper_store, price_api)
    written = engine.run_replay(
        ReplayRun(
            spec_id=spec.spec_id,
            start_date=window_dates[0],
            end_date=end,
            description=f"{SPEC_NAME} live-data study replay",
        )
    )
    for entry in written:
        tag = entry.entry_type
        benchmark_note = (
            f" vs VOO same period {entry.voo_return_same_period:+.4%}"
            if entry.voo_return_same_period is not None
            else ""
        )
        realized = (
            f" realized {entry.realized_return:+.4%}"
            if entry.realized_return is not None
            else ""
        )
        print(f"Journal [{tag}] {entry.entry_id}:{realized}{benchmark_note}")
    return [entry.entry_id for entry in written]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="data/market.duckdb", help="DuckDB path")
    parser.add_argument(
        "--approver",
        default="anant",
        help="Human identity recorded on approvals/decisions (default: anant)",
    )
    parser.add_argument(
        "--record-decision",
        action="store_true",
        help="Record the promotion decision implied by the gate batch "
        "(promote only if all four gates passed).",
    )
    parser.add_argument(
        "--skip-paper", action="store_true", help="Skip the paper replay artifact."
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        fail(f"database {db_path} does not exist — run ingestion first (Cursor owns it).")
    conn = duckdb.connect(str(db_path))

    config = load_config()
    universe = list(config.universe.symbols)
    benchmark = config.universe.default_benchmark

    try:
        row = conn.execute(
            "SELECT COUNT(*), MIN(trading_date), MAX(trading_date) "
            "FROM daily_ohlcv WHERE symbol = ?",
            [benchmark],
        ).fetchone()
    except duckdb.CatalogException:
        fail(f"{db_path} has no daily_ohlcv table — run init-db + ingestion first.")
    rows, start, end = row
    if not rows:
        fail(f"no stored {benchmark} rows in {db_path} — ingest prices first.")
    print(
        f"Universe: {len(universe)} symbols, benchmark {benchmark}; "
        f"{rows} {benchmark} sessions stored [{start} → {end}]."
    )

    fundamentals_store = FundamentalsStore(conn)
    equities = [
        s for s in universe
        if config.universe.assets[s].asset_type != "etf"
    ]
    fundamentals = load_fundamentals(fundamentals_store, equities)
    missing = sorted(set(equities) - set(fundamentals))
    print(
        f"Fundamentals loaded for {len(fundamentals)}/{len(equities)} equities"
        + (f"; none stored for {', '.join(missing)} (they can only be skipped "
           "as INSUFFICIENT_DATA, never synthesized)." if missing else ".")
    )

    brain = BrainStore(conn)
    brain.init_schema()
    spec = get_or_register_spec(brain, args.approver)

    hook = resolve_hook(spec.hook_ref)
    assert hook is not None
    try:
        study = run_quality_momentum_study(
            spec.params, PriceReadAPI(conn), universe, start, end,
            benchmark_symbol=benchmark, fundamentals_snapshots=fundamentals,
        )
    except StrategyDataError as e:
        fail(str(e))

    strategy = study.strategy
    net = strategy.net_returns()
    summary = summarize(net, trade_count=strategy.trade_count)
    benchmark_total = total_return(study.benchmark_returns)

    if study.dropped_symbols:
        for symbol, reason in sorted(study.dropped_symbols.items()):
            print(f"Excluded {symbol}: {reason}")

    outcome = GateHarness().run_and_record(
        brain, spec.spec_id, strategy, study.benchmark_returns, as_of=end
    )

    print()
    print(f"=== {SPEC_NAME} study report (as of {end}) ===")
    print(
        f"Series: {summary.periods} net-of-cost sessions "
        f"({DEFAULT_COST_BPS_PER_SIDE:.0f} bps/side), "
        f"{summary.trade_count} rebalance trades."
    )
    print(
        f"Strategy net: total {summary.total_return:+.2%}, "
        f"annualized {summary.annualized_return:+.2%}, "
        f"Sharpe {summary.sharpe_annualized if summary.sharpe_annualized is None else round(summary.sharpe_annualized, 2)}, "
        f"max drawdown {summary.max_drawdown:+.2%}."
    )
    print(f"{benchmark} same window: total {benchmark_total:+.2%}.")
    latest = study.latest_holdings
    print(f"Latest holdings (equal weight): {', '.join(latest) if latest else 'cash'}.")
    print()
    print("Gate batch (fixed order, stops at first failure):")
    for result in outcome.results:
        status = "PASS" if result.passed else "FAIL"
        note = f" — {result.notes[0]}" if result.notes else ""
        print(f"  {result.gate}: {status}{note}")
    ran = {r.gate for r in outcome.results}
    for gate in ("out_of_sample", "monte_carlo", "walk_forward", "deflated_sharpe"):
        if gate not in ran:
            print(f"  {gate}: NOT RUN (an earlier gate failed; order is fixed)")
    print(f"Recorded {len(outcome.test_run_ids)} TestRunRecords (trials={outcome.n_trials}).")

    if args.record_decision:
        decision = record_gate_outcome_decision(
            brain,
            spec.spec_id,
            decided_by=args.approver,
            rationale=(
                "Live-data study gate batch outcome recorded by the study runner; "
                f"all_passed={outcome.all_passed}."
            ),
        )
        print(
            f"Promotion decision recorded: {decision.decision.value} "
            f"({decision.from_state.value} → {decision.to_state.value})."
        )
    else:
        print("No promotion decision recorded (pass --record-decision to record one).")
    print(f"Demo-eligible: {is_demo_eligible(brain, spec.spec_id)}.")

    journal_ids: list[str] = []
    if args.skip_paper:
        print("Paper replay skipped (--skip-paper).")
    else:
        print()
        journal_ids = run_paper_replay(
            conn, PriceReadAPI(conn), spec, study, args.approver, end
        )
    print()
    print(
        "Reminder: research desk output only — action vocabulary is "
        "WATCH | HOLD | ACCUMULATE | REDUCE | AVOID | INSUFFICIENT_DATA."
    )


if __name__ == "__main__":
    main()
