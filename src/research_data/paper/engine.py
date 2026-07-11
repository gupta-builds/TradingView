"""PaperEngine — timed auto-entry and accelerated historical replay.

Timed auto-entry contract: inside an approved thesis's entry window the
engine has full power to enter the paper book (that is the point of the
test window); outside it, or without human approval, it has none.

Replay contract: the engine walks a historical range using stored prices
only, fills entries when windows open, closes them at range end, and writes
the journal *as of the simulated dates* — verification on past markets, not
cinema playback. Every exit records the same-period VOO return.

Only ACCUMULATE theses auto-enter (they are the only thesis kind that opens
paper exposure). WATCH/HOLD/REDUCE/AVOID/INSUFFICIENT_DATA theses are
journaled decisions, not entries.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from research_data.models import OHLCVRecord
from research_data.paper.models import (
    ActionLabel,
    JournalEntry,
    PaperFill,
    PaperMode,
    PositionEffect,
    ReplayRun,
    Thesis,
    ThesisStatus,
)
from research_data.paper.store import PaperStore
from research_data.read_api import PriceReadAPI

#: Paper book notional per full-size thesis (size_fraction scales this).
DEFAULT_BOOK_NOTIONAL = 100_000.0


class PaperEngineError(Exception):
    """Raised when the paper engine cannot honor a contract."""


class PaperEngine:
    """Executes approved theses against stored prices. Deterministic."""

    def __init__(
        self,
        store: PaperStore,
        price_api: PriceReadAPI,
        benchmark_symbol: str = "VOO",
        book_notional: float = DEFAULT_BOOK_NOTIONAL,
        price_source: str | None = None,
        on_lesson_journaled: Callable[[JournalEntry], None] | None = None,
    ) -> None:
        self._store = store
        self._price_api = price_api
        self._benchmark_symbol = benchmark_symbol
        self._book_notional = book_notional
        self._price_source = price_source
        # Injected by CLI (has BrainStore); paper/ never imports BrainStore.
        self._on_lesson_journaled = on_lesson_journaled

    # -- timed auto-entry ---------------------------------------------------

    def execute_timed_entries(self, as_of: date, mode: PaperMode) -> list[PaperFill]:
        """Enter every approved, unfilled ACCUMULATE thesis whose window has
        opened by ``as_of``, at the first usable session close in the window.

        Uses only stored usable prices; a thesis whose window has no usable
        session yet is skipped (tried again next call), and one whose window
        fully passed without data expires — it never back-fills an entry.
        """
        fills: list[PaperFill] = []
        for thesis in self._store.list_theses(status=ThesisStatus.APPROVED):
            if thesis.action != ActionLabel.ACCUMULATE:
                continue
            if thesis.entry_window_start > as_of:
                continue  # window not open yet
            if self._store.list_fills(thesis.thesis_id):
                continue  # already entered

            window_end = min(thesis.entry_window_end, as_of)
            records = self._price_records(
                thesis.symbol, thesis.entry_window_start, window_end
            )
            if not records:
                if thesis.entry_window_end < as_of:
                    self._store.set_thesis_status(thesis.thesis_id, ThesisStatus.EXPIRED)
                    self._store.add_journal_entry(
                        JournalEntry(
                            mode=mode,
                            entry_type="review",
                            as_of=as_of,
                            body=(
                                f"Thesis expired unfilled: no usable {thesis.symbol} "
                                "session inside the approved entry window. "
                                "No entry was fabricated."
                            ),
                            thesis_id=thesis.thesis_id,
                            spec_id=thesis.spec_id,
                            symbol=thesis.symbol,
                        )
                    )
                continue

            first = records[0]
            price = first.adjusted_close or first.close
            quantity = (self._book_notional * thesis.size_fraction) / price
            fill = PaperFill(
                thesis_id=thesis.thesis_id,
                symbol=thesis.symbol,
                position_effect=PositionEffect.OPEN,
                quantity=quantity,
                fill_date=first.trading_date,
                fill_price=price,
                price_source=first.source,
                price_payload_hash=first.raw_payload_hash,
                mode=mode,
            )
            self._store.record_fill(fill)
            self._store.set_thesis_status(thesis.thesis_id, ThesisStatus.EXECUTED)
            self._store.add_journal_entry(
                JournalEntry(
                    mode=mode,
                    entry_type="entry",
                    as_of=first.trading_date,
                    body=(
                        f"Timed auto-entry for pre-approved thesis: opened "
                        f"{quantity:.4f} units of {thesis.symbol} at "
                        f"{price:.4f} ({first.source}). Window "
                        f"[{thesis.entry_window_start} → {thesis.entry_window_end}]."
                    ),
                    thesis_id=thesis.thesis_id,
                    spec_id=thesis.spec_id,
                    symbol=thesis.symbol,
                    next_review_date=thesis.next_review_date,
                )
            )
            fills.append(fill)
        return fills

    # -- accelerated historical replay -----------------------------------------

    def run_replay(self, replay: ReplayRun) -> list[JournalEntry]:
        """Walk the replay range, enter windows as they open, close at range
        end, and write the journal as-if-time-passed.

        Returns the journal entries written by this replay (in as-of order).
        """
        self._store.create_replay_run(replay)
        written: list[JournalEntry] = []

        self.execute_timed_entries(replay.end_date, PaperMode.REPLAY)

        # Close every position this replay opened, at the last usable session
        # in range, and compare against the benchmark over the same holding
        # period. Positions with no usable exit price stay open and are
        # flagged — never valued at an invented price.
        for thesis in self._store.list_theses(status=ThesisStatus.EXECUTED):
            open_fills = [
                f
                for f in self._store.list_fills(thesis.thesis_id)
                if f.mode == PaperMode.REPLAY
                and f.position_effect == PositionEffect.OPEN
            ]
            closed = {
                f.thesis_id
                for f in self._store.list_fills(thesis.thesis_id)
                if f.position_effect == PositionEffect.CLOSE
            }
            for fill in open_fills:
                if fill.thesis_id in closed:
                    continue
                exit_records = self._price_records(
                    fill.symbol, fill.fill_date, replay.end_date
                )
                if not exit_records or exit_records[-1].trading_date <= fill.fill_date:
                    written.append(
                        self._journal(
                            JournalEntry(
                                mode=PaperMode.REPLAY,
                                entry_type="review",
                                as_of=replay.end_date,
                                body=(
                                    f"Replay ended with {fill.symbol} position still "
                                    "open: no usable exit session after entry. "
                                    "Position not marked at a fabricated price."
                                ),
                                thesis_id=fill.thesis_id,
                                spec_id=thesis.spec_id,
                                symbol=fill.symbol,
                            )
                        )
                    )
                    continue
                last = exit_records[-1]
                exit_price = last.adjusted_close or last.close
                realized = exit_price / fill.fill_price - 1.0
                voo_return = self._benchmark_return(fill.fill_date, last.trading_date)
                self._store.record_fill(
                    PaperFill(
                        thesis_id=fill.thesis_id,
                        symbol=fill.symbol,
                        position_effect=PositionEffect.CLOSE,
                        quantity=fill.quantity,
                        fill_date=last.trading_date,
                        fill_price=exit_price,
                        price_source=last.source,
                        price_payload_hash=last.raw_payload_hash,
                        mode=PaperMode.REPLAY,
                    )
                )
                base_body = (
                    f"Replay exit: closed {fill.symbol} at {exit_price:.4f} "
                    f"(entered {fill.fill_price:.4f} on {fill.fill_date}). "
                    f"Realized {realized:+.4%}"
                )
                if voo_return is not None:
                    written.append(
                        self._journal(
                            JournalEntry(
                                mode=PaperMode.REPLAY,
                                entry_type="exit",
                                as_of=last.trading_date,
                                body=base_body
                                + f"; {self._benchmark_symbol} same period {voo_return:+.4%}.",
                                thesis_id=fill.thesis_id,
                                spec_id=thesis.spec_id,
                                symbol=fill.symbol,
                                realized_return=realized,
                                voo_return_same_period=voo_return,
                            )
                        )
                    )
                else:
                    # An "exit" entry requires the benchmark figure. When VOO
                    # data is genuinely missing we say so in a review entry —
                    # we do not invent a benchmark number.
                    written.append(
                        self._journal(
                            JournalEntry(
                                mode=PaperMode.REPLAY,
                                entry_type="review",
                                as_of=last.trading_date,
                                body=base_body
                                + f"; {self._benchmark_symbol} same-period return "
                                "unavailable in stored data — benchmark comparison "
                                "missing, flagged for follow-up.",
                                thesis_id=fill.thesis_id,
                                spec_id=thesis.spec_id,
                                symbol=fill.symbol,
                                realized_return=realized,
                            )
                        )
                    )

        self._store.complete_replay_run(replay.replay_id)
        return written

    # -- helpers -------------------------------------------------------------------

    def _journal(self, entry: JournalEntry) -> JournalEntry:
        self._store.add_journal_entry(entry)
        if (
            self._on_lesson_journaled is not None
            and entry.entry_type in {"lesson", "exit"}
        ):
            self._on_lesson_journaled(entry)
        return entry

    def _price_records(self, symbol: str, start: date, end: date) -> list[OHLCVRecord]:
        if end < start:
            return []
        return self._price_api.get_price_frame(
            symbols=[symbol],
            start=start,
            end=end,
            source=self._price_source,
            require_usable=True,
        )

    def _benchmark_return(self, start: date, end: date) -> float | None:
        records = self._price_records(self._benchmark_symbol, start, end)
        if len(records) < 2:
            return None
        first = records[0].adjusted_close or records[0].close
        last = records[-1].adjusted_close or records[-1].close
        if first <= 0:
            return None
        return last / first - 1.0
