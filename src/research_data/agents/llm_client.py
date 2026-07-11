"""LLM client choke point (C4).

Sole ``litellm`` import site in the package. ``FixtureLLMClient`` is the CI
default (``RESEARCH_DATA_LLM=fixture``); ``LiveLLMClient`` wraps a
``litellm.Router`` (Gemini Flash → Groq → Ollama) with structured output
bound to Pydantic models via ``instructor``. API keys are read from the
environment by litellm itself — never passed through code or logged.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

#: Hard cap on completion tokens per call (E3 cost control). Gemini 3.x Flash
#: spends "thinking" tokens from the same completion budget, so this must be
#: comfortably above the visible JSON size (2048 truncated in live smoke).
DEFAULT_MAX_TOKENS = 8192

#: Consecutive failed calls after which the live client refuses further calls.
ROUTER_MAX_FAILURES = 2

#: Confirmed current Gemini Flash litellm alias (gemini-2.0-flash retired 2026-06-01).
DEFAULT_GEMINI_MODEL = "gemini/gemini-3.5-flash"
DEFAULT_GROQ_MODEL = "groq/llama-3.3-70b-versatile"
DEFAULT_OLLAMA_MODEL = "ollama/llama3.1"


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


def _build_model_list() -> tuple[list[dict[str, Any]], list[dict[str, list[str]]]]:
    """Router deployments from env — only providers whose keys are present."""
    deployments: list[dict[str, Any]] = []
    if os.environ.get("GEMINI_API_KEY"):
        deployments.append(
            {
                "model_name": "desk-gemini",
                "litellm_params": {
                    "model": os.environ.get("LLM_MODEL", DEFAULT_GEMINI_MODEL),
                },
            }
        )
    if os.environ.get("GROQ_API_KEY"):
        deployments.append(
            {
                "model_name": "desk-groq",
                "litellm_params": {
                    "model": os.environ.get("LLM_MODEL_GROQ", DEFAULT_GROQ_MODEL),
                },
            }
        )
    if os.environ.get("OLLAMA_API_BASE"):
        deployments.append(
            {
                "model_name": "desk-ollama",
                "litellm_params": {
                    "model": os.environ.get("LLM_MODEL_OLLAMA", DEFAULT_OLLAMA_MODEL),
                    "api_base": os.environ["OLLAMA_API_BASE"],
                },
            }
        )
    if not deployments:
        raise LLMClientError(
            "RESEARCH_DATA_LLM=live but no provider key found "
            "(GEMINI_API_KEY / GROQ_API_KEY / OLLAMA_API_BASE)"
        )
    names = [d["model_name"] for d in deployments]
    fallbacks = [{names[0]: names[1:]}] if len(names) > 1 else []
    return deployments, fallbacks


class LiveLLMClient:
    """litellm.Router behind instructor — structured output, fail-fast on repeat errors.

    ``structured_create`` is injectable for offline tests; the default builds
    the Router lazily so fixture-mode processes never import litellm.
    """

    def __init__(
        self,
        structured_create: Callable[..., BaseModel] | None = None,
    ) -> None:
        self._consecutive_failures = 0
        if structured_create is not None:
            self._create = structured_create
            self._primary = "test-stub"
            return

        import logging  # noqa: PLC0415

        import instructor  # noqa: PLC0415 — lazy: live mode only
        import litellm  # noqa: PLC0415 — sole litellm import site (C4)

        litellm.suppress_debug_info = True
        litellm.drop_params = True  # fallbacks may not share every sampling param
        logging.getLogger("LiteLLM").setLevel(logging.ERROR)
        deployments, fallbacks = _build_model_list()
        router = litellm.Router(
            model_list=deployments,
            fallbacks=fallbacks,
            num_retries=0,
        )
        client = instructor.from_litellm(router.completion, mode=instructor.Mode.JSON)
        self._create = client.chat.completions.create
        self._primary = deployments[0]["model_name"]

    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
    ) -> T:
        if self._consecutive_failures >= ROUTER_MAX_FAILURES:
            raise LLMClientError(
                f"live LLM disabled after {self._consecutive_failures} consecutive "
                "failures (fail-fast; restart the process to retry)"
            )
        try:
            result = self._create(
                model=self._primary,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_model=response_model,
                max_tokens=DEFAULT_MAX_TOKENS,
                temperature=0.0,
                # Bounded thinking on reasoning models (Gemini 3.x); providers
                # without the knob drop it via litellm.drop_params.
                reasoning_effort="low",
            )
        except Exception as e:  # provider errors are opaque; never re-log payloads
            self._consecutive_failures += 1
            raise LLMClientError(f"live LLM call failed: {type(e).__name__}: {e}") from e
        self._consecutive_failures = 0
        return result  # type: ignore[return-value]


def get_llm_client(
    canned: dict[type[BaseModel], BaseModel] | None = None,
) -> FixtureLLMClient | LiveLLMClient:
    mode = os.environ.get("RESEARCH_DATA_LLM", "fixture").strip().lower()
    if mode in {"fixture", "off", "none", ""}:
        return FixtureLLMClient(canned=canned)
    if mode == "live":
        return LiveLLMClient()
    raise LLMClientError(f"Unknown RESEARCH_DATA_LLM={mode!r}; use fixture|live")
