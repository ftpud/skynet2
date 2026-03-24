import json
import os
from datetime import datetime
from pathlib import Path

COMMAND_NAME = "room_post"
DESCRIPTION = (
    "Post a message to the shared meeting room, visible to all agents. "
    "Parameters: content (required), type (optional: message|analysis|proposal|"
    "code|review|question|decision|done — use 'done' to signal your contribution "
    "for this meeting is complete). "
    "Author and round number are set automatically from env vars."
)
USAGE_EXAMPLE = (
    '{"action":"command","name":"room_post","parameters":{"content":"My analysis shows...","type":"analysis"}} '
    'or {"action":"command","name":"room_post","parameters":{"content":"I believe we reached consensus.","type":"done"}}'
)

VALID_TYPES = {
    "message", "analysis", "proposal", "code",
    "review", "question", "decision", "done",
}


def execute(parameters: dict) -> str:
    room_file = os.environ.get("SWARM_ROOM_FILE", "")
    if not room_file:
        return "ERROR: SWARM_ROOM_FILE env var not set — are you running inside swarm.py?"

    if not isinstance(parameters, dict):
        return "ERROR: parameters must be an object"

    content = parameters.get("content", "")
    if not content or not isinstance(content, str):
        return "ERROR: 'content' is required"

    post_type = str(parameters.get("type", "message")).lower()
    if post_type not in VALID_TYPES:
        post_type = "message"

    author = os.environ.get("SWARM_AGENT_NAME", "unknown")
    try:
        round_num = int(os.environ.get("SWARM_ROUND", "1"))
    except ValueError:
        round_num = 1

    entry = {
        "round": round_num,
        "author": author,
        "type": post_type,
        "content": content.strip(),
        "timestamp": datetime.now().isoformat(),
    }

    try:
        path = Path(room_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)
            f.write("\n")
    except OSError as exc:
        return f"ERROR: cannot write to room file: {exc}"

    return f"OK: posted to room (author={author}, round={round_num}, type={post_type})"

