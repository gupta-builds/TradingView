"""DuckDB persistence for theses, fills, journal entries, and replay runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb

from research_data.brain.models import validate_human_identity
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


class PaperStoreError(Exception):
    """Raised on illegal paper-store operations."""


def _to_db_ts(value: datetime | None) -> datetime | None:
    """Naive-UTC normalization (DuckDB TIMESTAMP converts aware → local)."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


_CREATE_THESES = """\
CREATE TABLE IF NOT EXISTS paper_theses (
    thesis_id VARCHAR PRIMARY KEY,
    spec_id VARCHAR,
    source_card_id VARCHAR,
    symbol VARCHAR NOT NULL,
    action VARCHAR NOT NULL,
    thesis_text VARCHAR NOT NULL,
    invalidation_conditions JSON NOT NULL,
    size_fraction DOUBLE NOT NULL,
    entry_window_start DATE NOT NULL,
    entry_window_end DATE NOT NULL,
    entry_rule JSON NOT NULL,
    status VARCHAR NOT NULL,
    proposed_by VARCHAR NOT NULL,
    approved_by VARCHAR,
    approved_at TIMESTAMP,
    next_review_date DATE,
    created_at TIMESTAMP NOT NULL
);
"""

_CREATE_FILLS = """\
CREATE TABLE IF NOT EXISTS paper_fills (
    fill_id VARCHAR PRIMARY KEY,
    thesis_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    position_effect VARCHAR NOT NULL,
    quantity DOUBLE NOT NULL,
    fill_date DATE NOT NULL,
    fill_price DOUBLE NOT NULL,
    price_source VARCHAR NOT NULL,
    price_payload_hash VARCHAR NOT NULL,
    mode VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL
);
"""

_CREATE_JOURNAL = """\
CREATE TABLE IF NOT EXISTS paper_journal_entries (
    entry_id VARCHAR PRIMARY KEY,
    mode VARCHAR NOT NULL,
    entry_type VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    body VARCHAR NOT NULL,
    spec_id VARCHAR,
    thesis_id VARCHAR,
    symbol VARCHAR,
    realized_return DOUBLE,
    voo_return_same_period DOUBLE,
    next_review_date DATE,
    created_at TIMESTAMP NOT NULL
);
"""

_CREATE_REPLAY_RUNS = """\
CREATE TABLE IF NOT EXISTS paper_replay_runs (
    replay_id VARCHAR PRIMARY KEY,
    spec_id VARCHAR,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL
);
"""


class PaperStore:
    """Typed persistence API for the paper book."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def init_schema(self) -> None:
        for stmt in (_CREATE_THESES, _CREATE_FILLS, _CREATE_JOURNAL, _CREATE_REPLAY_RUNS):
            self._conn.execute(stmt)

    # -- theses ------------------------------------------------------------

    def propose_thesis(self, thesis: Thesis) -> str:
        if thesis.status != ThesisStatus.PROPOSED:
            raise PaperStoreError("new theses must enter as PROPOSED")
        self._conn.execute(
            """
            INSERT INTO paper_theses (
                thesis_id, spec_id, source_card_id, symbol, action, thesis_text,
                invalidation_conditions, size_fraction,
                entry_window_start, entry_window_end, entry_rule,
                status, proposed_by, approved_by, approved_at,
                next_review_date, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                thesis.thesis_id,
                thesis.spec_id,
                thesis.source_card_id,
                thesis.symbol,
                thesis.action.value,
                thesis.thesis_text,
                json.dumps(thesis.invalidation_conditions),
                thesis.size_fraction,
                thesis.entry_window_start,
                thesis.entry_window_end,
                json.dumps(thesis.entry_rule),
                thesis.status.value,
                thesis.proposed_by,
                thesis.approved_by,
                _to_db_ts(thesis.approved_at),
                thesis.next_review_date,
                _to_db_ts(thesis.created_at),
            ],
        )
        return thesis.thesis_id

    def get_thesis(self, thesis_id: str) -> Thesis:
        row = self._conn.execute(
            "SELECT * FROM paper_theses WHERE thesis_id = ?", [thesis_id]
        ).fetchone()
        if row is None:
            raise PaperStoreError(f"Unknown thesis_id: {thesis_id}")
        return _row_to_thesis(row)

    def list_theses(self, status: ThesisStatus | None = None) -> list[Thesis]:
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM paper_theses ORDER BY created_at, thesis_id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM paper_theses WHERE status = ? ORDER BY created_at, thesis_id",
                [status.value],
            ).fetchall()
        return [_row_to_thesis(r) for r in rows]

    def approve_thesis(
        self, thesis_id: str, approved_by: str, approved_at: datetime | None = None
    ) -> Thesis:
        """Human gate: PROPOSED → APPROVED. Auto-entry is illegal before this."""
        approved_by = validate_human_identity(approved_by, "approved_by")
        thesis = self.get_thesis(thesis_id)
        if thesis.status != ThesisStatus.PROPOSED:
            raise PaperStoreError(
                f"Only PROPOSED theses can be approved; {thesis_id} is {thesis.status.value}"
            )
        approved_at = approved_at or datetime.now(timezone.utc)
        self._conn.execute(
            "UPDATE paper_theses SET status = ?, approved_by = ?, approved_at = ? "
            "WHERE thesis_id = ?",
            [ThesisStatus.APPROVED.value, approved_by, _to_db_ts(approved_at), thesis_id],
        )
        return self.get_thesis(thesis_id)

    def set_thesis_status(self, thesis_id: str, status: ThesisStatus) -> None:
        self.get_thesis(thesis_id)
        self._conn.execute(
            "UPDATE paper_theses SET status = ? WHERE thesis_id = ?",
            [status.value, thesis_id],
        )

    # -- fills --------------------------------------------------------------

    def record_fill(self, fill: PaperFill) -> str:
        """Persist a fill. OPEN fills demand an approved thesis and a fill
        date inside the approved entry window — the timed-entry contract."""
        thesis = self.get_thesis(fill.thesis_id)
        if fill.position_effect == PositionEffect.OPEN:
            if thesis.status not in (ThesisStatus.APPROVED, ThesisStatus.EXECUTED):
                raise PaperStoreError(
                    f"OPEN fill requires an APPROVED thesis; {fill.thesis_id} "
                    f"is {thesis.status.value}"
                )
            if not (thesis.entry_window_start <= fill.fill_date <= thesis.entry_window_end):
                raise PaperStoreError(
                    f"OPEN fill date {fill.fill_date} is outside the approved "
                    f"entry window [{thesis.entry_window_start}, {thesis.entry_window_end}]"
                )
        self._conn.execute(
            """
            INSERT INTO paper_fills (
                fill_id, thesis_id, symbol, position_effect, quantity,
                fill_date, fill_price, price_source, price_payload_hash,
                mode, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                fill.fill_id,
                fill.thesis_id,
                fill.symbol,
                fill.position_effect.value,
                fill.quantity,
                fill.fill_date,
                fill.fill_price,
                fill.price_source,
                fill.price_payload_hash,
                fill.mode.value,
                _to_db_ts(fill.created_at),
            ],
        )
        return fill.fill_id

    def list_fills(self, thesis_id: str | None = None) -> list[PaperFill]:
        if thesis_id is None:
            rows = self._conn.execute(
                "SELECT * FROM paper_fills ORDER BY fill_date, created_at, fill_id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM paper_fills WHERE thesis_id = ? "
                "ORDER BY fill_date, created_at, fill_id",
                [thesis_id],
            ).fetchall()
        return [_row_to_fill(r) for r in rows]

    # -- journal -------------------------------------------------------------

    def add_journal_entry(self, entry: JournalEntry) -> str:
        self._conn.execute(
            """
            INSERT INTO paper_journal_entries (
                entry_id, mode, entry_type, as_of, body, spec_id, thesis_id,
                symbol, realized_return, voo_return_same_period,
                next_review_date, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                entry.entry_id,
                entry.mode.value,
                entry.entry_type,
                entry.as_of,
                entry.body,
                entry.spec_id,
                entry.thesis_id,
                entry.symbol,
                entry.realized_return,
                entry.voo_return_same_period,
                entry.next_review_date,
                _to_db_ts(entry.created_at),
            ],
        )
        return entry.entry_id

    def get_journal_entry(self, entry_id: str) -> JournalEntry:
        row = self._conn.execute(
            "SELECT * FROM paper_journal_entries WHERE entry_id = ?", [entry_id]
        ).fetchone()
        if row is None:
            raise PaperStoreError(f"Unknown journal entry_id: {entry_id}")
        return _row_to_journal(row)

    def list_journal_entries(
        self,
        mode: PaperMode | None = None,
        thesis_id: str | None = None,
    ) -> list[JournalEntry]:
        conditions: list[str] = []
        params: list = []
        if mode is not None:
            conditions.append("mode = ?")
            params.append(mode.value)
        if thesis_id is not None:
            conditions.append("thesis_id = ?")
            params.append(thesis_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._conn.execute(
            f"SELECT * FROM paper_journal_entries {where} "
            "ORDER BY as_of, created_at, entry_id",
            params,
        ).fetchall()
        return [_row_to_journal(r) for r in rows]

    def pending_reviews(self, as_of: date) -> list[JournalEntry]:
        """Review jump-ahead hook: journal entries whose review date is due."""
        rows = self._conn.execute(
            "SELECT * FROM paper_journal_entries "
            "WHERE next_review_date IS NOT NULL AND next_review_date <= ? "
            "ORDER BY next_review_date, entry_id",
            [as_of],
        ).fetchall()
        return [_row_to_journal(r) for r in rows]

    # -- replay runs ------------------------------------------------------------

    def create_replay_run(self, run: ReplayRun) -> str:
        self._conn.execute(
            """
            INSERT INTO paper_replay_runs (
                replay_id, spec_id, start_date, end_date, status, description, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run.replay_id,
                run.spec_id,
                run.start_date,
                run.end_date,
                run.status,
                run.description,
                _to_db_ts(run.created_at),
            ],
        )
        return run.replay_id

    def complete_replay_run(self, replay_id: str) -> None:
        self._conn.execute(
            "UPDATE paper_replay_runs SET status = 'completed' WHERE replay_id = ?",
            [replay_id],
        )

    def get_replay_run(self, replay_id: str) -> ReplayRun:
        row = self._conn.execute(
            "SELECT * FROM paper_replay_runs WHERE replay_id = ?", [replay_id]
        ).fetchone()
        if row is None:
            raise PaperStoreError(f"Unknown replay_id: {replay_id}")
        return ReplayRun(
            replay_id=row[0],
            spec_id=row[1],
            start_date=row[2],
            end_date=row[3],
            status=row[4],
            description=row[5],
            created_at=_as_utc(row[6]),
        )


# ---------------------------------------------------------------------------
# Row converters
# ---------------------------------------------------------------------------


def _loads(value):
    return json.loads(value) if isinstance(value, str) else value


def _row_to_thesis(row: tuple) -> Thesis:
    # Post-E4: source_card_id at index 2 (17 cols). Pre-E4: 16 cols without it.
    if len(row) >= 17:
        return Thesis(
            thesis_id=row[0],
            spec_id=row[1],
            source_card_id=row[2],
            symbol=row[3],
            action=ActionLabel(row[4]),
            thesis_text=row[5],
            invalidation_conditions=_loads(row[6]),
            size_fraction=row[7],
            entry_window_start=row[8],
            entry_window_end=row[9],
            entry_rule=_loads(row[10]),
            status=ThesisStatus(row[11]),
            proposed_by=row[12],
            approved_by=row[13],
            approved_at=_as_utc(row[14]),
            next_review_date=row[15],
            created_at=_as_utc(row[16]),
        )
    return Thesis(
        thesis_id=row[0],
        spec_id=row[1],
        symbol=row[2],
        action=ActionLabel(row[3]),
        thesis_text=row[4],
        invalidation_conditions=_loads(row[5]),
        size_fraction=row[6],
        entry_window_start=row[7],
        entry_window_end=row[8],
        entry_rule=_loads(row[9]),
        status=ThesisStatus(row[10]),
        proposed_by=row[11],
        approved_by=row[12],
        approved_at=_as_utc(row[13]),
        next_review_date=row[14],
        created_at=_as_utc(row[15]),
    )


def _row_to_fill(row: tuple) -> PaperFill:
    return PaperFill(
        fill_id=row[0],
        thesis_id=row[1],
        symbol=row[2],
        position_effect=PositionEffect(row[3]),
        quantity=row[4],
        fill_date=row[5],
        fill_price=row[6],
        price_source=row[7],
        price_payload_hash=row[8],
        mode=PaperMode(row[9]),
        created_at=_as_utc(row[10]),
    )


def _row_to_journal(row: tuple) -> JournalEntry:
    return JournalEntry(
        entry_id=row[0],
        mode=PaperMode(row[1]),
        entry_type=row[2],
        as_of=row[3],
        body=row[4],
        spec_id=row[5],
        thesis_id=row[6],
        symbol=row[7],
        realized_return=row[8],
        voo_return_same_period=row[9],
        next_review_date=row[10],
        created_at=_as_utc(row[11]),
    )
