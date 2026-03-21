import subprocess

COMMAND_NAME = "multiple_linux_commands"
DESCRIPTION = "Run multiple Linux shell commands in sequence and return all captured outputs chained together."
USAGE_EXAMPLE = '{"action":"command","name":"multiple_linux_commands","parameters":{"commands":["ls -la","pwd"]}}'

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

        commands = parameters.get("commands")
        if not commands or not isinstance(commands, list):
            return "ERROR: 'commands' is required and must be a list"

        if not all(isinstance(c, str) for c in commands):
            return "ERROR: all commands must be strings"

        results = []

        for i, command in enumerate(commands):
            lower = command.lower()
            blocked = False
            for pattern in _BLOCKED:
                if pattern in lower:
                    results.append(f"[Command {i + 1}]: {command}\nERROR: blocked unsafe command pattern: {pattern}")
                    blocked = True
                    break

            if blocked:
                continue

            try:
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

                results.append(f"[Command {i + 1}]: {command}\n{combined}")

            except subprocess.TimeoutExpired:
                results.append(f"[Command {i + 1}]: {command}\nERROR: command timed out")
            except Exception as e:
                results.append(f"[Command {i + 1}]: {command}\nERROR: {e}")

        return "\n\n".join(results) if results else "(no commands executed)"

    except Exception as e:
        return f"ERROR: {e}"
