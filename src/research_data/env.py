"""Safe .env loading for local development.

Loads KEY=VALUE pairs from a gitignored .env file into os.environ without
overriding variables that are already set, and without ever logging or
returning secret values. No third-party dependency.
"""

from __future__ import annotations

import os
from pathlib import Path


def _project_root() -> Path:
    """Project root is two levels up from src/research_data/."""
    return Path(__file__).resolve().parent.parent.parent


def load_dotenv(path: str | Path | None = None) -> list[str]:
    """Load environment variables from a .env file if it exists.

    Existing environment variables are never overridden. Values are never
    logged or echoed; only the variable *names* that were newly set are
    returned, so callers can report what was loaded without leaking secrets.

    Args:
        path: Path to the .env file. Defaults to <project root>/.env.

    Returns:
        Sorted list of variable names that were newly set (may be empty).
    """
    env_path = Path(path) if path is not None else _project_root() / ".env"
    if not env_path.is_file():
        return []

    loaded: list[str] = []
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or key in os.environ:
            continue
        os.environ[key] = value
        loaded.append(key)

    return sorted(loaded)
