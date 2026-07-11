"""Analyst prompt module — Fable fills system/user templates.

Reserved so import graph is stable; Cursor does not invent prompt text.
"""

ANALYST_SYSTEM_PROMPT = (
    "PLACEHOLDER — Fable replaces this with the evidence-bound analyst contract. "
    "Quote only numbers from the ScorePacket JSON; never invent metrics."
)
