import subprocess

COMMAND_NAME = "linux_command"
DESCRIPTION = "Run a safe Linux shell command and return captured output."
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

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
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
