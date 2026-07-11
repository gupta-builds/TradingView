"""Security and scope boundary tests (Tasks 13.1–13.2).

Requirements: 14.1, 14.5, 16.1–16.6
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, "src")

from research_data.cli import CLIError, app, verify_env_gitignore
from research_data.config import ConfigError, ProviderConfig, validate_api_key

runner = CliRunner()
_EXEC_RE = re.compile(r"\b(BUY NOW|SELL NOW|BUY|SELL|HOLD)\b", re.IGNORECASE)
_PREDICTIVE_RE = re.compile(
    r"\b(guaranteed|risk-free|will rise|will fall|sure thing)\b",
    re.IGNORECASE,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestSecurityAndScope:
    def test_env_listed_in_gitignore(self):
        gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        lines = [
            ln.strip()
            for ln in gitignore.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assert ".env" in lines

    def test_verify_env_gitignore_passes_for_project(self):
        verify_env_gitignore(PROJECT_ROOT)

    def test_verify_env_gitignore_refuses_when_missing(self, tmp_path):
        (tmp_path / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
        with pytest.raises(CLIError, match=r"\.env"):
            verify_env_gitignore(tmp_path)

    def test_api_keys_from_env_only(self, monkeypatch):
        cfg = ProviderConfig(
            source_name="polygon",
            source_url="https://api.polygon.io",
            license_note="test",
            requires_api_key=True,
            rate_limit=5,
            adjustment_policy="split_dividend_adjusted",
            api_key_env_var="POLYGON_API_KEY",
        )
        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        with pytest.raises(ConfigError, match="POLYGON_API_KEY"):
            validate_api_key(cfg)
        monkeypatch.setenv("POLYGON_API_KEY", "dummy")
        validate_api_key(cfg)  # should not raise

    def test_no_execution_language_in_cli_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # Ingestion commands: keep historical BUY/SELL/HOLD ban.
        ingest_cmds = ("init-db", "ingest-prices", "audit-prices", "benchmark")
        for cmd in ingest_cmds:
            r = runner.invoke(app, [cmd, "--help"])
            assert r.exit_code == 0, r.output
            assert _EXEC_RE.search(r.output) is None
        # Desk commands (Phase 3): HOLD is a legal ActionLabel — ban BUY/SELL only.
        desk_ban = re.compile(r"\b(BUY NOW|SELL NOW|BUY|SELL)\b", re.IGNORECASE)
        for cmd in (
            "propose",
            "approve",
            "reject",
            "decide",
            "analyze-symbol",
            "critique-spec",
            "cite-add",
        ):
            r = runner.invoke(app, [cmd, "--help"])
            assert r.exit_code == 0, r.output
            assert desk_ban.search(r.output) is None

    def test_no_predictive_language_in_cli_help(self):
        result = runner.invoke(app, ["--help"])
        assert _PREDICTIVE_RE.search(result.output) is None

    def test_no_llm_imports_outside_agents_package(self):
        """Extended C4 boundary (Phase 3)."""
        llm_patterns = [
            re.compile(r"openai", re.I),
            re.compile(r"anthropic", re.I),
            re.compile(r"langchain", re.I),
            re.compile(r"litellm", re.I),
            re.compile(r"instructor", re.I),
            re.compile(r"pydantic_ai", re.I),
            re.compile(r"google\.generativeai", re.I),
        ]
        offenders = []
        for path in (PROJECT_ROOT / "src" / "research_data").rglob("*.py"):
            rel = path.relative_to(PROJECT_ROOT / "src" / "research_data")
            if rel.parts and rel.parts[0] == "agents":
                continue
            text = path.read_text(encoding="utf-8")
            for pat in llm_patterns:
                if pat.search(text):
                    offenders.append(f"{rel}: {pat.pattern}")
        assert offenders == []

    def test_no_broker_sdk_in_dependencies(self):
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        forbidden = [
            "alpaca",
            "ib_insync",
            "ibapi",
            "ccxt",
            "robinhood",
            "tda-api",
            "tradier",
            "metaapi",
            "oandapy",
        ]
        lower = pyproject.lower()
        for name in forbidden:
            assert name not in lower, f"Forbidden broker dependency: {name}"

    def test_no_intraday_tick_options_paths(self):
        src = PROJECT_ROOT / "src" / "research_data"
        offenders = []
        patterns = [
            re.compile(r"\bintraday\b", re.I),
            re.compile(r"\btick_data\b", re.I),
            re.compile(r"\boptions_chain\b", re.I),
            re.compile(r"\bfutures_contract\b", re.I),
            re.compile(r"\bcrypto_pair\b", re.I),
        ]
        for path in src.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for pat in patterns:
                if pat.search(text):
                    offenders.append(f"{path.name}: {pat.pattern}")
        assert offenders == []

    def test_no_llm_calls_in_ingestion_modules(self):
        modules = [
            "models.py",
            "config.py",
            "storage.py",
            "normalization.py",
            "calendar.py",
            "quality.py",
            "read_api.py",
            "evidence.py",
            "benchmark.py",
        ]
        llm_patterns = [
            re.compile(r"openai", re.I),
            re.compile(r"anthropic", re.I),
            re.compile(r"langchain", re.I),
            re.compile(r"litellm", re.I),
            re.compile(r"ChatCompletion", re.I),
        ]
        src = PROJECT_ROOT / "src" / "research_data"
        for name in modules:
            text = (src / name).read_text(encoding="utf-8")
            for pat in llm_patterns:
                assert pat.search(text) is None, f"{name} matched {pat.pattern}"
