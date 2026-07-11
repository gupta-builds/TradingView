"""Deterministic citation ingest — vault notes, journal lessons, manual add.

Lives outside ``agents/`` (D1): zero LLM calls. BrainStore is insert-only for
citations; stable vault ids use path + claims-section content hash.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from research_data.brain.models import Citation
from research_data.brain.store import BrainStore, BrainStoreError
from research_data.paper.models import JournalEntry

_CLAIMS_HEADING = re.compile(r"^##\s+Claims\s*$", re.MULTILINE | re.IGNORECASE)


def _normalize_title_author(title: str, authors: str | None) -> str:
    a = (authors or "").strip().lower()
    return f"{title.strip().lower()}|{a}"


def warn_duplicate_citation(store: BrainStore, title: str, authors: str | None) -> str | None:
    """Return a warning string if a normalized title/author match exists."""
    key = _normalize_title_author(title, authors)
    for existing in store.list_citations():
        if _normalize_title_author(existing.title, existing.authors) == key:
            return (
                f"Possible duplicate citation: existing id={existing.citation_id} "
                f"title={existing.title!r}"
            )
    return None


def add_citation(
    store: BrainStore,
    *,
    source_type: str,
    title: str,
    claims: list[str] | None = None,
    url: str | None = None,
    authors: str | None = None,
    license_note: str | None = None,
    retrieved_at: datetime | None = None,
) -> tuple[Citation, str | None]:
    """Manual cite-add. Returns (citation, optional duplicate warning)."""
    warning = warn_duplicate_citation(store, title, authors)
    citation = Citation(
        source_type=source_type,
        title=title,
        url=url,
        authors=authors,
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
        claims=list(claims or []),
        license_note=license_note,
    )
    store.add_citation(citation)
    return citation, warning


def _extract_claims_section(markdown: str) -> tuple[str, list[str]]:
    """Return (claims_section_raw, claim_bullets). Empty claims allowed at ingest."""
    match = _CLAIMS_HEADING.search(markdown)
    if not match:
        return "", []
    start = match.end()
    rest = markdown[start:]
    next_h2 = re.search(r"^##\s+", rest, re.MULTILINE)
    section = rest[: next_h2.start()] if next_h2 else rest
    claims: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*")):
            claims.append(stripped.lstrip("-* ").strip())
    return section.strip(), claims


def vault_citation_id(vault_relpath: str, claims_section: str) -> str:
    """Stable id = hash(path + content_hash(claims_section)). No mtime."""
    content_hash = hashlib.sha256(claims_section.encode("utf-8")).hexdigest()
    raw = f"{vault_relpath}\0{content_hash}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def cite_from_vault(
    store: BrainStore,
    vault_path: str | Path,
    *,
    vault_relpath: str | None = None,
    source_type: str = "vault_note",
) -> tuple[Citation | None, str]:
    """Ingest a vault markdown file. Re-ingest with same claims = no-op.

    Returns (citation or None if already present, status message).
    """
    path = Path(vault_path)
    text = path.read_text(encoding="utf-8")
    rel = vault_relpath or path.name
    claims_section, claims = _extract_claims_section(text)
    cid = vault_citation_id(rel, claims_section)
    try:
        existing = store.get_citation(cid)
        return existing, f"no-op: citation {cid} already present"
    except BrainStoreError:
        pass

    # Title: first H1 or filename
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem

    citation = Citation(
        citation_id=cid,
        source_type=source_type,
        title=title,
        url=None,
        authors=None,
        retrieved_at=datetime.now(timezone.utc),
        claims=claims,
        license_note=f"vault:{rel}",
    )
    store.add_citation(citation)
    return citation, f"inserted citation {cid}"


def journal_lesson_citation_id(entry_id: str) -> str:
    return hashlib.sha256(f"journal_lesson:{entry_id}".encode()).hexdigest()[:32]


def cite_from_journal(
    store: BrainStore,
    entry: JournalEntry,
) -> tuple[Citation | None, str]:
    """Upsert journal_lesson citation keyed by journal_entry_id."""
    if entry.entry_type not in {"lesson", "exit"}:
        return None, f"skip: entry_type={entry.entry_type} not lesson/exit"
    cid = journal_lesson_citation_id(entry.entry_id)
    try:
        existing = store.get_citation(cid)
        return existing, f"no-op: journal citation {cid} already present"
    except BrainStoreError:
        pass

    title = (
        f"Journal {entry.entry_type}: {entry.symbol or 'n/a'} "
        f"as_of {entry.as_of.isoformat()}"
    )
    citation = Citation(
        citation_id=cid,
        source_type="journal_lesson",
        title=title,
        url=None,
        authors=None,
        retrieved_at=datetime.now(timezone.utc),
        claims=[entry.body.strip()] if entry.body.strip() else [],
        license_note=f"journal_entry_id={entry.entry_id}",
    )
    store.add_citation(citation)
    return citation, f"inserted journal citation {cid}"


def make_lesson_journal_callback(store: BrainStore):
    """Closure for PaperEngine.on_lesson_journaled (D5)."""

    def _cb(entry: JournalEntry) -> None:
        cite_from_journal(store, entry)

    return _cb
