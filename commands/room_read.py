import json
import os
from pathlib import Path

COMMAND_NAME = "room_read"
DESCRIPTION = (
    "Read the current shared meeting room — all posts from all agents so far. "
    "Optional: last_n (int) to limit to the most recent N posts. "
    "Requires SWARM_ROOM_FILE environment variable (set automatically by swarm.py)."
)
USAGE_EXAMPLE = (
    '{"action":"command","name":"room_read","parameters":{}} '
    'or {"action":"command","name":"room_read","parameters":{"last_n":10}}'
)


def execute(parameters: dict) -> str:
    room_file = os.environ.get("SWARM_ROOM_FILE", "")
    if not room_file:
        return "ERROR: SWARM_ROOM_FILE env var not set — are you running inside swarm.py?"

    path = Path(room_file)
    if not path.exists():
        return "(room is empty — no posts yet)"

    posts: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        posts.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError as exc:
        return f"ERROR: cannot read room file: {exc}"

    if not posts:
        return "(room is empty — no posts yet)"

    # Optional tail filter
    try:
        last_n = int((parameters or {}).get("last_n", 0))
        if last_n > 0:
            posts = posts[-last_n:]
    except (TypeError, ValueError):
        pass

    sep = "─" * 64
    lines = [
        "═" * 64,
        f"MEETING ROOM  ({len(posts)} post{'s' if len(posts) != 1 else ''})",
        "═" * 64,
    ]
    for post in posts:
        rnd = post.get("round", "?")
        author = post.get("author", "unknown")
        ptype = post.get("type", "message")
        content = post.get("content", "").strip()
        lines.append(f"\n[Round {rnd}] {author}  ({ptype})")
        lines.append(sep)
        lines.append(content)

    lines.append("\n" + "═" * 64)
    return "\n".join(lines)

