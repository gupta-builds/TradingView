"""Desk CLI commands: brain, citations, analyze/critique (Typer on main app)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb
import typer

from research_data.agents.assemble import assemble_symbol_input
from research_data.agents.runner import RunnerError, run_analyze_symbol, run_critique_spec
from research_data.brain.citations import (
    add_citation,
    cite_from_journal,
    cite_from_vault,
)
from research_data.brain.loop import latest_gate_batch, record_gate_outcome_decision
from research_data.brain.models import StrategySpec
from research_data.brain.store import BrainStore, BrainStoreError
from research_data.factors.packets import (
    EtfBaselineComparison,
    MomentumScore,
    PacketDataQuality,
    PacketProvenance,
    QualityFCFScore,
    SafetyScore,
    ScorePacket,
    ScoreStatus,
    TAContext,
    ValuationContext,
)
from research_data.models import QualityStatus
from research_data.paper.store import PaperStore


def register_desk_commands(app: typer.Typer, *, default_db: str, project_root: Path) -> None:
    """Attach brain / cite / analyze commands to the root Typer app."""

    def _open(db_path: str) -> duckdb.DuckDBPyConnection:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(path))

    def _brain(conn) -> BrainStore:
        store = BrainStore(conn)
        store.init_schema()
        return store

    @app.command("cite-add")
    def cite_add_cmd(
        title: str = typer.Option(..., "--title"),
        source_type: str = typer.Option("paper", "--source-type"),
        claim: list[str] = typer.Option([], "--claim", help="Repeatable claim bullet"),
        authors: Optional[str] = typer.Option(None, "--authors"),
        url: Optional[str] = typer.Option(None, "--url"),
        db_path: str = typer.Option(default_db, "--db-path"),
    ) -> None:
        """Add a Citation row (claims may be empty at ingest)."""
        conn = _open(db_path)
        try:
            store = _brain(conn)
            citation, warning = add_citation(
                store,
                source_type=source_type,
                title=title,
                claims=list(claim),
                authors=authors,
                url=url,
            )
            if warning:
                typer.echo(f"WARNING: {warning}", err=True)
            typer.echo(f"citation_id={citation.citation_id}")
        finally:
            conn.close()

    @app.command("cite-from-vault")
    def cite_from_vault_cmd(
        path: str = typer.Argument(..., help="Path to vault markdown file"),
        vault_relpath: Optional[str] = typer.Option(None, "--relpath"),
        db_path: str = typer.Option(default_db, "--db-path"),
    ) -> None:
        """Ingest a vault note into brain_citations (idempotent on claims hash)."""
        conn = _open(db_path)
        try:
            store = _brain(conn)
            citation, msg = cite_from_vault(
                store, path, vault_relpath=vault_relpath
            )
            typer.echo(msg)
            if citation is not None:
                typer.echo(f"citation_id={citation.citation_id}")
        finally:
            conn.close()

    @app.command("cite-from-journal")
    def cite_from_journal_cmd(
        entry_id: str = typer.Argument(...),
        db_path: str = typer.Option(default_db, "--db-path"),
    ) -> None:
        """Upsert a journal_lesson Citation from a paper journal entry id."""
        conn = _open(db_path)
        try:
            brain = _brain(conn)
            paper = PaperStore(conn)
            paper.init_schema()
            entry = paper.get_journal_entry(entry_id)
            citation, msg = cite_from_journal(brain, entry)
            typer.echo(msg)
            if citation is not None:
                typer.echo(f"citation_id={citation.citation_id}")
        finally:
            conn.close()

    @app.command("propose")
    def propose_cmd(
        name: str = typer.Option(..., "--name"),
        description: str = typer.Option(..., "--description"),
        citation_id: list[str] = typer.Option(..., "--citation-id"),
        hook_ref: Optional[str] = typer.Option(None, "--hook-ref"),
        params_json: str = typer.Option("{}", "--params-json"),
        params_delta_json: Optional[str] = typer.Option(None, "--params-delta-json"),
        parent_spec_id: Optional[str] = typer.Option(None, "--parent-spec-id"),
        proposed_by: str = typer.Option("human", "--proposed-by"),
        factor: list[str] = typer.Option([], "--factor"),
        db_path: str = typer.Option(default_db, "--db-path"),
    ) -> None:
        """Insert a PROPOSED StrategySpec (resolve_hook at propose-time if set)."""
        conn = _open(db_path)
        try:
            store = _brain(conn)
            params = json.loads(params_json)
            params_delta = (
                json.loads(params_delta_json) if params_delta_json is not None else None
            )
            spec = StrategySpec(
                name=name,
                description=description,
                proposed_by=proposed_by,
                citation_ids=list(citation_id),
                factor_dependencies=list(factor),
                params=params,
                params_delta=params_delta,
                parent_spec_id=parent_spec_id,
                hook_ref=hook_ref,
            )
            store.propose_spec(spec)
            typer.echo(f"spec_id={spec.spec_id} status=proposed")
        except (BrainStoreError, json.JSONDecodeError) as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(code=1) from e
        finally:
            conn.close()

    @app.command("approve")
    def approve_cmd(
        spec_id: str = typer.Argument(...),
        approver: str = typer.Option(..., "--approver", help="Human identity (e.g. anant)"),
        db_path: str = typer.Option(default_db, "--db-path"),
    ) -> None:
        """Human gate: PROPOSED → APPROVED."""
        conn = _open(db_path)
        try:
            store = _brain(conn)
            spec = store.approve_spec(spec_id, approved_by=approver)
            typer.echo(f"spec_id={spec.spec_id} status={spec.status.value}")
        except (BrainStoreError, ValueError) as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(code=1) from e
        finally:
            conn.close()

    @app.command("reject")
    def reject_cmd(
        spec_id: str = typer.Argument(...),
        reason: str = typer.Option(..., "--reason"),
        approver: str = typer.Option(..., "--approver"),
        db_path: str = typer.Option(default_db, "--db-path"),
    ) -> None:
        """Human gate: PROPOSED → REJECTED."""
        conn = _open(db_path)
        try:
            store = _brain(conn)
            spec = store.reject_spec(spec_id, reason=reason, decided_by=approver)
            typer.echo(f"spec_id={spec.spec_id} status={spec.status.value}")
        except (BrainStoreError, ValueError) as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(code=1) from e
        finally:
            conn.close()

    @app.command("decide")
    def decide_cmd(
        spec_id: str = typer.Argument(...),
        approver: str = typer.Option(..., "--approver"),
        rationale: str = typer.Option(..., "--rationale"),
        db_path: str = typer.Option(default_db, "--db-path"),
    ) -> None:
        """Record promote/demote/hold from the latest gate batch (human only)."""
        conn = _open(db_path)
        try:
            store = _brain(conn)
            decision = record_gate_outcome_decision(
                store, spec_id, decided_by=approver, rationale=rationale
            )
            typer.echo(
                f"decision_id={decision.decision_id} "
                f"{decision.decision.value} → {decision.to_state.value}"
            )
        except Exception as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(code=1) from e
        finally:
            conn.close()

    def _minimal_blocked_packet(symbol: str, as_of: date, status: QualityStatus) -> ScorePacket:
        cap_map = {
            QualityStatus.MISSING: 0.0,
            QualityStatus.CONTRADICTORY: 0.3,
            QualityStatus.STALE: 0.5,
            QualityStatus.INSUFFICIENT_DATA: 0.4,
            QualityStatus.PARTIAL: 0.7,
            QualityStatus.USABLE: 1.0,
        }
        cap = cap_map.get(status, 0.0)
        now = datetime.now(timezone.utc)
        return ScorePacket(
            symbol=symbol,
            as_of=as_of,
            universe=[symbol],
            momentum_score=MomentumScore(
                status=ScoreStatus.INSUFFICIENT_DATA, universe_size=1
            ),
            safety_score=SafetyScore(
                status=ScoreStatus.INSUFFICIENT_DATA, universe_size=1
            ),
            quality_fcf_score=QualityFCFScore(
                status=ScoreStatus.INSUFFICIENT_DATA, universe_size=1
            ),
            valuation=ValuationContext(status=ScoreStatus.INSUFFICIENT_DATA),
            etf_baseline=EtfBaselineComparison(
                status=ScoreStatus.INSUFFICIENT_DATA, benchmark_symbol="VOO"
            ),
            ta_context=TAContext(),
            data_quality=PacketDataQuality(status=status, max_confidence=cap),
            provenance=PacketProvenance(generated_at=now),
        )

    @app.command("analyze-symbol")
    def analyze_symbol_cmd(
        symbol: str = typer.Argument(...),
        as_of: Optional[str] = typer.Option(None, "--as-of"),
        quality: Optional[str] = typer.Option(
            None,
            "--quality",
            help="Force quality status for blocked-path tests (missing|contradictory)",
        ),
        cards_dir: str = typer.Option(
            str(project_root / "data" / "cards"), "--cards-dir"
        ),
        vault_mirror: Optional[str] = typer.Option(
            None, "--vault-mirror", help="Optional one-way markdown export path"
        ),
        db_path: str = typer.Option(default_db, "--db-path"),
    ) -> None:
        """Assemble packets and write an EvidenceCard (INSUFFICIENT_DATA path is live)."""
        symbol = symbol.upper()
        as_of_date = date.fromisoformat(as_of) if as_of else date.today()
        conn = _open(db_path)
        try:
            if quality is not None:
                status = QualityStatus(quality.lower())
                packet = _minimal_blocked_packet(symbol, as_of_date, status)
            else:
                # Happy path needs FactorEngine + Fable LLM — report clearly.
                typer.echo(
                    "Happy-path analyze requires Fable LLM client. "
                    "Use --quality missing|contradictory for the deterministic "
                    "INSUFFICIENT_DATA path, or preload RESEARCH_DATA_LLM=fixture.",
                    err=True,
                )
                raise typer.Exit(code=2)

            bundle = assemble_symbol_input(score_packet=packet)
            try:
                card = run_analyze_symbol(
                    bundle,
                    cards_dir=cards_dir,
                    vault_mirror_path=vault_mirror,
                )
            except RunnerError as e:
                typer.echo(str(e), err=True)
                raise typer.Exit(code=1) from e
            typer.echo(
                f"card_id={card.card_id} action={card.action.value} "
                f"confidence={card.confidence}"
            )
        finally:
            conn.close()

    @app.command("critique-spec")
    def critique_spec_cmd(
        spec_id: str = typer.Argument(...),
        symbol: str = typer.Option("NVDA", "--symbol"),
        quality: Optional[str] = typer.Option(None, "--quality"),
        cards_dir: str = typer.Option(
            str(project_root / "data" / "cards"), "--cards-dir"
        ),
        db_path: str = typer.Option(default_db, "--db-path"),
    ) -> None:
        """Write a CriticReview for a spec (blocked path live; happy path = Fable)."""
        conn = _open(db_path)
        try:
            store = _brain(conn)
            store.get_spec(spec_id)
            runs = latest_gate_batch(store, spec_id)
            as_of_date = date.today()
            status = (
                QualityStatus(quality.lower())
                if quality
                else QualityStatus.USABLE
            )
            packet = _minimal_blocked_packet(symbol.upper(), as_of_date, status)
            bundle = assemble_symbol_input(
                score_packet=packet,
                spec_id=spec_id,
                gate_runs=runs,
            )
            try:
                review = run_critique_spec(bundle, cards_dir=cards_dir)
            except RunnerError as e:
                typer.echo(str(e), err=True)
                raise typer.Exit(code=1) from e
            typer.echo(
                f"review_id={review.review_id} suggestion={review.suggestion} "
                f"rejected={review.rejected}"
            )
        except BrainStoreError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(code=1) from e
        finally:
            conn.close()
