"""LLM client choke point (C4).

Cursor prereq: fixture provider only — **no litellm import**. Fable adds
``litellm.Router`` (Gemini Flash → Groq → Ollama) behind ``RESEARCH_DATA_LLM=live``.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClientError(Exception):
    """Provider / fixture failures."""


class StructuredLLM(Protocol):
    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
    ) -> T: ...


class FixtureLLMClient:
    """Offline CI provider — returns a preloaded model instance."""

    def __init__(self, canned: dict[type[BaseModel], BaseModel] | None = None) -> None:
        self._canned = canned or {}
        self.invocation_count = 0

    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
    ) -> T:
        self.invocation_count += 1
        if response_model not in self._canned:
            raise LLMClientError(
                f"FixtureLLMClient has no canned response for {response_model.__name__}"
            )
        return self._canned[response_model]  # type: ignore[return-value]


class LiveLLMClient:
    """Placeholder — Fable implements litellm.Router + instructor/pydantic-ai here."""

    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
    ) -> T:
        raise LLMClientError(
            "Live LLM path not implemented in Cursor prereq; "
            "Fable fills agents/llm_client.py with litellm.Router"
        )


def get_llm_client(
    canned: dict[type[BaseModel], BaseModel] | None = None,
) -> FixtureLLMClient | LiveLLMClient:
    mode = os.environ.get("RESEARCH_DATA_LLM", "fixture").strip().lower()
    if mode in {"fixture", "off", "none", ""}:
        return FixtureLLMClient(canned=canned)
    if mode == "live":
        return LiveLLMClient()
    raise LLMClientError(f"Unknown RESEARCH_DATA_LLM={mode!r}; use fixture|live")


# max_tokens / Router fail-fast constants for Fable (documented, unused until live):
DEFAULT_MAX_TOKENS = 2048
ROUTER_MAX_FAILURES = 2
