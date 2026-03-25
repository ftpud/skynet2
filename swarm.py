#!/usr/bin/env python3
"""swarm.py — Multi-agent meeting room coordinator.

Runs multiple agents in a shared "room" where they read each other's posts,
build on them, and converge on a collective result.  Unlike the delegation
model (one agent hands off to another), every participant sees the same context
and self-selects what to contribute.

Quick start
-----------
    python swarm.py --topic "Design a Redis caching layer for the API"

    # Custom swarm config
    python swarm.py --config agents/swarm.yaml --topic "Refactor the auth module"

    # Resume / inspect a previous meeting
    python swarm.py --room-file ./rooms/my-meeting.jsonl --summary

Usage
-----
    --topic         Topic / task for the meeting (required unless --summary)
    --config        Path to swarm YAML config  [default: agents/swarm.yaml]
    --agent-dir     Path to skynet2 directory  [auto-detected]
    --room-file     Explicit room file path    [default: rooms/<slug>_<ts>.jsonl]
    --log-dir       Directory for logs         [default: ./logs]
    --summary       Print a formatted summary of an existing room and exit
    --provider      Override provider for all participants
    --model         Override model for all participants
    --verbose       Verbose coordinator output (agent stderr shown)
    -v              Alias for --verbose
"""

import argparse
import json
import logging
import logging.handlers
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml


# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging(log_dir: Path, verbose: bool) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"swarm_{ts}.log"

    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("swarm")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    logger.info("Swarm log → %s", log_file)
    return logger


# ── Room I/O ──────────────────────────────────────────────────────────────────

class SwarmRoom:
    """Append-only JSONL meeting room.  Thread-safe only for single-writer use."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def post(self, author: str, content: str, post_type: str = "message",
             round_num: int = 0) -> None:
        entry = {
            "round": round_num,
            "author": author,
            "type": post_type,
            "content": content.strip(),
            "timestamp": datetime.now().isoformat(),
        }
        with open(self.path, "a", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)
            f.write("\n")

    def posts(self) -> list[dict]:
        if not self.path.exists():
            return []
        result = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        result.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return result

    def done_agents(self) -> set[str]:
        """Return set of agents that have posted type=done at any point."""
        return {p["author"] for p in self.posts() if p.get("type") == "done"}

    def format(self) -> str:
        """Human-readable formatted view of the room."""
        all_posts = self.posts()
        if not all_posts:
            return "(room is empty)"

        sep = "─" * 68
        lines = [
            "═" * 68,
            f"  MEETING ROOM  ({len(all_posts)} posts)",
            "═" * 68,
        ]
        last_round = None
        for post in all_posts:
            rnd = post.get("round", "?")
            if rnd != last_round:
                last_round = rnd
                label = "SETUP" if rnd == 0 else f"ROUND {rnd}"
                lines.append(f"\n┌── {label} " + "─" * (58 - len(str(label))))
            author = post.get("author", "?")
            ptype = post.get("type", "message")
            content = post.get("content", "").strip()
            ts = post.get("timestamp", "")[:19]
            lines.append(f"\n│ {author}  [{ptype}]  {ts}")
            lines.append(sep)
            for ln in content.splitlines():
                lines.append(f"  {ln}")

        lines.append("\n" + "═" * 68)
        return "\n".join(lines)


# ── Coordinator ───────────────────────────────────────────────────────────────

class SwarmCoordinator:
    def __init__(
        self,
        config: dict,
        topic: str,
        room: SwarmRoom,
        agent_dir: Path,
        args: argparse.Namespace,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.topic = topic
        self.room = room
        self.agent_dir = agent_dir
        self.args = args
        self.log = logger

        self.participants: list[str] = config.get("participants", [])
        self.max_rounds: int = int(config.get("max_rounds", 4))
        self.done_threshold: int = int(config.get("done_threshold", len(self.participants)))
        self.response_timeout: float = float(config.get("response_timeout", 300))

        if not self.participants:
            raise ValueError("swarm config has no participants")

    # ── public entry point ────────────────────────────────────────────────────

    def run(self) -> None:
        self.log.info("═" * 68)
        self.log.info("SWARM MEETING starting")
        self.log.info("  topic        : %s", self.topic[:80])
        self.log.info("  participants : %s", ", ".join(self.participants))
        self.log.info("  max_rounds   : %d", self.max_rounds)
        self.log.info("  done_thresh  : %d", self.done_threshold)
        self.log.info("  room file    : %s", self.room.path)
        self.log.info("═" * 68)

        # Post the task to the room so all agents see it from round 1
        self.room.post("facilitator", self.topic, "task", round_num=0)
        self.log.info("[room] Facilitator posted topic")

        for round_num in range(1, self.max_rounds + 1):
            self.log.info("")
            self.log.info("─── Round %d / %d ───────────────────────────────────", round_num, self.max_rounds)
            self._run_round(round_num)

            # Consensus check after each full round
            done = self.room.done_agents()
            self.log.info("Done signals so far: %s / %d needed  (%s)",
                          len(done), self.done_threshold,
                          ", ".join(sorted(done)) if done else "none")
            if len(done) >= self.done_threshold:
                self.log.info("Consensus reached — ending meeting early")
                break
        else:
            self.log.info("Max rounds reached")

        # Print final formatted room to stdout
        print("\n" + self.room.format())
        self.log.info("Meeting complete.  Room file: %s", self.room.path)

    # ── round execution ───────────────────────────────────────────────────────

    def _run_round(self, round_num: int) -> None:
        for agent_name in self.participants:
            self.log.info("  Turn: %s", agent_name)
            try:
                answer = self._run_agent_turn(agent_name, round_num)
                self.log.info("  %s done: %s",
                              agent_name,
                              answer[:100].replace("\n", " ") if answer else "(no answer)")
            except subprocess.TimeoutExpired:
                self.log.error("  %s TIMED OUT after %gs", agent_name, self.response_timeout)
                self.room.post(agent_name, "Turn timed out.", "error", round_num)
            except Exception as exc:
                self.log.error("  %s ERROR: %s", agent_name, exc)
                self.room.post(agent_name, f"Turn failed: {exc}", "error", round_num)

    def _run_agent_turn(self, agent_name: str, round_num: int) -> str:
        agent_py = self.agent_dir / "agent.py"
        prompt = self._build_turn_prompt(agent_name, round_num)

        cmd = [sys.executable, "-u", str(agent_py),
               "--agent", agent_name,
               "--prompt", prompt]

        # Provider/model overrides: CLI flag wins over per-agent config
        if self.args.provider:
            cmd += ["--provider", self.args.provider]
        if self.args.model:
            cmd += ["--model", self.args.model]

        env = os.environ.copy()
        env["SWARM_ROOM_FILE"] = str(self.room.path)
        env["SWARM_AGENT_NAME"] = agent_name
        env["SWARM_ROUND"] = str(round_num)
        env["PYTHONUNBUFFERED"] = "1"

        self.log.debug("  cmd: %s", " ".join(cmd))

        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=self.response_timeout,
        )

        if result.stderr:
            for line in result.stderr.strip().splitlines():
                self.log.debug("    [%s stderr] %s", agent_name, line)

        if result.returncode != 0:
            err = (result.stderr or "").strip()[:300]
            raise RuntimeError(f"exit={result.returncode}: {err}")

        stdout = (result.stdout or "").strip()
        if stdout:
            lines = [line.strip() for line in stdout.splitlines() if line.strip()]
            if lines:
                stdout = lines[-1]

        if not stdout and result.stderr:
            stderr_lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
            for line in reversed(stderr_lines):
                if line.startswith("["):
                    continue
                if line.startswith("{") and '"action"' in line:
                    continue
                stdout = line
                break

        return stdout

    # ── prompt builder ────────────────────────────────────────────────────────

    def _build_turn_prompt(self, agent_name: str, round_num: int) -> str:
        done_so_far = self.room.done_agents()
        done_note = ""
        if done_so_far:
            done_note = (
                f"\n\nNote: {', '.join(sorted(done_so_far))} have already signalled done. "
                f"If you also believe the meeting objective is achieved, "
                f"post type=done and give your final_answer."
            )

        return (
            f"SWARM MEETING — Round {round_num} of {self.max_rounds}\n"
            f"Topic: {self.topic}\n\n"
            f"Steps:\n"
            f"1. Call room_read to see all contributions so far.\n"
            f"2. Contribute your perspective with one or more room_post calls.\n"
            f"3. Choose the type that best fits each post "
            f"(analysis / proposal / code / review / question / decision / done).\n"
            f"4. Post type=done if you believe the meeting objective is fully achieved.\n"
            f"5. Give final_answer with a brief summary of what you contributed this round."
            f"{done_note}"
        )


# ── CLI helpers ───────────────────────────────────────────────────────────────

def _auto_detect_agent_dir() -> Path:
    here = Path(__file__).resolve().parent
    # This script lives alongside agent.py in skynet2/
    if (here / "agent.py").exists():
        return here
    for candidate in [here.parent / "skynet2", here / "skynet2"]:
        if (candidate / "agent.py").exists():
            return candidate
    return here


def _load_swarm_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(f"Swarm config not found: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
    return slug[:max_len]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Swarm meeting coordinator — runs multiple agents in a shared room.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--topic", default=None,
        help="Meeting topic / task description (required unless --summary)",
    )
    parser.add_argument(
        "--config", default=None, metavar="FILE",
        help="Path to swarm YAML config  [default: agents/swarm.yaml]",
    )
    parser.add_argument(
        "--agent-dir", default=None, metavar="DIR",
        help="Path to skynet2 directory  [auto-detected]",
    )
    parser.add_argument(
        "--room-file", default=None, metavar="FILE",
        help="Explicit room JSONL file path  [default: rooms/<slug>_<ts>.jsonl]",
    )
    parser.add_argument(
        "--log-dir", default="./logs", metavar="DIR",
        help="Directory for coordinator logs  [default: ./logs]",
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="Print formatted summary of an existing room file and exit",
    )
    parser.add_argument(
        "--provider", default=None, choices=["openai", "claude"],
        help="Provider override applied to all participants",
    )
    parser.add_argument(
        "--model", default=None,
        help="Model override applied to all participants",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show agent stderr and DEBUG coordinator messages on console",
    )
    args = parser.parse_args()

    # Resolve agent-dir
    if args.agent_dir is None:
        args.agent_dir = str(_auto_detect_agent_dir())

    # Resolve config
    if args.config is None:
        args.config = str(Path(args.agent_dir) / "agents" / "swarm.yaml")

    return args


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    logger = setup_logging(Path(args.log_dir), args.verbose)

    # --summary mode: just pretty-print an existing room
    if args.summary:
        room_path = Path(args.room_file) if args.room_file else None
        if not room_path or not room_path.exists():
            print("ERROR: --summary requires --room-file pointing to an existing room JSONL", file=sys.stderr)
            sys.exit(1)
        print(SwarmRoom(room_path).format())
        return

    if not args.topic:
        print("ERROR: --topic is required (or use --summary to inspect an existing room)", file=sys.stderr)
        sys.exit(1)

    # Load config
    try:
        config = _load_swarm_config(Path(args.config))
    except Exception as exc:
        logger.critical("Cannot load swarm config: %s", exc)
        sys.exit(1)

    # Determine room file
    if args.room_file:
        room_path = Path(args.room_file)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = _slugify(args.topic)
        rooms_dir = Path(args.agent_dir) / "rooms"
        rooms_dir.mkdir(parents=True, exist_ok=True)
        room_path = rooms_dir / f"{slug}_{ts}.jsonl"

    room = SwarmRoom(room_path)
    agent_dir = Path(args.agent_dir)

    coordinator = SwarmCoordinator(
        config=config,
        topic=args.topic,
        room=room,
        agent_dir=agent_dir,
        args=args,
        logger=logger,
    )
    coordinator.run()


if __name__ == "__main__":
    main()

