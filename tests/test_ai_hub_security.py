"""Structural guards for Phase 3 AI hub (C4, D3)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from research_data.gates.harness import GateHarness, GateHarnessConfig
from research_data.gates.oos import OOSParams
from research_data.gates.monte_carlo import MonteCarloParams
from research_data.gates.walk_forward import WalkForwardParams
from research_data.gates.deflated_sharpe import DeflatedSharpeParams

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src" / "research_data"

_LLM_IMPORT_RE = re.compile(
    r"\b(litellm|openai|anthropic|instructor|pydantic_ai|google\.generativeai)\b",
    re.I,
)


def test_llm_imports_only_under_agents() -> None:
    """C4: LLM stack symbols only under agents/ (llm_client is the litellm site)."""
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC)
        text = path.read_text(encoding="utf-8")
        if _LLM_IMPORT_RE.search(text):
            if rel.parts[0] != "agents":
                offenders.append(str(rel))
            # litellm itself may only appear in llm_client.py once Fable lands;
            # Cursor prereq must not import litellm anywhere yet.
            if "litellm" in text.lower() and path.name != "llm_client.py":
                offenders.append(f"{rel}: litellm outside llm_client.py")
    assert offenders == []


def test_kronos_reserved_not_imported_under_agents() -> None:
    for path in (SRC / "agents").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "kronos_reserved" not in text, path.name


def test_gate_harness_defaults_match_literature() -> None:
    cfg = GateHarnessConfig()
    assert cfg.oos == OOSParams()
    assert cfg.monte_carlo == MonteCarloParams()
    assert cfg.walk_forward == WalkForwardParams()
    assert cfg.deflated_sharpe == DeflatedSharpeParams()


def test_no_nondefault_gate_params_outside_tests() -> None:
    """D3: GateHarnessConfig / *Params never constructed with kwargs outside tests/."""
    param_ctors = {
        "GateHarnessConfig",
        "OOSParams",
        "MonteCarloParams",
        "WalkForwardParams",
        "DeflatedSharpeParams",
    }
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in param_ctors and node.keywords:
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}:{name}")
    assert offenders == [], offenders


def test_strategy_hooks_do_not_read_universe_from_params() -> None:
    """D3: hooks must not pull universe/symbols/cost-bps from params dict."""
    strategies = SRC / "strategies"
    if not strategies.is_dir():
        pytest.skip("no strategies dir")
    banned = re.compile(
        r"""params\s*\[\s*['\"]?(universe|symbols|cost_bps|cost-bps)['\"]?\s*\]"""
        r"""|params\.get\(\s*['\"]?(universe|symbols|cost_bps)['\"]?""",
        re.I,
    )
    offenders = []
    for path in strategies.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if banned.search(text):
            offenders.append(path.name)
    assert offenders == []
