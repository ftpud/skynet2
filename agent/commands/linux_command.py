from __future__ import annotations

import subprocess
from typing import Any

MAX_OUTPUT_CHARS = 2000
TIMEOUT_SECONDS = 10
BLOCKED_PATTERNS = [
    "rm -rf",
    "shutdown",
    "reboot",
    "mkfs",
    ":(){ :|:& };:",
]

COMMAND_NAME = "linux_command"
DESCRIPTION = "Run a non-destructive shell command with timeout and captured output."
USAGE_EXAMPLE = '{"action":"command","name":"linux_command","parameters":{"command":"pwd"}}'


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS]


def _error(message: str) -> str:
    return _truncate(f"ERROR: {message}")


def execute(parameters: dict[str, Any]) -> str:
    try:
        if not isinstance(parameters, dict):
            return _error("parameters must be an object")

        command = parameters.get("command")
        if not isinstance(command, str) or not command.strip():
            return _error("command must be a non-empty string")

        normalized = command.lower()
        for pattern in BLOCKED_PATTERNS:
            if pattern in normalized:
                return _error(f"blocked command pattern: {pattern}")

        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        output = output.strip()
        if not output:
            output = f"EXIT_CODE: {completed.returncode}"
        elif completed.returncode != 0:
            output = f"EXIT_CODE: {completed.returncode}\n{output}"
        return _truncate(output)
    except subprocess.TimeoutExpired:
        return _error("command timed out")
    except Exception as exc:
        return _error(str(exc))
