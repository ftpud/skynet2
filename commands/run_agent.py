import json
import subprocess
import sys
from pathlib import Path

COMMAND_NAME = "run_agent"
DESCRIPTION = "Run another configured agent with a prompt and return its final answer."
USAGE_EXAMPLE = '{"action":"command","name":"run_agent","parameters":{"agent":"reviewer","prompt":"Review this plan"}}'


def execute(parameters: dict) -> str:
    agent = parameters.get("agent")
    prompt = parameters.get("prompt")

    if not agent or not isinstance(agent, str):
        return "ERROR: Missing or invalid 'agent' parameter"
    if prompt is None or not isinstance(prompt, str):
        return "ERROR: Missing or invalid 'prompt' parameter"

    root = Path(__file__).resolve().parent.parent
    ahent_path = root / "ahent.py"

    if not ahent_path.exists():
        return f"ERROR: ahent.py not found at {ahent_path}"

    try:
        proc = subprocess.run(
            [sys.executable, str(ahent_path), "--agent", agent, "--prompt", prompt],
            capture_output=True,
            text=True,
            cwd=str(root),
            check=False,
        )
    except Exception as e:
        return f"ERROR: Failed to run ahent.py: {e}"

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if proc.returncode != 0:
        if stderr:
            return f"ERROR: ahent.py exited with code {proc.returncode}: {stderr}"
        return f"ERROR: ahent.py exited with code {proc.returncode}"

    if not stdout:
        return "ERROR: ahent.py returned no output"

    # If output is JSON, try to return final_answer content when present.
    try:
        data = json.loads(stdout)
        if isinstance(data, dict) and data.get("action") == "final_answer":
            content = data.get("content")
            if isinstance(content, str):
                return content
        return stdout
    except Exception:
        return stdout
