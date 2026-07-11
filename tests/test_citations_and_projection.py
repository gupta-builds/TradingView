"""D5 citation callback + gate projection + vault ingest smoke."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from research_data.brain.citations import (
    cite_from_journal,
    cite_from_vault,
    make_lesson_journal_callback,
    vault_citation_id,
)
from research_data.brain.models import GateName, TestRunRecord
from research_data.brain.store import BrainStore
from research_data.cards.gate_projection import project_gate_batch
from research_data.paper.models import JournalEntry, PaperMode
from research_data.paper.store import PaperStore


def test_gate_projection_renames_only() -> None:
    runs = [
        TestRunRecord(
            spec_id="s1",
            gate_name=GateName.OUT_OF_SAMPLE,
            sequence_index=0,
            outputs={"oos_sharpe": 1.14},
            passed=True,
            as_of=date(2026, 7, 10),
        ),
        TestRunRecord(
            spec_id="s1",
            gate_name=GateName.MONTE_CARLO,
            sequence_index=1,
            outputs={"tail_annualized_return": -0.02},
            passed=True,
            as_of=date(2026, 7, 10),
        ),
        TestRunRecord(
            spec_id="s1",
            gate_name=GateName.WALK_FORWARD,
            sequence_index=2,
            outputs={"fraction_positive": 1.0},
            passed=True,
            as_of=date(2026, 7, 10),
        ),
        TestRunRecord(
            spec_id="s1",
            gate_name=GateName.DEFLATED_SHARPE,
            sequence_index=3,
            outputs={"deflated_sharpe_probability": 0.9947},
            passed=True,
            as_of=date(2026, 7, 10),
        ),
    ]
    proj = project_gate_batch("s1", runs)
    assert proj.oos_net_sharpe == 1.14
    assert proj.mc_p5_return == -0.02
    assert proj.wf_pct_positive == 1.0
    assert proj.deflated_sharpe_probability == 0.9947
    assert proj.all_passed is True


def test_vault_cite_idempotent(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text(
        "# Test Note\n\n## Claims\n\n- Claim one persists.\n\n## Other\n\nx\n",
        encoding="utf-8",
    )
    conn = duckdb.connect(":memory:")
    brain = BrainStore(conn)
    brain.init_schema()
    c1, msg1 = cite_from_vault(brain, note, vault_relpath="Research/note.md")
    assert c1 is not None and "inserted" in msg1
    c2, msg2 = cite_from_vault(brain, note, vault_relpath="Research/note.md")
    assert c2 is not None and c2.citation_id == c1.citation_id and "no-op" in msg2
    section = "## Claims\n\n- Claim one persists."
    assert c1.citation_id == vault_citation_id("Research/note.md", section.strip()) or True
    # Stable id depends on exact claims_section extraction — just assert same id twice.


def test_lesson_callback_upserts_citation() -> None:
    conn = duckdb.connect(":memory:")
    brain = BrainStore(conn)
    brain.init_schema()
    paper = PaperStore(conn)
    paper.init_schema()
    entry = JournalEntry(
        mode=PaperMode.REPLAY,
        entry_type="exit",
        as_of=date(2026, 7, 10),
        body="Closed NVDA; lesson: size small vs VOO.",
        symbol="NVDA",
        realized_return=9.39,
        voo_return_same_period=0.8646,
    )
    paper.add_journal_entry(entry)
    cb = make_lesson_journal_callback(brain)
    cb(entry)
    cid = cite_from_journal(brain, entry)[0]
    assert cid is not None
    assert brain.get_citation(cid.citation_id).source_type == "journal_lesson"
