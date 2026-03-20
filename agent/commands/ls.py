from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_OUTPUT_CHARS = 2000

COMMAND_NAME = "ls"
DESCRIPTION = "List files and directories in a target directory."
USAGE_EXAMPLE = '{"action":"command","name":"ls","parameters":{"path":"."}}'


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS]


def _error(message: str) -> str:
    return _truncate(f"ERROR: {message}")


def execute(parameters: dict[str, Any]) -> str:
    try:
        if not isinstance(parameters, dict):
            return _error("parameters must be an object")

        path_value = parameters.get("path", ".")
        if not isinstance(path_value, str) or not path_value.strip():
            return _error("path must be a non-empty string")

        path = Path(path_value)
        if not path.exists():
            return _error(f"path not found: {path_value}")
        if not path.is_dir():
            return _error(f"not a directory: {path_value}")

        entries = []
        for entry in sorted(path.iterdir(), key=lambda item: item.name.lower()):
            suffix = "/" if entry.is_dir() else ""
            entries.append(f"{entry.name}{suffix}")

        return _truncate("\n".join(entries) if entries else "(empty)")
    except Exception as exc:
        return _error(str(exc))
