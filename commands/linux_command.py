import os
import subprocess

COMMAND_NAME = "linux_command"
DESCRIPTION = "Run a shell command and return captured output. Prefer dedicated file tools when available."
USAGE_EXAMPLE = '{"action":"command","name":"linux_command","parameters":{"command":"ls -la"}}'

_BLOCKED = [
    "rm -rf",
    "shutdown",
    "reboot",
    "mkfs",
    ":(){ :|:& };:",
]


def execute(parameters: dict) -> str:
    try:
        if not isinstance(parameters, dict):
            return "ERROR: parameters must be an object"

        command = parameters.get("command")
        if not command or not isinstance(command, str):
            return "ERROR: 'command' is required"

        lower = command.lower()
        for pattern in _BLOCKED:
            if pattern in lower:
                return f"ERROR: blocked unsafe command pattern: {pattern}"

        interactive = bool(parameters.get("interactive"))
        if interactive:
            shell = os.environ.get("SHELL") or "/bin/zsh"
            return (
                "ERROR: interactive shell handoff is not supported from this agent process. "
                f"Requested command for manual run in your current shell: {shell} -ic {command!r}"
            )

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

        out = (result.stdout or "")
        err = (result.stderr or "")
        combined = (out + ("\n" if out and err else "") + err).strip()
        if not combined:
            combined = "(no output)"

        return combined
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out"
    except Exception as e:
        return f"ERROR: {e}"
