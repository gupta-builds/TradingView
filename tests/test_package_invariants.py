"""CI canary: year-ahead packages import cleanly and stay on the math-first map.

These tests are cheap and fail loudly if a core module disappears from main.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_MODULES = (
    "research_data.models",
    "research_data.storage",
    "research_data.quality",
    "research_data.read_api",
    "research_data.evidence",
    "research_data.benchmark",
    "research_data.cli",
    "research_data.brain",
    "research_data.factors",
    "research_data.fundamentals",
    "research_data.gates",
    "research_data.paper",
    "research_data.strategies",
    "research_data.strategies.quality_momentum",
    "research_data.kronos_reserved",
    "research_data.providers.polygon",
    "research_data.providers.csv_fixture",
)

REQUIRED_PATHS = (
    "Docs/YEAR_AHEAD_BASE.md",
    "Docs/GITHUB_WORKFLOW.md",
    "Docs/PHASE2_STRATEGY_PACK.md",
    "scripts/run_quality_momentum_study.py",
    ".github/workflows/ci.yml",
    "config/assets.toml",
    "config/providers.toml",
    ".kiro/specs/data-ingestion-foundation/tasks.md",
)


@pytest.mark.parametrize("module_name", REQUIRED_MODULES)
def test_required_module_imports(module_name: str) -> None:
    mod = importlib.import_module(module_name)
    assert mod is not None


@pytest.mark.parametrize("rel_path", REQUIRED_PATHS)
def test_required_paths_exist(rel_path: str) -> None:
    path = PROJECT_ROOT / rel_path
    assert path.is_file(), f"missing required path: {rel_path}"


def test_universe_has_fourteen_symbols() -> None:
    from research_data.config import load_config

    config = load_config()
    assert len(config.universe.symbols) == 14
    assert "VOO" in config.universe.symbols
    assert "BRKB" in config.universe.symbols


def test_kronos_module_has_no_inference_imports() -> None:
    """Kronos stays reserved: no torch/transformers/from_pretrained in that file."""
    source = (PROJECT_ROOT / "src/research_data/kronos_reserved.py").read_text(
        encoding="utf-8"
    )
    forbidden = ("torch", "transformers", "from_pretrained", "NeoQuasar", "huggingface")
    lowered = source.lower()
    for token in forbidden:
        assert token.lower() not in lowered, f"kronos_reserved must not reference {token}"


def test_no_prediction_market_packages() -> None:
    src = PROJECT_ROOT / "src" / "research_data"
    names = {p.name.lower() for p in src.rglob("*") if p.is_file() or p.is_dir()}
    for banned in ("kalshi", "polymarket", "prediction_market"):
        assert not any(banned in n for n in names), f"found banned path fragment: {banned}"
