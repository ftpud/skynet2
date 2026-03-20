from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_OUTPUT_CHARS = 2000

COMMAND_NAME = "write_file"
DESCRIPTION = "Write UTF-8 text content to a file, creating parent directories if needed."
USAGE_EXAMPLE = '{"action":"command","name":"write_file","parameters":{"path":"notes.txt","content":"hello"}}'


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS]


def _error(message: str) -> str:
    return _truncate(f"ERROR: {message}")


def execute(parameters: dict[str, Any]) -> str:
    try:
        if not isinstance(parameters, dict):
            return _error("parameters must be an object")

        path_value = parameters.get("path")
        content = parameters.get("content")

        if not isinstance(path_value, str) or not path_value.strip():
            return _error("path must be a non-empty string")
        if not isinstance(content, str):
            return _error("content must be a string")

        path = Path(path_value)
        if path.exists() and path.is_dir():
            return _error(f"path is a directory: {path_value}")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return _truncate(f"WROTE: {path_value}")
    except Exception as exc:
        return _error(str(exc))
