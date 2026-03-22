#!/usr/bin/env python3
"""
Production-ready lightweight ReAct-style AI Agent
Follows strict JSON protocol, hierarchical spawning, bounded execution
"""

import os
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
    MAX_OUTPUT_CHARS,
    MAX_RETRIES_PER_STEP,
    MAX_STEPS,
)
from agent_loaders import load_agents, load_commands
from agent_logging import log_session_end, log_session_start, log_step
from agent_utils import build_system_prompt, extract_json, extract_usage, is_codex


class Agent:
    def __init__(self, config: dict, model: str, depth: int, agent_name: str, verbose: bool = False, log_path: str | None = None, provider: str = "openai", verbose_log: bool = False, verbose_log_path: str | None = None, provider_override: str | None = None):
        self.config = config
        self.model = model
        self.depth = depth
        self.agent_name = agent_name
        self.verbose = verbose
        self.spawned_children = 0
        self.provider = (provider or "openai").lower()
        self.provider_override = (provider_override.lower() if provider_override else None)
        self.verbose_log = verbose_log
        self.verbose_log_path = verbose_log_path
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

        limits = config.get("limits", {})
        self.max_steps = limits.get("max_steps", MAX_STEPS)
        self.max_depth = limits.get("max_depth", MAX_AGENT_DEPTH)
        self.max_children = limits.get("max_children", MAX_CHILD_AGENTS)
        self.max_output_chars = MAX_OUTPUT_CHARS
        self.max_context_messages = MAX_CONTEXT_MESSAGES

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
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

        if self.verbose:
            self._vprint(f"[START] Agent '{agent_name}' | depth={depth} | provider={self.provider} | model={model}")
            self._vprint(f"   config role  : {config.get('role','<unset>')}")
            self._vprint(f"   permissions  : {', '.join(config.get('permissions',[])) or '<none>'}")
            self._vprint(f"   max steps    : {self.max_steps}")
            self._vprint(f"   log file     → {self.log_path}")
            if self.verbose_log and self.verbose_log_path:
                self._vprint(f"   verbose log  → {self.verbose_log_path}")
            self._vprint()

    def _vprint(self, text: str = "", end: str = "\n"):
        if self.verbose:
            print(text, end=end, file=sys.stderr, flush=True)
        if self.verbose_log and self.verbose_log_path:
            try:
                with open(self.verbose_log_path, "a", encoding="utf-8") as f:
                    f.write(text)
                    f.write(end)
            except Exception:
                pass

    def _log(self, step: int, action: str, parameters: dict, result: str):
        log_step(self.log_path, self.agent_name, self.provider, self.model, self.depth, step, action, parameters, result)

    def _log_session_end(self):
        log_session_end(self.log_path, self.agent_name, self.provider, self.model, self.session_tokens_in, self.session_tokens_out)

    def _extract_json(self, text: str) -> dict | None:
        return extract_json(text)

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
        if self.verbose:
            cmd += ["--verbose"]
        if self.verbose_log:
            cmd += ["--verbose-log"]
            if self.verbose_log_path:
                cmd += ["--verbose-log-path", self.verbose_log_path]

        try:
            if self.verbose_log and self.verbose_log_path:
                self._vprint(f"[child cmd] {' '.join(cmd)}")
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=CHILD_AGENT_TIMEOUT)
            if self.verbose_log and self.verbose_log_path:
                if r.stdout:
                    self._vprint(f"[child stdout]\n{r.stdout}")
                if r.stderr:
                    self._vprint(f"[child stderr]\n{r.stderr}")            
                if r.returncode == 0:
                    return f"FINAL_ANSWER: {r.stdout.strip()}"
            err = r.stderr.strip()[:400]
            return f"ERROR: child agent failed\n{r.returncode=}\n{err}"
        except subprocess.TimeoutExpired:
            return "ERROR: child agent timed out"
        except Exception as e:
            return f"ERROR: could not start child: {e}"

    def execute_command(self, name: str, params: dict, step: int) -> str:
        if name == "run_agent":
            return self._run_agent(params, step)

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
                        if self.verbose:
                            print(event.delta, end="", flush=True, file=sys.stderr)
                        full_response += event.delta
                        parsed_early = self._extract_json(full_response)
                        if parsed_early is not None:
                            break

                final_response = stream.get_final_response()
                usage = getattr(final_response, "usage", None)
                in_tokens, out_tokens = self._extract_usage(usage, "responses")
                if parsed_early is not None:
                    return __import__("json").dumps(parsed_early, ensure_ascii=False), in_tokens, out_tokens
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
            for chunk in stream:
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    usage = chunk.usage
                delta = chunk.choices[0].delta.content if chunk.choices else None
                delta = delta or ""
                if self.verbose and delta:
                    print(delta, end="", flush=True, file=sys.stderr)
                full_response += delta
                parsed_early = self._extract_json(full_response)
                if parsed_early is not None:
                    continue
            in_tokens, out_tokens = self._extract_usage(usage, "chat_completions")
            if parsed_early is not None:
                return __import__("json").dumps(parsed_early, ensure_ascii=False), in_tokens, out_tokens
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
                    if self.verbose and text:
                        print(text, end="", flush=True, file=sys.stderr)
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

            if parsed_early is not None:
                return __import__("json").dumps(parsed_early, ensure_ascii=False), in_tokens, out_tokens

            if stop_reason == "max_tokens" and claude_max_tokens < max_claude_tokens:
                new_limit = min(claude_max_tokens * 2, max_claude_tokens)
                if self.verbose:
                    print(f"   [claude] truncated at {claude_max_tokens} tokens → retrying with {new_limit}", file=sys.stderr)
                claude_max_tokens = new_limit
                time.sleep(0.3)
                continue

            break

        return full_response, in_tokens, out_tokens

    def run(self, initial_prompt: str):
        self.history = [{"role": "user", "content": initial_prompt}]
        step = 0

        while step < self.max_steps:
            step += 1
            if self.verbose:
                print(f"[{step:2d}] Calling {self.provider}:{self.model} …", file=sys.stderr)

            messages = [{"role": "system", "content": self.system_prompt}] + self.history[-self.max_context_messages :]

            parsed = None
            for attempt in range(1, MAX_RETRIES_PER_STEP + 1):
                if self.verbose and attempt > 1:
                    print(f"   retry {attempt}/{MAX_RETRIES_PER_STEP}", file=sys.stderr)

                try:
                    full_response, in_tokens, out_tokens = self._call_model(messages)
                    self.session_tokens_in += in_tokens
                    self.session_tokens_out += out_tokens
                except Exception as e:
                    if self.verbose:
                        print(f"   API error: {e}", file=sys.stderr)
                    time.sleep(0.7)
                    continue

                parsed = self._extract_json(full_response)
                if parsed:
                    break

                error_feedback = (
                    "Your last response was not valid JSON.\n"
                    "You MUST output EXACTLY one JSON object with no extra text.\n"
                    f"Last response started: {full_response[:180]!r}…"
                )
                self.history.append({"role": "user", "content": error_feedback})

            if not parsed:
                if self.verbose:
                    print(" → Parsing failed after all retries", file=sys.stderr)
                self._log(step, "parse_failure", {}, "Max retries reached")
                print("ERROR: Could not parse valid JSON after retries.")
                self._log_session_end()
                return

            action = parsed.get("action")
            if not action:
                self.history.append({"role": "user", "content": "Missing 'action' field in JSON"})
                continue

            curr = {"action": action}
            if action == "command":
                curr["name"] = parsed.get("name")
                curr["params"] = parsed.get("parameters", {})
            self.recent_actions.append(curr)
            if len(self.recent_actions) > 3:
                self.recent_actions.pop(0)
            if len(self.recent_actions) == 3 and len({__import__("json").dumps(d, sort_keys=True) for d in self.recent_actions}) == 1:
                if self.verbose:
                    print(" → Loop detected — forcing final answer", file=sys.stderr)
                print("Agent appears stuck in loop. Terminating.")
                self._log_session_end()
                return

            if action == "final_answer":
                content = parsed.get("content", "(no content)")
                is_invalid = False

                if isinstance(content, str):
                    stripped = content.strip()
                    if stripped.startswith("{") and stripped.endswith("}"):
                        try:
                            inner = __import__("json").loads(stripped)
                            if isinstance(inner, dict) and "action" in inner:
                                is_invalid = True
                        except Exception:
                            pass

                if is_invalid:
                    if self.verbose:
                        print(" → Invalid final_answer (wrapped JSON), retrying...", file=sys.stderr)

                    error_feedback = (
                        "INVALID OUTPUT:\n"
                        "You returned JSON inside 'content'. This is not allowed.\n\n"
                        "You MUST return either:\n"
                        '1. {"action":"command","name":"...","parameters":{}}\n'
                        '2. {"action":"final_answer","content":"plain text"}\n\n'
                        "Do NOT wrap JSON in strings."
                    )

                    self.history.append({"role": "user", "content": error_feedback})
                    continue

                if self.verbose:
                    print("\n → Final answer:", file=sys.stderr)

                print(content)
                self._log(step, "final_answer", {}, content)
                self._log_session_end()
                return

            elif action == "command":
                name = parsed.get("name")
                params = parsed.get("parameters", {})
                if name not in self.config.get("permissions", []):
                    obs = "ERROR: this command is not permitted"
                else:
                    if self.verbose:
                        print(f" → {name} {params}", file=sys.stderr)
                    obs = self.execute_command(name, params, step)

                obs = obs[: self.max_output_chars] + "…" if len(obs) > self.max_output_chars else obs

                self.history.append({"role": "assistant", "content": __import__("json").dumps(parsed)})
                self.history.append({"role": "user", "content": f"Observation: {obs}"})

                if name != "run_agent":
                    self._log(step, name, params, obs)

                if self.verbose:
                    print(f"   ↳ {obs[:120]}{'…' if len(obs) > 120 else ''}", file=sys.stderr)

            else:
                self.history.append({"role": "user", "content": "Invalid action — must be 'command' or 'final_answer'"})

        if self.verbose:
            print(f"Reached max steps ({self.max_steps}) without final answer.", file=sys.stderr)
        self._log(step, "max_steps_reached", {}, "terminated without final_answer")
        print("Agent reached maximum step limit without producing a final answer.")


if __name__ == "__main__":
    args = parse_args()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config, model, provider = load_runtime_config(args, script_dir)

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
    )
    agent.run(args.prompt)
