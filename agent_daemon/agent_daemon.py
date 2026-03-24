#!/usr/bin/env python3
"""agent_daemon.py — Persistent agent pipeline daemon.

Starts a skynet2 agent in --keep-session-open mode and feeds it messages
arriving on a named pipe (FIFO), one at a time, in arrival order.

The FIFO stays open permanently (self-writer trick) so external senders can
open/write/close it repeatedly without the daemon losing the read-end.

Designed for cron jobs, webhooks, shell scripts, or any process that can
write a line of text to a path.

Quick start
-----------
    # Terminal 1 — start the daemon
    python agent_daemon.py --agent code --agent-dir ../skynet2

    # Terminal 2 — send tasks
    echo "list all .py files" > /tmp/skynet2_code.fifo
    echo "run the test suite"  > /tmp/skynet2_code.fifo

Cron example (runs every hour)
-------------------------------
    0 * * * * echo "run hourly health check" > /tmp/skynet2_code.fifo

Options
-------
    --agent             Agent config name (required, maps to agents/<name>.yaml)
    --agent-dir         Path to the skynet2 directory (auto-detected by default)
    --pipe              Input FIFO path (default: /tmp/skynet2_<agent>.fifo)
    --initial-prompt    First message sent at startup (default: "You are ready.")
    --log-dir           Daemon log directory (default: ./logs)
    --response-log      File to append message/response pairs to
    --pid-file          Write daemon PID here (for process managers)
    --response-timeout  Seconds to wait for each agent response (default: 600)
    --provider          Provider override forwarded to the agent
    --model             Model override forwarded to the agent
    --agent-verbose     Pass --verbose to the agent subprocess
    -v / --verbose      Verbose daemon logging (DEBUG level to console)
"""

import argparse
import logging
import logging.handlers
import os
import queue
import select
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

# Bytes written by Python's input() before blocking for stdin.
# The agent loop does: input("\nYou> ")  →  stdout gets b"\nYou> "
PROMPT_MARKER = b"\nYou> "

DEFAULT_RESPONSE_TIMEOUT = 600  # seconds per agent call


# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging(log_dir: Path, agent_name: str, verbose: bool) -> logging.Logger:
    """Rotating file handler (10 MB × 5) + stderr console handler."""
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"daemon_{agent_name}_{ts}.log"

    fmt = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger = logging.getLogger("agent_daemon")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Rotating file — always DEBUG level so nothing is lost
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Console (stderr) — INFO unless --verbose
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    logger.info("Daemon log → %s", log_file)
    return logger


# ── FIFO helpers ──────────────────────────────────────────────────────────────

def ensure_fifo(path: Path, logger: logging.Logger) -> None:
    """Create a named pipe at *path* if it does not already exist."""
    if path.exists():
        if not stat.S_ISFIFO(path.stat().st_mode):
            raise RuntimeError(f"Path exists and is not a FIFO: {path}")
        logger.debug("FIFO already present: %s", path)
    else:
        os.mkfifo(path, mode=0o600)
        logger.info("Created FIFO: %s  (mode 0600)", path)


# ── Pipe reader thread ────────────────────────────────────────────────────────

class PipeReader(threading.Thread):
    """Background thread that reads newline-delimited messages from a FIFO.

    Uses the *self-writer* trick: we permanently hold one write-end of the FIFO
    open ourselves.  This prevents the read-end from ever receiving EOF when an
    external writer disconnects, so external senders can open/write/close the
    FIFO repeatedly without disrupting the daemon.

    Each non-empty, stripped line is pushed onto *msg_queue*.
    """

    def __init__(
        self,
        pipe_path: Path,
        msg_queue: "queue.Queue[str]",
        stop_event: threading.Event,
        logger: logging.Logger,
    ) -> None:
        super().__init__(name="pipe-reader", daemon=True)
        self.pipe_path = pipe_path
        self.msg_queue = msg_queue
        self.stop_event = stop_event
        self.log = logger

    def run(self) -> None:
        self.log.info("[pipe] Starting on %s", self.pipe_path)

        try:
            rfd = os.open(str(self.pipe_path), os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            self.log.error("[pipe] Cannot open FIFO read-end: %s", exc)
            return

        try:
            wfd = os.open(str(self.pipe_path), os.O_WRONLY | os.O_NONBLOCK)
        except OSError as exc:
            os.close(rfd)
            self.log.error("[pipe] Cannot open FIFO write-end: %s", exc)
            return

        self.log.info("[pipe] Open and listening for messages")
        buf = ""
        try:
            while not self.stop_event.is_set():
                readable, _, _ = select.select([rfd], [], [], 1.0)
                if not readable:
                    continue
                try:
                    raw = os.read(rfd, 4096)
                except OSError as exc:
                    self.log.error("[pipe] Read error: %s", exc)
                    break
                if not raw:
                    # Should not happen with self-writer, but guard anyway.
                    time.sleep(0.05)
                    continue

                buf += raw.decode("utf-8", errors="replace")
                self.log.debug("[pipe] Received %d bytes (buf=%d)", len(raw), len(buf))

                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    self.log.info("[pipe] ← %r", line)
                    self.msg_queue.put(line)
        finally:
            try:
                os.close(rfd)
                os.close(wfd)
            except OSError:
                pass
        self.log.info("[pipe] Stopped")


# ── Agent session ─────────────────────────────────────────────────────────────

class AgentSession:
    """Wraps one agent.py subprocess running in --keep-session-open mode.

    Communication protocol:
      1. Agent processes the initial --prompt, prints the answer to stdout,
         then prints ``\\nYou> `` and blocks on stdin.
      2. For every subsequent message we write ``<message>\\n`` to stdin and
         read stdout until ``\\nYou> `` appears again.

    Binary I/O + os.read() is used so select() works on the raw file
    descriptors without interference from Python's text buffering.
    The agent is launched with ``python -u`` (unbuffered) and
    PYTHONUNBUFFERED=1 so its stdout reaches us immediately.
    """

    def __init__(
        self,
        agent_py: Path,
        agent_name: str,
        initial_prompt: str,
        extra_args: list[str],
        response_timeout: float,
        logger: logging.Logger,
    ) -> None:
        self.agent_py = agent_py
        self.agent_name = agent_name
        self.initial_prompt = initial_prompt
        self.extra_args = extra_args
        self.timeout = response_timeout
        self.log = logger
        self.proc: subprocess.Popen | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> str:
        """Spawn the agent subprocess and return its startup response."""
        cmd = [
            sys.executable, "-u",          # -u: force unbuffered stdout/stderr
            str(self.agent_py),
            "--agent", self.agent_name,
            "--prompt", self.initial_prompt,
            "--keep-session-open",
        ] + self.extra_args

        self.log.info("[session] Launching: %s", " ".join(cmd))
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"       # belt-and-suspenders

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.log.info("[session] Agent PID=%d", self.proc.pid)

        resp = self._read_until_prompt()
        self.log.info("[session] Startup response (%d chars): %s",
                      len(resp), resp[:120].replace("\n", "↵") + ("…" if len(resp) > 120 else ""))
        return resp

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.log.info("[session] Terminating PID=%d", self.proc.pid)
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.log.warning("[session] SIGTERM ignored — sending SIGKILL")
                self.proc.kill()
                self.proc.wait()
            self.log.info("[session] Agent stopped (exit=%s)", self.proc.returncode)

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    # ── message exchange ─────────────────────────────────────────────────────

    def send(self, message: str) -> str:
        """Write *message* to agent stdin, block until response. Returns answer text."""
        if not self.is_alive():
            raise RuntimeError("Agent process is not running")
        assert self.proc and self.proc.stdin
        self.log.debug("[session] → %r", message[:200])
        self.proc.stdin.write((message + "\n").encode())
        self.proc.stdin.flush()
        resp = self._read_until_prompt()
        self.log.info("[session] ← (%d chars): %s",
                      len(resp), resp[:120].replace("\n", "↵") + ("…" if len(resp) > 120 else ""))
        return resp

    # ── internal reader ──────────────────────────────────────────────────────

    def _read_until_prompt(self) -> str:
        """Read agent stdout until PROMPT_MARKER appears.

        Interleaves stderr reads so the agent's verbose/debug output is logged
        at DEBUG level and doesn't accumulate in an unread pipe buffer (which
        would cause the agent to block).
        """
        assert self.proc and self.proc.stdout and self.proc.stderr

        sel = selectors.DefaultSelector()
        sel.register(self.proc.stdout, selectors.EVENT_READ, data="stdout")
        sel.register(self.proc.stderr, selectors.EVENT_READ, data="stderr")

        buf = b""
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                # ── process exited ─────────────────────────────────────────
                if self.proc.poll() is not None:
                    try:
                        tail = self.proc.stdout.read() or b""
                        buf += tail
                    except OSError:
                        pass
                    try:
                        err = (self.proc.stderr.read() or b"").decode("utf-8", errors="replace").strip()
                        if err:
                            self.log.warning("[session] final stderr:\n%s", err[:800])
                    except OSError:
                        pass
                    raise RuntimeError(
                        f"Agent exited (code={self.proc.returncode}) while waiting for response"
                    )

                # ── timeout ───────────────────────────────────────────────
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError(
                        f"Agent response timeout after {self.timeout}s"
                    )

                # ── wait for data ─────────────────────────────────────────
                events = sel.select(timeout=min(0.5, left))
                for key, _ in events:
                    try:
                        chunk = os.read(key.fileobj.fileno(), 4096)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        continue

                    if key.data == "stderr":
                        for line in chunk.decode("utf-8", errors="replace").splitlines():
                            self.log.debug("[agent stderr] %s", line)
                        continue

                    buf += chunk

                # ── check for prompt marker ───────────────────────────────
                if PROMPT_MARKER in buf:
                    answer, _ = buf.rsplit(PROMPT_MARKER, 1)
                    return answer.decode("utf-8", errors="replace").strip()

                # Handles the very end of the buffer when marker has no trailing bytes yet
                if buf.endswith(b"You> "):
                    return buf[:-5].decode("utf-8", errors="replace").strip()
        finally:
            sel.close()


# ── Response log ──────────────────────────────────────────────────────────────

class ResponseLog:
    """Appends message/response pairs to a plain-text log file."""

    def __init__(self, path: Path, logger: logging.Logger) -> None:
        self.path = path
        self.log = logger
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, message: str, response: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sep = "─" * 72
        entry = (
            f"\n{sep}\n"
            f"[{ts}] PROMPT:\n{message}\n\n"
            f"[{ts}] RESPONSE:\n{response}\n"
        )
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(entry)
        except OSError as exc:
            self.log.warning("[resp-log] Write error: %s", exc)


# ── Daemon ────────────────────────────────────────────────────────────────────

class Daemon:
    def __init__(self, args: argparse.Namespace, logger: logging.Logger) -> None:
        self.args = args
        self.log = logger
        self.stop_event = threading.Event()
        self.msg_queue: queue.Queue[str] = queue.Queue()
        self.pipe_path = Path(args.pipe)
        self.session: AgentSession | None = None
        self.resp_log = ResponseLog(Path(args.response_log), logger)

    # ── signal handling ───────────────────────────────────────────────────────

    def _on_signal(self, signum: int, _frame) -> None:
        name = signal.Signals(signum).name
        self.log.info("Signal %s received — requesting shutdown", name)
        self.stop_event.set()

    # ── PID file ──────────────────────────────────────────────────────────────

    def _write_pid(self) -> None:
        if not self.args.pid_file:
            return
        try:
            Path(self.args.pid_file).write_text(str(os.getpid()), encoding="ascii")
            self.log.debug("PID %d → %s", os.getpid(), self.args.pid_file)
        except OSError as exc:
            self.log.warning("Cannot write PID file: %s", exc)

    def _remove_pid(self) -> None:
        if not self.args.pid_file:
            return
        try:
            Path(self.args.pid_file).unlink(missing_ok=True)
        except OSError:
            pass

    # ── agent session lifecycle ───────────────────────────────────────────────

    def _build_extra_args(self) -> list[str]:
        extra: list[str] = []
        if self.args.provider:
            extra += ["--provider", self.args.provider]
        if self.args.model:
            extra += ["--model", self.args.model]
        if self.args.agent_verbose:
            extra.append("--verbose")
        return extra

    def _start_session(self) -> None:
        agent_py = Path(self.args.agent_dir) / "agent.py"
        if not agent_py.exists():
            raise FileNotFoundError(f"agent.py not found at {agent_py}")

        if self.session:
            self.session.stop()

        self.session = AgentSession(
            agent_py=agent_py,
            agent_name=self.args.agent,
            initial_prompt=self.args.initial_prompt,
            extra_args=self._build_extra_args(),
            response_timeout=self.args.response_timeout,
            logger=self.log,
        )
        startup_resp = self.session.start()
        self.resp_log.write(self.args.initial_prompt, startup_resp)
        self.log.info("[daemon] Agent session ready")

    # ── message processing ────────────────────────────────────────────────────

    def _handle(self, message: str) -> None:
        self.log.info("[daemon] Processing message (%d chars): %r",
                      len(message), message[:120])
        max_attempts = 3

        for attempt in range(1, max_attempts + 1):
            # Restart dead session
            if not (self.session and self.session.is_alive()):
                self.log.warning("[daemon] Session not alive — restarting (attempt %d/%d)",
                                 attempt, max_attempts)
                try:
                    self._start_session()
                except Exception as exc:
                    self.log.error("[daemon] Session restart failed: %s", exc)
                    if attempt == max_attempts:
                        self.log.error("[daemon] Dropping message after %d failed restarts: %r",
                                       max_attempts, message)
                        return
                    time.sleep(3 * attempt)
                    continue

            # Try to send
            try:
                response = self.session.send(message)  # type: ignore[union-attr]
                self.resp_log.write(message, response)
                self.log.info("[daemon] Message processed OK (%d-char response)", len(response))
                return
            except Exception as exc:
                self.log.error("[daemon] Send failed (attempt %d/%d): %s",
                               attempt, max_attempts, exc)
                if self.session:
                    self.session.stop()
                    self.session = None
                if attempt < max_attempts:
                    time.sleep(2 * attempt)

        self.log.error("[daemon] Gave up on message after %d attempts: %r",
                       max_attempts, message)

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        self.log.info("═" * 60)
        self.log.info("Agent Daemon starting")
        self.log.info("  agent        : %s", self.args.agent)
        self.log.info("  agent-dir    : %s", self.args.agent_dir)
        self.log.info("  pipe         : %s", self.pipe_path)
        self.log.info("  response-log : %s", self.args.response_log)
        self.log.info("  timeout      : %ss", self.args.response_timeout)
        self.log.info("═" * 60)

        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

        self._write_pid()

        try:
            ensure_fifo(self.pipe_path, self.log)
            self._start_session()
        except Exception as exc:
            self.log.critical("Startup failed: %s", exc)
            self._remove_pid()
            sys.exit(1)

        reader = PipeReader(self.pipe_path, self.msg_queue, self.stop_event, self.log)
        reader.start()

        self.log.info("Ready — send tasks with:  echo 'your task' > %s", self.pipe_path)

        try:
            while not self.stop_event.is_set():
                try:
                    msg = self.msg_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                self._handle(msg)
                self.msg_queue.task_done()
        finally:
            # Drain and report any messages that will not be processed
            pending: list[str] = []
            while not self.msg_queue.empty():
                try:
                    pending.append(self.msg_queue.get_nowait())
                except queue.Empty:
                    break
            if pending:
                self.log.warning("[daemon] Shutdown — dropping %d unprocessed message(s):",
                                 len(pending))
                for m in pending:
                    self.log.warning("  dropped: %r", m)

            if self.session:
                self.session.stop()
            self._remove_pid()
            self.log.info("[daemon] Stopped cleanly")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _auto_detect_agent_dir() -> str:
    """Walk upward from this script's location looking for agent.py."""
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "skynet2",    # ../skynet2  (script lives in agent_daemon/)
        here / "skynet2",           # ./skynet2
        here,                       # we are inside skynet2
    ]
    for c in candidates:
        if (c / "agent.py").exists():
            return str(c)
    # Fall back; will produce a clear error at runtime
    return str(here.parent / "skynet2")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Persistent agent daemon: queues pipe input and feeds it to a skynet2 agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required
    parser.add_argument(
        "--agent", required=True,
        help="Agent config name (maps to agents/<name>.yaml inside agent-dir)",
    )

    # Paths
    parser.add_argument(
        "--agent-dir", default=None, metavar="DIR",
        help="Path to the skynet2 directory (auto-detected from script location by default)",
    )
    parser.add_argument(
        "--pipe", default=None, metavar="PATH",
        help="Named pipe (FIFO) path for incoming messages  [default: /tmp/skynet2_<agent>.fifo]",
    )
    parser.add_argument(
        "--log-dir", default="./logs", metavar="DIR",
        help="Directory for rotating daemon logs  [default: ./logs]",
    )
    parser.add_argument(
        "--response-log", default=None, metavar="FILE",
        help="File that receives every message/response pair  [default: <log-dir>/responses_<agent>.log]",
    )
    parser.add_argument(
        "--pid-file", default=None, metavar="FILE",
        help="Write daemon PID here — useful for systemd / supervisord",
    )

    # Agent behaviour
    parser.add_argument(
        "--initial-prompt",
        default="You are ready to receive tasks. Acknowledge briefly.",
        help="Message sent to the agent at startup to initialise the session",
    )
    parser.add_argument(
        "--response-timeout", type=float, default=DEFAULT_RESPONSE_TIMEOUT,
        metavar="SECS",
        help=f"Max seconds to wait for each agent response  [default: {DEFAULT_RESPONSE_TIMEOUT}]",
    )
    parser.add_argument(
        "--provider", default=None, choices=["openai", "claude"],
        help="Provider override forwarded to the agent",
    )
    parser.add_argument(
        "--model", default=None,
        help="Model override forwarded to the agent",
    )
    parser.add_argument(
        "--agent-verbose", action="store_true",
        help="Pass --verbose to the agent subprocess (agent logs appear as DEBUG here)",
    )

    # Daemon verbosity
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show DEBUG-level daemon messages on the console (always written to file)",
    )

    args = parser.parse_args()

    # Fill derived defaults
    if args.agent_dir is None:
        args.agent_dir = _auto_detect_agent_dir()
    if args.pipe is None:
        args.pipe = f"/tmp/skynet2_{args.agent}.fifo"
    if args.response_log is None:
        args.response_log = str(Path(args.log_dir) / f"responses_{args.agent}.log")

    return args


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    logger = setup_logging(Path(args.log_dir), args.agent, args.verbose)
    Daemon(args, logger).run()


if __name__ == "__main__":
    main()

