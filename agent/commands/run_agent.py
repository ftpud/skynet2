from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_OUTPUT_CHARS = 2000
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_CHILDREN = 5

COMMAND_NAME = "run_agent"
DESCRIPTION = "Run a child agent process with config and prompt, returning only its final answer."
USAGE_EXAMPLE = '{"action":"command","name":"run_agent","parameters":{"config":"agent/config.yaml","prompt":"Review this code","role":"reviewer"}}'


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS]


def _error(message: str) -> str:
    return _truncate(f"ERROR: {message}")


def _extract_final_answer(output: str) -> str:
    text = output.strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("FINAL_ANSWER:"):
            return line[len("FINAL_ANSWER:") :].strip()
    return lines[-1] if lines else text


def execute(parameters: dict[str, Any]) -> str:
    try:
        if not isinstance(parameters, dict):
            return _error("parameters must be an object")

        config_path = parameters.get("config")
        prompt = parameters.get("prompt")
        role = parameters.get("role")

        if not isinstance(config_path, str) or not config_path.strip():
            return _error("config must be a non-empty string")
        if not isinstance(prompt, str) or not prompt.strip():
            return _error("prompt must be a non-empty string")
        if role is not None and not isinstance(role, str):
            return _error("role must be a string when provided")

        depth = int(os.environ.get("AGENT_DEPTH", "0"))
        child_count = int(os.environ.get("AGENT_CHILD_COUNT", "0"))
        max_depth = int(os.environ.get("MAX_AGENT_DEPTH", str(DEFAULT_MAX_DEPTH)))
        max_children = int(os.environ.get("MAX_CHILD_AGENTS", str(DEFAULT_MAX_CHILDREN)))
        timeout = int(os.environ.get("CHILD_AGENT_TIMEOUT", str(DEFAULT_TIMEOUT)))

        if depth + 1 > max_depth:
            return _error("max agent depth exceeded")
        if child_count + 1 > max_children:
            return _error("max child agents exceeded")

        resolved_config = Path(config_path)
        if not resolved_config.exists() or not resolved_config.is_file():
            return _error(f"config file not found: {config_path}")

        agent_script = Path(__file__).resolve().parent.parent / "agent.py"
        cmd = [sys.executable, str(agent_script), "--config", str(resolved_config), "--prompt", prompt]

        env = os.environ.copy()
        env["AGENT_DEPTH"] = str(depth + 1)
        env["AGENT_CHILD_COUNT"] = str(child_count + 1)
        env["MAX_AGENT_DEPTH"] = str(max_depth)
        env["MAX_CHILD_AGENTS"] = str(max_children)
        env["CHILD_AGENT_TIMEOUT"] = str(timeout)

        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        combined_output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
        if completed.returncode != 0 and not combined_output:
            return _error(f"child agent failed with exit code {completed.returncode}")

        final_answer = _extract_final_answer(combined_output)
        if not final_answer:
            return _error("child agent returned empty output")

        return _truncate(f"FINAL_ANSWER: {final_answer}")
    except subprocess.TimeoutExpired:
        return _error("child agent timed out")
    except Exception as exc:
        return _error(str(exc))
