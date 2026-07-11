"""DuckDB persistence for the brain closed loop.

Separate tables from the ingestion schema (``daily_ohlcv`` and friends stay
clean). All writes go through typed models; approval and promotion decisions
require a human identity (see ``models.validate_human_identity``).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import duckdb

from research_data.brain.models import (
    Citation,
    DecisionKind,
    GateName,
    JournalLink,
    PromotionDecision,
    PromotionState,
    SpecStatus,
    StrategySpec,
    TestRunRecord,
    validate_human_identity,
)


class BrainStoreError(Exception):
    """Raised on illegal brain-store operations (bad transitions, unknown ids)."""


def _to_db_ts(value: datetime | None) -> datetime | None:
    """Normalize to naive UTC before insert.

    DuckDB TIMESTAMP columns convert tz-aware datetimes to *local* time and
    drop the offset, which corrupts round-trips on non-UTC machines.
    """
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


_CREATE_CITATIONS = """\
CREATE TABLE IF NOT EXISTS brain_citations (
    citation_id VARCHAR PRIMARY KEY,
    source_type VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    url VARCHAR,
    authors VARCHAR,
    retrieved_at TIMESTAMP NOT NULL,
    claims JSON NOT NULL,
    license_note VARCHAR,
    created_at TIMESTAMP NOT NULL
);
"""

_CREATE_SPECS = """\
CREATE TABLE IF NOT EXISTS brain_strategy_specs (
    spec_id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    version INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    promotion_state VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    proposed_by VARCHAR NOT NULL,
    citation_ids JSON NOT NULL,
    factor_dependencies JSON NOT NULL,
    params JSON NOT NULL,
    params_delta JSON,
    parent_spec_id VARCHAR,
    hook_ref VARCHAR,
    created_at TIMESTAMP NOT NULL,
    approved_by VARCHAR,
    approved_at TIMESTAMP,
    status_reason VARCHAR,
    UNIQUE (name, version)
);
"""

_CREATE_TEST_RUNS = """\
CREATE TABLE IF NOT EXISTS brain_test_runs (
    test_run_id VARCHAR PRIMARY KEY,
    spec_id VARCHAR NOT NULL,
    gate_name VARCHAR NOT NULL,
    sequence_index INTEGER NOT NULL,
    inputs JSON NOT NULL,
    outputs JSON NOT NULL,
    passed BOOLEAN NOT NULL,
    as_of DATE NOT NULL,
    created_at TIMESTAMP NOT NULL
);
"""

_CREATE_DECISIONS = """\
CREATE TABLE IF NOT EXISTS brain_decisions (
    decision_id VARCHAR PRIMARY KEY,
    spec_id VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,
    from_state VARCHAR NOT NULL,
    to_state VARCHAR NOT NULL,
    rationale VARCHAR NOT NULL,
    evidence_test_run_ids JSON NOT NULL,
    evidence_citation_ids JSON NOT NULL,
    journal_entry_ids JSON NOT NULL,
    decided_by VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL
);
"""

_CREATE_JOURNAL_LINKS = """\
CREATE TABLE IF NOT EXISTS brain_journal_links (
    link_id VARCHAR PRIMARY KEY,
    spec_id VARCHAR NOT NULL,
    journal_entry_id VARCHAR NOT NULL,
    relation VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL
);
"""


class BrainStore:
    """Typed persistence API for citations, specs, test runs, decisions, links."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def init_schema(self) -> None:
        """Create brain tables if they do not exist. Preserves existing data."""
        for stmt in (
            _CREATE_CITATIONS,
            _CREATE_SPECS,
            _CREATE_TEST_RUNS,
            _CREATE_DECISIONS,
            _CREATE_JOURNAL_LINKS,
        ):
            self._conn.execute(stmt)

    # -- citations ----------------------------------------------------------

    def add_citation(self, citation: Citation) -> str:
        self._conn.execute(
            """
            INSERT INTO brain_citations (
                citation_id, source_type, title, url, authors,
                retrieved_at, claims, license_note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                citation.citation_id,
                citation.source_type,
                citation.title,
                citation.url,
                citation.authors,
                _to_db_ts(citation.retrieved_at),
                json.dumps(citation.claims),
                citation.license_note,
                _to_db_ts(citation.created_at),
            ],
        )
        return citation.citation_id

    def get_citation(self, citation_id: str) -> Citation:
        row = self._conn.execute(
            "SELECT * FROM brain_citations WHERE citation_id = ?", [citation_id]
        ).fetchone()
        if row is None:
            raise BrainStoreError(f"Unknown citation_id: {citation_id}")
        return _row_to_citation(row)

    def list_citations(self) -> list[Citation]:
        rows = self._conn.execute(
            "SELECT * FROM brain_citations ORDER BY created_at, citation_id"
        ).fetchall()
        return [_row_to_citation(r) for r in rows]

    # -- specs ---------------------------------------------------------------

    def propose_spec(self, spec: StrategySpec) -> str:
        """Store a new spec. It must enter the loop as PROPOSED / UNPROVEN."""
        if spec.status != SpecStatus.PROPOSED:
            raise BrainStoreError(
                f"New specs must have status PROPOSED, got {spec.status.value}"
            )
        if spec.promotion_state != PromotionState.UNPROVEN:
            raise BrainStoreError(
                "New specs must enter with promotion_state UNPROVEN, "
                f"got {spec.promotion_state.value}"
            )
        for citation_id in spec.citation_ids:
            # A proposal must cite research that actually exists in the store.
            citation = self.get_citation(citation_id)
            if not citation.claims:
                raise BrainStoreError(
                    f"Citation {citation_id} has empty claims; "
                    "non-empty claims required when assembling evidence_citation_ids "
                    "for a PROPOSED StrategySpec"
                )
        if spec.parent_spec_id is not None:
            self.get_spec(spec.parent_spec_id)
        if spec.hook_ref:
            # Fail-closed early (D2): resolve at propose-time, not only approve.
            from research_data.brain.loop import resolve_hook

            resolve_hook(spec.hook_ref)
        self._conn.execute(
            """
            INSERT INTO brain_strategy_specs (
                spec_id, name, version, status, promotion_state, description,
                proposed_by, citation_ids, factor_dependencies, params,
                params_delta, parent_spec_id, hook_ref, created_at,
                approved_by, approved_at, status_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                spec.spec_id,
                spec.name,
                spec.version,
                spec.status.value,
                spec.promotion_state.value,
                spec.description,
                spec.proposed_by,
                json.dumps(spec.citation_ids),
                json.dumps(spec.factor_dependencies),
                json.dumps(spec.params),
                json.dumps(spec.params_delta) if spec.params_delta is not None else None,
                spec.parent_spec_id,
                spec.hook_ref,
                _to_db_ts(spec.created_at),
                spec.approved_by,
                _to_db_ts(spec.approved_at),
                spec.status_reason,
            ],
        )
        return spec.spec_id

    def get_spec(self, spec_id: str) -> StrategySpec:
        row = self._conn.execute(
            "SELECT * FROM brain_strategy_specs WHERE spec_id = ?", [spec_id]
        ).fetchone()
        if row is None:
            raise BrainStoreError(f"Unknown spec_id: {spec_id}")
        return _row_to_spec(row)

    def list_specs(self, status: SpecStatus | None = None) -> list[StrategySpec]:
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM brain_strategy_specs ORDER BY created_at, spec_id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM brain_strategy_specs WHERE status = ? "
                "ORDER BY created_at, spec_id",
                [status.value],
            ).fetchall()
        return [_row_to_spec(r) for r in rows]

    def approve_spec(
        self,
        spec_id: str,
        approved_by: str,
        approved_at: datetime | None = None,
    ) -> StrategySpec:
        """Human gate: PROPOSED → APPROVED. ``approved_by`` must be a human."""
        approved_by = validate_human_identity(approved_by, "approved_by")
        spec = self.get_spec(spec_id)
        if spec.status != SpecStatus.PROPOSED:
            raise BrainStoreError(
                f"Only PROPOSED specs can be approved; {spec_id} is {spec.status.value}"
            )
        approved_at = approved_at or datetime.now(timezone.utc)
        self._conn.execute(
            """
            UPDATE brain_strategy_specs
            SET status = ?, approved_by = ?, approved_at = ?
            WHERE spec_id = ?
            """,
            [SpecStatus.APPROVED.value, approved_by, _to_db_ts(approved_at), spec_id],
        )
        return self.get_spec(spec_id)

    def reject_spec(self, spec_id: str, reason: str, decided_by: str) -> StrategySpec:
        """Human gate: PROPOSED → REJECTED with a stated reason."""
        decided_by = validate_human_identity(decided_by, "decided_by")
        if not reason.strip():
            raise BrainStoreError("rejection requires a non-empty reason")
        spec = self.get_spec(spec_id)
        if spec.status != SpecStatus.PROPOSED:
            raise BrainStoreError(
                f"Only PROPOSED specs can be rejected; {spec_id} is {spec.status.value}"
            )
        self._conn.execute(
            "UPDATE brain_strategy_specs SET status = ?, status_reason = ? WHERE spec_id = ?",
            [SpecStatus.REJECTED.value, reason, spec_id],
        )
        return self.get_spec(spec_id)

    def retire_spec(self, spec_id: str, reason: str, decided_by: str) -> StrategySpec:
        """Human gate: APPROVED → RETIRED (spec leaves active rotation)."""
        decided_by = validate_human_identity(decided_by, "decided_by")
        if not reason.strip():
            raise BrainStoreError("retiring requires a non-empty reason")
        spec = self.get_spec(spec_id)
        if spec.status != SpecStatus.APPROVED:
            raise BrainStoreError(
                f"Only APPROVED specs can be retired; {spec_id} is {spec.status.value}"
            )
        self._conn.execute(
            "UPDATE brain_strategy_specs SET status = ?, status_reason = ? WHERE spec_id = ?",
            [SpecStatus.RETIRED.value, reason, spec_id],
        )
        return self.get_spec(spec_id)

    # -- test runs ------------------------------------------------------------

    def record_test_run(self, run: TestRunRecord) -> str:
        # A gate run is only meaningful against a spec that exists and was
        # approved by a human — gates never run on unapproved proposals.
        spec = self.get_spec(run.spec_id)
        if spec.status != SpecStatus.APPROVED:
            raise BrainStoreError(
                f"Gates run only against APPROVED specs; {run.spec_id} is {spec.status.value}"
            )
        self._conn.execute(
            """
            INSERT INTO brain_test_runs (
                test_run_id, spec_id, gate_name, sequence_index,
                inputs, outputs, passed, as_of, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run.test_run_id,
                run.spec_id,
                run.gate_name.value,
                run.sequence_index,
                json.dumps(run.inputs, default=str),
                json.dumps(run.outputs, default=str),
                run.passed,
                run.as_of,
                _to_db_ts(run.created_at),
            ],
        )
        return run.test_run_id

    def list_test_runs(self, spec_id: str) -> list[TestRunRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM brain_test_runs WHERE spec_id = ?
            ORDER BY created_at, sequence_index, test_run_id
            """,
            [spec_id],
        ).fetchall()
        return [_row_to_test_run(r) for r in rows]

    def list_runs_for_gate(self, gate_name: GateName) -> list[TestRunRecord]:
        """All recorded runs of one gate across every spec (trial history)."""
        rows = self._conn.execute(
            "SELECT * FROM brain_test_runs WHERE gate_name = ? "
            "ORDER BY created_at, test_run_id",
            [gate_name.value],
        ).fetchall()
        return [_row_to_test_run(r) for r in rows]

    def count_tested_specs(self) -> int:
        """Number of distinct specs with at least one recorded gate run.

        This is the trial count fed to the deflated-Sharpe gate: every strategy
        configuration that reached testing counts as a selection-bias trial.
        """
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT spec_id) FROM brain_test_runs"
        ).fetchone()
        return int(row[0]) if row else 0

    # -- decisions -------------------------------------------------------------

    def record_decision(self, decision: PromotionDecision) -> str:
        """Persist a promote/demote/hold decision and move the spec's state."""
        spec = self.get_spec(decision.spec_id)
        if spec.promotion_state != decision.from_state:
            raise BrainStoreError(
                f"Decision from_state {decision.from_state.value} does not match "
                f"spec promotion_state {spec.promotion_state.value}"
            )
        if decision.decision != DecisionKind.HOLD and decision.from_state == decision.to_state:
            raise BrainStoreError("promote/demote decisions must change state")
        for run_id in decision.evidence_test_run_ids:
            row = self._conn.execute(
                "SELECT test_run_id FROM brain_test_runs WHERE test_run_id = ?",
                [run_id],
            ).fetchone()
            if row is None:
                raise BrainStoreError(f"Unknown evidence test_run_id: {run_id}")
        self._conn.execute(
            """
            INSERT INTO brain_decisions (
                decision_id, spec_id, decision, from_state, to_state, rationale,
                evidence_test_run_ids, evidence_citation_ids, journal_entry_ids,
                decided_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                decision.decision_id,
                decision.spec_id,
                decision.decision.value,
                decision.from_state.value,
                decision.to_state.value,
                decision.rationale,
                json.dumps(decision.evidence_test_run_ids),
                json.dumps(decision.evidence_citation_ids),
                json.dumps(decision.journal_entry_ids),
                decision.decided_by,
                _to_db_ts(decision.created_at),
            ],
        )
        self._conn.execute(
            "UPDATE brain_strategy_specs SET promotion_state = ? WHERE spec_id = ?",
            [decision.to_state.value, decision.spec_id],
        )
        return decision.decision_id

    def list_decisions(self, spec_id: str) -> list[PromotionDecision]:
        rows = self._conn.execute(
            "SELECT * FROM brain_decisions WHERE spec_id = ? ORDER BY created_at, decision_id",
            [spec_id],
        ).fetchall()
        return [_row_to_decision(r) for r in rows]

    # -- journal links -----------------------------------------------------------

    def link_journal(self, link: JournalLink) -> str:
        self.get_spec(link.spec_id)
        self._conn.execute(
            """
            INSERT INTO brain_journal_links (
                link_id, spec_id, journal_entry_id, relation, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [link.link_id, link.spec_id, link.journal_entry_id, link.relation, _to_db_ts(link.created_at)],
        )
        return link.link_id

    def list_journal_links(self, spec_id: str) -> list[JournalLink]:
        rows = self._conn.execute(
            "SELECT * FROM brain_journal_links WHERE spec_id = ? ORDER BY created_at, link_id",
            [spec_id],
        ).fetchall()
        return [
            JournalLink(
                link_id=r[0],
                spec_id=r[1],
                journal_entry_id=r[2],
                relation=r[3],
                created_at=_as_utc(r[4]),
            )
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Row converters
# ---------------------------------------------------------------------------


def _as_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _loads(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _row_to_citation(row: tuple) -> Citation:
    return Citation(
        citation_id=row[0],
        source_type=row[1],
        title=row[2],
        url=row[3],
        authors=row[4],
        retrieved_at=_as_utc(row[5]),
        claims=_loads(row[6]),
        license_note=row[7],
        created_at=_as_utc(row[8]),
    )


def _row_to_spec(row: tuple) -> StrategySpec:
    # Columns: 0-9 classic, then params_delta, parent_spec_id, hook_ref, …
    # Support both pre-D2 (15 cols) and post-D2 (17 cols) row shapes for
    # in-memory tests that rebuild schema; live DBs rebuild per desk policy.
    if len(row) >= 17:
        return StrategySpec(
            spec_id=row[0],
            name=row[1],
            version=row[2],
            status=SpecStatus(row[3]),
            promotion_state=PromotionState(row[4]),
            description=row[5],
            proposed_by=row[6],
            citation_ids=_loads(row[7]),
            factor_dependencies=_loads(row[8]),
            params=_loads(row[9]),
            params_delta=_loads(row[10]) if row[10] is not None else None,
            parent_spec_id=row[11],
            hook_ref=row[12],
            created_at=_as_utc(row[13]),
            approved_by=row[14],
            approved_at=_as_utc(row[15]),
            status_reason=row[16],
        )
    return StrategySpec(
        spec_id=row[0],
        name=row[1],
        version=row[2],
        status=SpecStatus(row[3]),
        promotion_state=PromotionState(row[4]),
        description=row[5],
        proposed_by=row[6],
        citation_ids=_loads(row[7]),
        factor_dependencies=_loads(row[8]),
        params=_loads(row[9]),
        hook_ref=row[10],
        created_at=_as_utc(row[11]),
        approved_by=row[12],
        approved_at=_as_utc(row[13]),
        status_reason=row[14],
    )


def _row_to_test_run(row: tuple) -> TestRunRecord:
    return TestRunRecord(
        test_run_id=row[0],
        spec_id=row[1],
        gate_name=GateName(row[2]),
        sequence_index=row[3],
        inputs=_loads(row[4]),
        outputs=_loads(row[5]),
        passed=row[6],
        as_of=row[7],
        created_at=_as_utc(row[8]),
    )


def _row_to_decision(row: tuple) -> PromotionDecision:
    return PromotionDecision(
        decision_id=row[0],
        spec_id=row[1],
        decision=DecisionKind(row[2]),
        from_state=PromotionState(row[3]),
        to_state=PromotionState(row[4]),
        rationale=row[5],
        evidence_test_run_ids=_loads(row[6]),
        evidence_citation_ids=_loads(row[7]),
        journal_entry_ids=_loads(row[8]),
        decided_by=row[9],
        created_at=_as_utc(row[10]),
    )
