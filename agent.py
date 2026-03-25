#!/usr/bin/env python3
"""
Production-ready lightweight ReAct-style AI Agent
Follows strict JSON protocol, hierarchical spawning, bounded execution
"""

import json
import os
import re
import selectors
import shlex
import subprocess
import sys
import time
from datetime import datetime

from openai import OpenAI
try:
    from anthropic import Anthropic
except Exception:
    Anthropic = None

from agent_cli import load_runtime_config, parse_args
from agent_constants import (
    CHILD_AGENT_TIMEOUT,
    MAX_AGENT_DEPTH,
    MAX_CHILD_AGENTS,
    MAX_CONTEXT_MESSAGES,
    MAX_OBS_HISTORY_CHARS,
    MAX_OUTPUT_CHARS,
    MAX_RETRIES_PER_STEP,
    MAX_STEPS,
    OBSERVATION_COMPACT_PREVIEW_CHARS,
    OBSERVATION_FILE_PREVIEW_CHARS,
    OBSERVATION_GENERIC_PREVIEW_CHARS,
)
from agent_loaders import load_agents, load_commands
from agent_logging import log_session_end, log_session_start, log_step
from agent_utils import (
    build_system_prompt,
    compress_observation,
    extract_all_json_actions,
    extract_json,
    extract_usage,
    is_codex,
)


class Agent:
    def __init__(self, config: dict, model: str, depth: int, agent_name: str, verbose: bool = False, log_path: str | None = None, provider: str = "openai", verbose_log: bool = False, verbose_log_path: str | None = None, provider_override: str | None = None, process_all_json_blocks: bool = False):
        self.config = config
        self.model = model
        self.depth = depth
        self.agent_name = agent_name
        self.verbose = verbose
        self.spawned_children = 0
        self.call_agent_sessions: dict[str, dict] = {}
        self.provider = (provider or "openai").lower()
        self.provider_override = (provider_override.lower() if provider_override else None)
        self.process_all_json_blocks = process_all_json_blocks
        self.verbose_log = verbose_log
        self.verbose_log_path = verbose_log_path
        self._streaming_line_open = False
        self.parallel_tool_calls = bool(config.get("parallel_tool_calls", False))
        if self.provider == "openai":
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        elif self.provider == "claude":
            if Anthropic is None:
                raise RuntimeError("Anthropic SDK is not installed. Install 'anthropic' to use provider=claude.")
            self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

        self.history: list[dict] = []
        self.recent_actions: list[dict] = []
        self.session_tokens_in = 0
        self.session_tokens_out = 0

        limits = config.get("limits") or {}
        self.max_steps = limits.get("max_steps", MAX_STEPS)
        self.max_depth = limits.get("max_depth", MAX_AGENT_DEPTH)
        self.max_children = limits.get("max_children", MAX_CHILD_AGENTS)
        self.max_output_chars = MAX_OUTPUT_CHARS
        self.max_context_messages = MAX_CONTEXT_MESSAGES
        self.max_obs_history_chars = limits.get("max_obs_history_chars", MAX_OBS_HISTORY_CHARS)
        self.observable_file_preview_chars = limits.get("observable_file_preview_chars", OBSERVATION_FILE_PREVIEW_CHARS)
        self.observable_generic_preview_chars = limits.get("observable_generic_preview_chars", OBSERVATION_GENERIC_PREVIEW_CHARS)
        self.observable_compact_preview_chars = limits.get("observable_compact_preview_chars", OBSERVATION_COMPACT_PREVIEW_CHARS)

        # Track whether the environment context has already been injected once
        # so we don't repeat it in every subsequent system-prompt call.
        self._env_context_sent = False

        # Kept-session optimization: how to handle history between tasks.
        # "reset"   – drop all history, start clean (default, best for tokens)
        # "summary" – keep a 1-line summary of the previous task's outcome
        # "keep"    – old behavior, keep everything (snowball)
        self.session_reset_mode = str(config.get("session_reset_mode", "summary")).lower()
        self._last_final_answer: str = ""
        self._task_count: int = 0

        # Strict execution mode: reject final_answer responses that ask
        # for confirmation/clarification instead of executing.  Enabled by
        # default — the model should always act, never ask.
        self.strict_execution = bool(config.get("strict_execution", True))

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.work_dir = os.getcwd()
        self.logs_dir = os.path.join(self.base_dir, "logs")
        os.makedirs(self.logs_dir, exist_ok=True)

        if log_path is not None:
            self.log_path = log_path
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.log_path = os.path.join(self.logs_dir, f"{agent_name}_{ts}.jsonl")

        if self.verbose_log_path is None and self.verbose_log:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.verbose_log_path = os.path.join(self.logs_dir, f"verbose_{agent_name}_{ts}.log")

        log_session_start(self.log_path, self.agent_name, self.provider, self.model, self.depth)

        self.command_info, self.command_handlers = load_commands(self.base_dir)
        self.agent_info = load_agents(self.base_dir)
        self.system_prompt = build_system_prompt(self.config, self.command_info, self.agent_info)
        self.run_hooks = config.get("hooks", {}) or {}
        self.startup_observe_commands = config.get("startup_observe", []) or []

        self.init_hook_output = ""

        if self.verbose:
            self._vprint(f"[START] Agent '{agent_name}' | depth={depth} | provider={self.provider} | model={model}")
            self._vprint(f"   config role  : {config.get('role','<unset>')}")
            self._vprint(f"   permissions  : {', '.join(config.get('permissions',[])) or '<none>'}")
            self._vprint(f"   max steps    : {self.max_steps}")
            self._vprint(f"   log file     → {self.log_path}")
            if self.verbose_log and self.verbose_log_path:
                self._vprint(f"   verbose log  → {self.verbose_log_path}")
            self._vprint()

    def _indent(self) -> str:
        return "  " * self.depth

    def _prefixed_text(self, text: str) -> str:
        prefix = self._indent()
        if not text:
            return prefix
        return "\n".join(f"{prefix}{line}" if line else prefix for line in text.split("\n"))

    def _vprint(self, text: str = "", end: str = "\n"):
        formatted = self._prefixed_text(text)
        if self.verbose:
            print(formatted, end=end, file=sys.stderr, flush=True)
        if self.verbose_log and self.verbose_log_path:
            try:
                with open(self.verbose_log_path, "a", encoding="utf-8") as f:
                    f.write(formatted)
                    f.write(end)
            except Exception:
                pass

    def _vstream(self, text: str):
        if not text:
            return
        prefix = self._indent()
        chunks = []
        for part in text.splitlines(keepends=True):
            if not self._streaming_line_open:
                chunks.append(prefix)
                self._streaming_line_open = True
            chunks.append(part)
            if part.endswith("\n"):
                self._streaming_line_open = False
        rendered = "".join(chunks)
        if self.verbose:
            print(rendered, end="", file=sys.stderr, flush=True)
        if self.verbose_log and self.verbose_log_path:
            try:
                with open(self.verbose_log_path, "a", encoding="utf-8") as f:
                    f.write(rendered)
            except Exception:
                pass

    def _vend_stream(self):
        if self._streaming_line_open:
            if self.verbose:
                print(file=sys.stderr, flush=True)
            if self.verbose_log and self.verbose_log_path:
                try:
                    with open(self.verbose_log_path, "a", encoding="utf-8") as f:
                        f.write("\n")
                except Exception:
                    pass
            self._streaming_line_open = False

    @staticmethod
    def _format_char_size(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)

    def _vprint_context(self, messages: list[dict]):
        """Print a compact preview of every message about to be sent to the
        LLM so you can see at a glance what's eating your input tokens.

        Format per message::

            [role  ] first 40 chars of con…: 12.4k

        Plus a totals line.
        """
        if not self.verbose:
            return
        total = sum(len(m.get("content", "")) for m in messages)
        self._vprint(f"[context] {len(messages)} msgs, ~{self._format_char_size(total)} chars")
        role_labels = {"system": "system", "user": "user  ", "assistant": "assist"}
        for m in messages:
            role = role_labels.get(m.get("role", ""), m.get("role", "?"))
            content = m.get("content", "")
            size = len(content)
            preview = content[:40].replace("\n", "↵").replace("\r", "")
            if len(content) > 40:
                preview += "…"
            self._vprint(f"  [{role}] {preview}: {self._format_char_size(size)}")
        self._vprint()

    def _log(self, step: int, action: str, parameters: dict, result: str, step_tokens_in: int = 0, step_tokens_out: int = 0):
        log_step(self.log_path, self.agent_name, self.provider, self.model, self.depth, step, action, parameters, result, step_tokens_in, step_tokens_out)

    def _log_session_end(self):
        self._run_hook("on_run_finish", {
            "AGENT_SESSION_TOKENS_IN": self.session_tokens_in,
            "AGENT_SESSION_TOKENS_OUT": self.session_tokens_out,
        })
        log_session_end(self.log_path, self.agent_name, self.provider, self.model, self.session_tokens_in, self.session_tokens_out)

    def _extract_json(self, text: str) -> dict | None:
        return extract_json(text)

    def _run_hook(self, hook_name: str, extra_env: dict[str, str] | None = None) -> str:
        script = self.run_hooks.get(hook_name)
        if not script:
            return ""

        env = os.environ.copy()
        env.update({
            "AGENT_NAME": self.agent_name,
            "AGENT_MODEL": self.model,
            "AGENT_PROVIDER": self.provider,
            "AGENT_DEPTH": str(self.depth),
            "AGENT_LOG_PATH": self.log_path,
        })
        if extra_env:
            env.update({k: str(v) for k, v in extra_env.items()})

        try:
            result = subprocess.run(
                script,
                shell=True,
                cwd=os.getcwd(),
                env=env,
                capture_output=not self.verbose,
                text=True,
            )
            output = ((result.stdout or "") + (result.stderr or "")).strip()
            status = f"hook '{hook_name}' exit={result.returncode}"
            if output:
                status += f"\n{output}"
            self._log(0, f"hook:{hook_name}", {"script": script}, status)
            if self.verbose_log and self.verbose_log_path and output:
                self._vprint(output)
            return output
        except Exception as e:
            self._log(0, f"hook:{hook_name}", {"script": script}, f"ERROR: {e}")
            return ""

    def _run_agent(self, params: dict, step: int) -> str:
        if self.depth + 1 > self.max_depth:
            return "ERROR: maximum nesting depth reached"
        if self.spawned_children >= self.max_children:
            return "ERROR: maximum number of child agents reached"

        child_agent = params.get("agent")
        child_prompt = params.get("prompt")
        if not child_agent or not child_prompt:
            return "ERROR: 'agent' and 'prompt' required"

        self.spawned_children += 1

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        child_log_path = os.path.join(self.logs_dir, f"{child_agent}_{ts}.jsonl")

        self._log(
            step=step,
            action="run_agent",
            parameters={"agent": child_agent, "prompt": child_prompt},
            result=f"child session starting | log file → {child_log_path}",
        )

        cmd = [
            sys.executable,
            os.path.abspath(__file__),
            "--agent",
            child_agent,
            "--prompt",
            child_prompt,
            "--depth",
            str(self.depth + 1),
            "--log-path",
            child_log_path,
        ]
        if self.provider_override:
            cmd += ["--provider-override", self.provider_override]
        if self.verbose_log:
            cmd += ["--verbose-log"]
            if self.verbose_log_path:
                cmd += ["--verbose-log-path", self.verbose_log_path]

        try:
            if self.verbose_log and self.verbose_log_path:
                self._vprint(f"[child cmd] {' '.join(cmd)}")
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=CHILD_AGENT_TIMEOUT)
            if self.verbose_log and self.verbose_log_path:
                if r.stderr:
                    self._vprint(f"[child stderr]\n{r.stderr.rstrip()}")
                if r.stdout:
                    child_stdout = r.stdout.rstrip()
                    final_line = child_stdout.splitlines()[-1] if child_stdout else ""
                    self._vprint(f"[child final answer]\n{final_line}")
            if r.returncode == 0:
                return f"FINAL_ANSWER: {r.stdout.strip()}"
            err = r.stderr.strip()[:400]
            return f"ERROR: child agent failed\n{r.returncode=}\n{err}"
        except subprocess.TimeoutExpired:
            return "ERROR: child agent timed out"
        except Exception as e:
            return f"ERROR: could not start child: {e}"


    def _call_agent(self, params: dict, step: int) -> str:
        if self.depth + 1 > self.max_depth:
            return "ERROR: maximum nesting depth reached"
        if self.spawned_children >= self.max_children:
            return "ERROR: maximum number of child agents reached"

        child_agent = params.get("agent")
        child_prompt = params.get("prompt")
        if not child_agent or not child_prompt:
            return "ERROR: 'agent' and 'prompt' required"

        session_id = str(params.get("session_id") or child_agent)
        session = self.call_agent_sessions.get(session_id)

        if session is None:
            self.spawned_children += 1
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            child_log_path = os.path.join(self.logs_dir, f"{child_agent}_{ts}.jsonl")
            cmd = [
                sys.executable,
                os.path.abspath(__file__),
                "--agent",
                child_agent,
                "--prompt",
                child_prompt,
                "--depth",
                str(self.depth + 1),
                "--log-path",
                child_log_path,
                "--keep-session-open",
            ]
            if self.provider_override:
                cmd += ["--provider-override", self.provider_override]
            if self.verbose_log:
                cmd += ["--verbose-log"]
                if self.verbose_log_path:
                    cmd += ["--verbose-log-path", self.verbose_log_path]

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=0,
                )
            except Exception as e:
                return f"ERROR: could not start child: {e}"

            session = {
                "agent": child_agent,
                "proc": proc,
                "log_path": child_log_path,
                "started": False,
            }
            self.call_agent_sessions[session_id] = session

            self._log(
                step=step,
                action="call_agent",
                parameters={"agent": child_agent, "prompt": child_prompt, "session_id": session_id},
                result=f"child persistent session started | log file → {child_log_path}",
            )
        else:
            proc = session["proc"]
            if proc.poll() is not None:
                self.call_agent_sessions.pop(session_id, None)
                return "ERROR: child session is closed"
            if session.get("agent") != child_agent:
                return "ERROR: session_id is already bound to another agent"

            try:
                assert proc.stdin is not None
                proc.stdin.write(child_prompt + "\n")
                proc.stdin.flush()
            except Exception as e:
                self.call_agent_sessions.pop(session_id, None)
                return f"ERROR: failed to send prompt to child: {e}"
        proc = session["proc"]
        try:
            assert proc.stdout is not None
            assert proc.stderr is not None

            selector = selectors.DefaultSelector()
            selector.register(proc.stdout, selectors.EVENT_READ)
            selector.register(proc.stderr, selectors.EVENT_READ)

            stdout_buffer = ""
            stderr_chunks = []
            prompt_marker = "\nYou> "
            saw_prompt = False
            idle_deadline = time.time() + CHILD_AGENT_TIMEOUT

            while True:
                if proc.poll() is not None:
                    try:
                        remaining_out = proc.stdout.read() or ""
                        if remaining_out:
                            stdout_buffer += remaining_out
                    except Exception:
                        pass
                    try:
                        remaining_err = proc.stderr.read() or ""
                        if remaining_err:
                            stderr_chunks.append(remaining_err)
                    except Exception:
                        pass
                    self.call_agent_sessions.pop(session_id, None)
                    err = "".join(stderr_chunks).strip()[:400]
                    return f"ERROR: child agent ended unexpectedly\n{err}"

                events = selector.select(timeout=0.2)
                if not events:
                    if time.time() >= idle_deadline:
                        return "ERROR: child agent timed out waiting for response"
                    continue

                idle_deadline = time.time() + CHILD_AGENT_TIMEOUT

                for key, _ in events:
                    stream = key.fileobj
                    try:
                        data = os.read(stream.fileno(), 4096).decode("utf-8", errors="replace")
                    except Exception:
                        data = ""

                    if not data:
                        continue

                    if stream is proc.stderr:
                        stderr_chunks.append(data)
                        continue

                    stdout_buffer += data
                    if prompt_marker in stdout_buffer or stdout_buffer.endswith("You> "):
                        saw_prompt = True
                        break

                if saw_prompt:
                    break

            selector.close()

            if prompt_marker in stdout_buffer:
                answer = stdout_buffer.rsplit(prompt_marker, 1)[0].strip()
            elif stdout_buffer.endswith("You> "):
                answer = stdout_buffer[:-5].strip()
            else:
                return "ERROR: child agent prompt not detected"

            if not session.get("started"):
                session["started"] = True
            elif answer.startswith("You>"):
                answer = answer[4:].strip()

            if not answer:
                return "ERROR: child returned empty answer"
            return f"FINAL_ANSWER: {answer}"
        except Exception as e:
            self.call_agent_sessions.pop(session_id, None)
            return f"ERROR: failed reading child output: {e}"

    def _reset_for_new_task(self):
        """Reset history between tasks in a kept-open session to avoid
        snowballing input tokens.  Controlled by ``session_reset_mode``
        (config key ``session_reset_mode``):

        * ``"reset"``   – nuke all history, start completely fresh.
        * ``"summary"`` – keep a single user message with a one-line recap
                          of the previous task so the model has minimal
                          continuity (default).
        * ``"keep"``    – legacy behaviour, don't touch history at all.
        """
        mode = self.session_reset_mode

        if mode == "keep":
            return  # old behaviour — do nothing

        old_len = len(self.history)
        old_chars = sum(len(m.get("content", "")) for m in self.history)

        if mode == "reset":
            self.history = []
        else:
            # "summary" (default)
            if self._last_final_answer:
                recap = self._last_final_answer[:600]
                if len(self._last_final_answer) > 600:
                    recap += " …"
                self.history = [
                    {"role": "user", "content":
                     f"[context] Previous task (#{self._task_count}) completed. "
                     f"Summary of result:\n{recap}"},
                ]
            else:
                self.history = []

        self.recent_actions = []

        if self.verbose:
            new_len = len(self.history)
            self._vprint(
                f"[session reset] mode={mode} | "
                f"dropped {old_len}→{new_len} msgs, "
                f"~{old_chars} chars freed"
            )

    # Patterns that indicate the model is asking for confirmation/clarification
    # instead of executing.  Used by strict_execution mode to reject and retry.
    _CONFIRMATION_PATTERNS = re.compile(
        r"(?i)"
        r"(?:would you like|shall I|should I|do you want|want me to|"
        r"let me know if|please confirm|if you(?:'d| would) like|"
        r"I can (?:also |proceed |go ahead )|"
        r"before I proceed|ready to proceed|"
        r"awaiting (?:your |further )|"
        r"need (?:your |more )(?:input|guidance|confirmation|clarification|direction)|"
        r"please (?:let me know|provide|specify|clarify)|"
        r"if you(?:'re| are) happy|is that (?:ok|okay|correct|right)\??|"
        r"I(?:'ll| will) wait|(?:what|which) (?:do you|would you) prefer)"
    )

    # Patterns that indicate a plan/proposal without execution
    _PLAN_ONLY_PATTERNS = re.compile(
        r"(?i)"
        r"(?:here(?:'s| is) (?:my |the |a )?(?:plan|proposal|approach|strategy|outline)|"
        r"I (?:recommend|suggest|propose) (?:the following|we|that)|"
        r"steps? (?:to|for|I would)|"
        r"the following (?:changes|steps|approach)|"
        r"I would (?:start|begin|first|then)|"
        r"here(?:'s| is) what I(?:'d| would) do)"
    )

    def _is_confirmation_seeking(self, content: str) -> str | None:
        """Check if a final_answer is asking for confirmation instead of
        delivering results.  Returns a rejection reason or None if OK."""
        if not self.strict_execution:
            return None
        if not isinstance(content, str):
            return None

        text = content.strip()
        # Very short answers are usually genuine
        if len(text) < 30:
            return None

        # Check for confirmation-seeking language
        match = self._CONFIRMATION_PATTERNS.search(text)
        if match:
            return f"confirmation-seeking: '{match.group()}'"

        # Check for plan-only responses (no execution)
        # Only flag if this is early in the run (step < max_steps/2)
        # and the response doesn't mention completed work
        if self._PLAN_ONLY_PATTERNS.search(text):
            done_indicators = re.compile(
                r"(?i)(?:done|completed|finished|implemented|fixed|updated|created|"
                r"applied|changed|modified|replaced|wrote|added|removed|deleted)"
            )
            if not done_indicators.search(text):
                return f"plan-only without execution"

        return None

    # Commands whose large string params are payload the model never needs
    # to re-see in history (it can re-read the file instead).  Only the
    # target path / identifier matters.
    _WRITE_HEAVY_COMMANDS = frozenset({
        "write_file", "append_to_file", "replace_in_file",
        "replace_in_multiple_files", "text_block_replace", "apply_patch",
    })
    # Params that are always small identifiers — never truncate these.
    _KEEP_FULL_PARAMS = frozenset({"path", "paths", "file", "filename", "command", "agent", "session_id"})

    def _compact_action_for_history(self, parsed_item: dict) -> str:
        """Return a JSON string for the assistant action, capped for history.

        The model doesn't need its own write payloads in history — the
        observation already records success/failure and the file can be
        re-read.  So we aggressively strip large content params from
        write-heavy commands, and lightly trim everything else.
        """
        raw = json.dumps(parsed_item, ensure_ascii=False)
        if len(raw) <= 400:
            return raw

        compact = dict(parsed_item)
        params = compact.get("parameters")
        cmd_name = compact.get("name", "")

        if not isinstance(params, dict):
            return raw

        is_write_heavy = cmd_name in self._WRITE_HEAVY_COMMANDS
        trimmed_params = {}
        for k, v in params.items():
            v_str = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
            v_len = len(v_str)

            # Small identifiers — always keep in full
            if k in self._KEEP_FULL_PARAMS or v_len <= 80:
                trimmed_params[k] = v
            elif is_write_heavy:
                # Aggressively strip: just note the size
                trimmed_params[k] = f"[{v_len} chars]"
            else:
                # Non-write commands: keep first 120 chars for context
                trimmed_params[k] = v_str[:120] + f"…[{v_len} chars]"

        compact["parameters"] = trimmed_params
        return json.dumps(compact, ensure_ascii=False)

    def _compact_history(self, params: dict, step: int) -> str:
        """Replace old history messages with a compact summary provided by the model."""
        summary = params.get("summary")
        if not summary or not isinstance(summary, str):
            return "ERROR: 'summary' is required — write a concise summary of everything important so far"

        keep_recent = 4
        try:
            keep_recent = int(params.get("keep_recent", 4))
        except (TypeError, ValueError):
            pass
        keep_recent = max(2, min(keep_recent, len(self.history)))

        old_len = len(self.history)
        if old_len <= keep_recent + 1:
            return f"History is already small ({old_len} messages). No compaction needed."

        # Keep the very first user message (the initial prompt) + the summary
        # + the most recent `keep_recent` messages verbatim.
        initial_prompt_msg = self.history[0]   # always the user's original prompt
        recent_msgs = self.history[-keep_recent:] if keep_recent > 0 else []

        # Build compacted history
        self.history = [
            initial_prompt_msg,
            {"role": "assistant", "content": json.dumps({
                "action": "command",
                "name": "compact_history",
                "parameters": {"summary": summary},
            })},
            {"role": "user", "content": (
                f"Observation: History compacted. Summary of prior work:\n{summary}"
            )},
        ] + recent_msgs

        new_len = len(self.history)
        dropped = old_len - new_len
        self._log(step, "compact_history", {"keep_recent": keep_recent}, f"Compacted {old_len} → {new_len} messages (dropped {dropped})")

        if self.verbose:
            print(f"{self._indent()}   [compact_history] {old_len} → {new_len} messages", file=sys.stderr)

        return f"OK: history compacted from {old_len} to {new_len} messages ({dropped} dropped). Your summary is preserved."

    def execute_command(self, name: str, params: dict, step: int) -> str:
        if name == "run_agent":
            return self._run_agent(params, step)
        if name == "call_agent":
            return self._call_agent(params, step)
        if name == "compact_history":
            return self._compact_history(params, step)

        handler = self.command_handlers.get(name)
        if not handler:
            return "ERROR: command not implemented"

        try:
            return str(handler(params))
        except Exception as e:
            return f"ERROR: {e}"

    def _is_codex(self) -> bool:
        return is_codex(self.model)

    def _extract_usage(self, usage, api_type: str) -> tuple[int, int]:
        return extract_usage(usage, api_type)

    def _summarize_command_result(self, action: str, result: str) -> str:
        result = result or ""
        size = len(result.encode("utf-8", errors="ignore"))
        lines = result.count("\n") + (1 if result else 0)
        if action in {"write_file", "append_to_file", "text_block_replace"}:
            return f"{action}: ok ({size} bytes, {lines} lines)"
        if action in {"read_file", "multiple_file_read", "linux_command", "multiple_linux_commands", "ls"}:
            return f"{action}: output suppressed ({size} bytes, {lines} lines)"
        return result

    def _call_model(self, messages: list[dict]) -> tuple[str, int, int]:
        temperature = self.config.get("temperature", 0.0 if self._is_codex() else 0.7)
        if self._is_codex():
            default_max = 128000
        elif self.provider == "claude":
            default_max = 8192
        else:
            default_max = 4096
        max_tokens = self.config.get("max_tokens", default_max)

        if self.provider == "openai" and self._is_codex():
            full_response = ""
            parsed_early = None
            with self.client.responses.stream(
                model=self.model,
                input=messages,
                temperature=temperature,
                max_output_tokens=max_tokens,
                text={"format": {"type": "json_object"}},
            ) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        self._vstream(event.delta)
                        full_response += event.delta
                        parsed_early = self._extract_json(full_response)
                        if parsed_early is not None:
                            break
                final_response = stream.get_final_response()
                usage = getattr(final_response, "usage", None)
                in_tokens, out_tokens = self._extract_usage(usage, "responses")
                self._vend_stream()
                if parsed_early is not None:
                    return json.dumps(parsed_early, ensure_ascii=False), in_tokens, out_tokens
                return full_response, in_tokens, out_tokens

        elif self.provider == "openai":
            full_response = ""
            parsed_early = None
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_tokens,
                response_format={"type": "json_object"},
                stream=True,
                stream_options={"include_usage": True},
            )
            usage = None
            in_tokens, out_tokens = 0, 0
            for chunk in stream:
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    usage = chunk.usage
                    in_tokens, out_tokens = self._extract_usage(usage, "chat_completions")
                delta = chunk.choices[0].delta.content if chunk.choices else None
                delta = delta or ""
                if delta:
                    self._vstream(delta)
                full_response += delta
                if parsed_early is None:
                    parsed_early = self._extract_json(full_response)
            self._vend_stream()
            if parsed_early is not None:
                return json.dumps(parsed_early, ensure_ascii=False), in_tokens, out_tokens
            return full_response, in_tokens, out_tokens

        system_text = ""
        claude_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            else:
                claude_messages.append(m)

        claude_max_tokens = max_tokens
        max_claude_tokens = max_tokens
        initial_claude_tokens = min(40000, claude_max_tokens)
        claude_max_tokens = initial_claude_tokens
        claude_attempt = 0
        max_claude_retries = 4

        while claude_attempt < max_claude_retries:
            claude_attempt += 1
            full_response = ""
            parsed_early = None
            in_tokens, out_tokens = 0, 0
            stop_reason = None

            with self.client.messages.stream(
                model=self.model,
                system=system_text,
                messages=claude_messages,
                temperature=temperature,
                max_tokens=claude_max_tokens,
            ) as stream:
                for text in stream.text_stream:
                    if text:
                        self._vstream(text)
                    full_response += text
                    parsed_early = self._extract_json(full_response)
                    if parsed_early is not None:
                        try:
                            stream.close()
                        except Exception:
                            pass
                        try:
                            usage = getattr(stream, "_MessageStream__message", None)
                            if usage is None:
                                raw = getattr(stream, "response", None)
                                usage = getattr(raw, "usage", None) if raw else None
                            if usage is not None:
                                in_tokens, out_tokens = self._extract_usage(usage, "claude")
                        except Exception:
                            pass
                        break
                if parsed_early is None:
                    try:
                        message = stream.get_final_message()
                        usage = getattr(message, "usage", None)
                        in_tokens, out_tokens = self._extract_usage(usage, "claude")
                        stop_reason = getattr(message, "stop_reason", None)
                    except Exception:
                        pass
            self._vend_stream()

            if parsed_early is not None:
                return json.dumps(parsed_early, ensure_ascii=False), in_tokens, out_tokens

            if stop_reason == "max_tokens" and claude_max_tokens < max_claude_tokens:
                new_limit = min(claude_max_tokens * 2, max_claude_tokens)
                if self.verbose:
                    print(f"{self._indent()}   [claude] truncated at {claude_max_tokens} tokens → retrying with {new_limit}", file=sys.stderr)
                claude_max_tokens = new_limit
                time.sleep(0.3)
                continue

            break

        return full_response, in_tokens, out_tokens

    def _run_startup_observations(self):
        cmds = []
        if isinstance(self.startup_observe_commands, list):
            cmds.extend([
                c for c in self.startup_observe_commands
                if isinstance(c, str) and c.strip()
            ])
        results = []
        for c in cmds:
            obs = self.execute_command(
                "linux_command",
                {"command": f"cd {shlex.quote(self.work_dir)} && {c}"},
                step=0
            )
            # Cap to obs history limit, not max_output_chars — this goes into
            # the system prompt and is re-sent on EVERY API call.
            if len(obs) > self.max_obs_history_chars:
                obs = obs[: self.max_obs_history_chars] + f"\n[…trimmed — {len(obs)} chars total]"
            results.append(f"$ {c}\n{obs}")
        return "\n\n".join(results)

    def run(self, initial_prompt: str):
        self.init_hook_output = self._run_hook("on_run_start", {"AGENT_INITIAL_PROMPT": initial_prompt})
        startup_context = self._run_startup_observations()

        env_parts = []
        if startup_context:
            env_parts.append(startup_context)
        if self.init_hook_output:
            env_parts.append(self.init_hook_output)
        self.environment_context = "\n\n".join(env_parts)

        # Reset so this run's environment context is injected on the first step.
        self._env_context_sent = False

        if not self.history:
            self.history = [{"role": "user", "content": initial_prompt}]
        else:
            self.history.append({"role": "user", "content": initial_prompt})

        self.recent_actions = []
        step = 0

        while step < self.max_steps:
            step += 1
            if self.verbose:
                print(f"{self._indent()}[{step:2d}] Calling {self.provider}:{self.model} …", file=sys.stderr)

            # Include the environment context only on the first LLM call of
            # this session so we don't repeat a potentially large block every
            # turn (it's already visible to the model via earlier history).
            if self.environment_context and not self._env_context_sent:
                system_content = (
                    self.system_prompt
                    + "\n\nENVIRONMENT:\n"
                    + self.environment_context
                )
                self._env_context_sent = True
            else:
                system_content = self.system_prompt

            messages = [{
                "role": "system",
                "content": system_content
            }] + self.history[-self.max_context_messages:]

            self._vprint_context(messages)

            parsed = None
            parsed_actions = None
            step_tokens_in = 0
            step_tokens_out = 0
            for attempt in range(1, MAX_RETRIES_PER_STEP + 1):
                if self.verbose and attempt > 1:
                    print(f"{self._indent()}   retry {attempt}/{MAX_RETRIES_PER_STEP}", file=sys.stderr)

                try:
                    full_response, in_tokens, out_tokens = self._call_model(messages)
                    self.session_tokens_in += in_tokens
                    self.session_tokens_out += out_tokens
                    step_tokens_in += in_tokens
                    step_tokens_out += out_tokens
                except Exception as e:
                    self._vend_stream()
                    if self.verbose:
                        print(f"{self._indent()}   API error: {e}", file=sys.stderr)
                    time.sleep(0.7)
                    continue

                parsed_actions = extract_all_json_actions(full_response)
                parsed = parsed_actions[0] if parsed_actions else None
                if parsed:
                    break

                error_feedback = (
                    "Your last response was not valid JSON.\n"
                    "You MUST output valid JSON only.\n"
                    "Return either one JSON object or one JSON array of action objects.\n"
                    f"Last response started: {full_response[:180]!r}…"
                )
                self.history.append({"role": "user", "content": error_feedback})

            if not parsed:
                if self.verbose:
                    print(f"{self._indent()} → Parsing failed after all retries", file=sys.stderr)
                self._log(step, "parse_failure", {}, "Max retries reached", step_tokens_in, step_tokens_out)
                print("ERROR: Could not parse valid JSON after retries.")
                self._log_session_end()
                return

            actions_to_process = parsed_actions or []
            if not self.process_all_json_blocks and actions_to_process:
                first_non_final = next((item for item in actions_to_process if item.get("action") != "final_answer"), None)
                if first_non_final is not None:
                    actions_to_process = [first_non_final]
                else:
                    actions_to_process = [actions_to_process[0]]

            for parsed_item in actions_to_process:
                action = parsed_item.get("action")
                if not action:
                    self.history.append({"role": "user", "content": "Missing 'action' field in JSON"})
                    continue

                curr = {"action": action}
                if action == "command":
                    curr["name"] = parsed_item.get("name")
                    curr["params"] = parsed_item.get("parameters", {})
                self.recent_actions.append(curr)
                if len(self.recent_actions) > 3:
                    self.recent_actions.pop(0)
                if len(self.recent_actions) == 3 and len({json.dumps(d, sort_keys=True) for d in self.recent_actions}) == 1:
                    if self.verbose:
                        print(f"{self._indent()} → Loop detected — forcing final answer", file=sys.stderr)
                    self._log(step, "loop_termination", {}, "Agent appears stuck in loop. Terminating.", step_tokens_in, step_tokens_out)
                    print("Agent appears stuck in loop. Terminating.")
                    self._log_session_end()
                    return

                if action == "final_answer":
                    content = parsed_item.get("content", "(no content)")
                    is_invalid = False

                    if isinstance(content, str):
                        stripped = content.strip()
                        if stripped.startswith("{") and stripped.endswith("}"):
                            try:
                                inner = json.loads(stripped)
                                if isinstance(inner, dict) and "action" in inner:
                                    is_invalid = True
                            except Exception:
                                pass

                    if is_invalid:
                        if self.verbose:
                            print(f"{self._indent()} → Invalid final_answer (wrapped JSON), retrying...", file=sys.stderr)

                        error_feedback = (
                            "INVALID OUTPUT:\n"
                            "You returned JSON inside 'content'. This is not allowed.\n\n"
                            "You MUST return either:\n"
                            '1. {"action":"command","name":"...","parameters":{}}\n'
                            '2. {"action":"final_answer","content":"plain text"}\n\n'
                            "Do NOT wrap JSON in strings."
                        )

                        self.history.append({"role": "user", "content": error_feedback})
                        break

                    # Strict execution: reject answers that ask for confirmation
                    # or propose a plan without executing.
                    rejection_reason = self._is_confirmation_seeking(str(content))
                    if rejection_reason:
                        if self.verbose:
                            print(f"{self._indent()} → Rejected final_answer ({rejection_reason}), forcing execution...", file=sys.stderr)

                        error_feedback = (
                            "REJECTED: You returned a response that asks for confirmation or "
                            "proposes a plan without executing it.\n\n"
                            "This is NOT allowed. You MUST:\n"
                            "- Execute the task yourself using commands\n"
                            "- NEVER ask the user for confirmation, clarification, or approval\n"
                            "- NEVER propose a plan and stop — execute the plan\n"
                            "- Make reasonable assumptions when details are ambiguous\n\n"
                            "DO THE WORK NOW. Use {\"action\":\"command\",...} to proceed."
                        )

                        self.history.append({"role": "user", "content": error_feedback})
                        self._log(step, "rejected_confirmation", {}, f"Rejected: {rejection_reason}", step_tokens_in, step_tokens_out)
                        break

                    if self.verbose:
                        print(f"\n{self._indent()} → Final answer:", file=sys.stderr)

                    print(content)
                    self._last_final_answer = str(content)
                    self._task_count += 1
                    self._log(step, "final_answer", {}, content, step_tokens_in, step_tokens_out)
                    self._log_session_end()
                    return

                elif action == "command":
                    name = parsed_item.get("name")
                    params = parsed_item.get("parameters", {})
                    if name not in self.config.get("permissions", []):
                        obs = "ERROR: this command is not permitted"
                    else:
                        if self.verbose:
                            print(f"{self._indent()} → {name} {params}", file=sys.stderr)
                        obs = self.execute_command(name, params, step)

                    obs = obs[: self.max_output_chars] + "…" if len(obs) > self.max_output_chars else obs

                    # Build a compact version for history storage.
                    # Write commands: the model doesn't need the echo — just
                    # a confirmation with size.
                    # Read/other commands: smart head+tail compression so the
                    # model keeps both the beginning AND end of the output
                    # (the blunt [:8000] cut used to lose the tail entirely).
                    if name in self._WRITE_HEAVY_COMMANDS:
                        history_obs = self._summarize_command_result(name, obs)
                    elif len(obs) > self.max_obs_history_chars:
                        history_obs = compress_observation(
                            obs,
                            file_preview_chars=self.observable_file_preview_chars,
                            generic_preview_chars=min(self.max_obs_history_chars, self.observable_generic_preview_chars),
                            compact_preview_chars=min(self.max_obs_history_chars, self.observable_compact_preview_chars),
                        )
                    else:
                        history_obs = obs

                    self.history.append({"role": "assistant", "content": self._compact_action_for_history(parsed_item)})

                    # Add a history-pressure hint so the model knows when to compact
                    history_chars = sum(len(m.get("content", "")) for m in self.history)
                    hint = ""
                    if history_chars > 20000 or len(self.history) > self.max_context_messages - 4:
                        hint = (
                            f"\n[context: {len(self.history)} msgs, ~{history_chars} chars"
                            f" — consider compact_history if you have more work ahead]"
                        )

                    self.history.append({"role": "user", "content": f"Observation: {history_obs}{hint}"})

                    if name != "run_agent":
                        self._log(step, name, params, obs, step_tokens_in, step_tokens_out)

                    if self.verbose:
                        print(f"{self._indent()}   ↳ {obs[:120]}{'…' if len(obs) > 120 else ''}", file=sys.stderr)

                else:
                    self.history.append({"role": "user", "content": "Invalid action — must be 'command' or 'final_answer'"})

        if self.verbose:
            print(f"{self._indent()}Reached max steps ({self.max_steps}) without final answer.", file=sys.stderr)
        self._log(step, "max_steps_reached", {}, "terminated without final_answer", 0, 0)
        print("Agent reached maximum step limit without producing a final answer.")
        self._log_session_end()


if __name__ == "__main__":
    args = parse_args()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config, model, provider = load_runtime_config(args, script_dir)

    if args.startup_observe:
        existing = config.get("startup_observe", []) or []
        if not isinstance(existing, list):
            existing = []
        config["startup_observe"] = existing + args.startup_observe

    agent = Agent(
        config=config,
        model=model,
        depth=args.depth,
        agent_name=args.agent,
        verbose=args.verbose,
        log_path=args.log_path,
        provider=provider,
        verbose_log=args.verbose_log,
        verbose_log_path=args.verbose_log_path,
        provider_override=args.provider_override,
        process_all_json_blocks=args.process_all_json_blocks,
    )

    current_prompt = args.prompt
    while True:
        agent.run(current_prompt)
        if not args.keep_session_open:
            break
        try:
            current_prompt = input("\nYou> ").strip()
        except EOFError:
            break
        if not current_prompt:
            break
        agent._reset_for_new_task()
