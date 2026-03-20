from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_OUTPUT_CHARS = 2000

COMMAND_NAME = "read_file"
DESCRIPTION = "Read a UTF-8 text file from disk and return its contents."
USAGE_EXAMPLE = '{"action":"command","name":"read_file","parameters":{"path":"README.md"}}'


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS]


def _error(message: str) -> str:
    return _truncate(f"ERROR: {message}")


def execute(parameters: dict[str, Any]) -> str:
    try:
        if not isinstance(parameters, dict):
            return _error("parameters must be an object")

        path_value = parameters.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            return _error("path must be a non-empty string")

        path = Path(path_value)
        if not path.exists():
            return _error(f"file not found: {path_value}")
        if not path.is_file():
            return _error(f"not a file: {path_value}")

        content = path.read_text(encoding="utf-8")
        return _truncate(content)
    except Exception as exc:
        return _error(str(exc))
