"""Paper-test contracts: pre-approved theses, timed auto-entry, journal.

The paper book is the real test of knowledge. Rules baked in:

- Nothing enters the book without a pre-approved thesis (human approval),
  and auto-entry happens only inside the thesis's approved time window.
- Two modes share one schema: REPLAY (accelerated historical verification,
  journal written as-if-time-passed) and LIVE (real-calendar paper book with
  review jump-ahead hooks).
- Every exit journal entry must record what VOO returned over the same
  holding period — alpha honesty is not optional.
- Action vocabulary is fixed: WATCH | HOLD | ACCUMULATE | REDUCE | AVOID |
  INSUFFICIENT_DATA. No execution language anywhere.
"""

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
from research_data.paper.store import PaperStore, PaperStoreError
from research_data.paper.engine import PaperEngine, PaperEngineError

__all__ = [
    "ActionLabel",
    "JournalEntry",
    "PaperEngine",
    "PaperEngineError",
    "PaperFill",
    "PaperMode",
    "PaperStore",
    "PaperStoreError",
    "PositionEffect",
    "ReplayRun",
    "Thesis",
    "ThesisStatus",
]
