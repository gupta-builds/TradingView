"""AI harness package — LLM provider stack only lives here (C4).

``llm_client.py`` is the sole future provider-SDK import site. Cursor prereq ships
fixture mode + NotImplemented live path; Fable fills Router + structured bind.
"""

from research_data.agents.assemble import (
    AnalystInputBundle,
    AssembleError,
    assemble_symbol_input,
    quality_blocks_llm,
)
from research_data.agents.runner import run_analyze_symbol

__all__ = [
    "AnalystInputBundle",
    "AssembleError",
    "assemble_symbol_input",
    "quality_blocks_llm",
    "run_analyze_symbol",
]
