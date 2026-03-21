#!/usr/bin/env python3
"""
Production-ready lightweight ReAct-style AI Agent
Follows strict JSON protocol, hierarchical spawning, bounded execution
"""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
import yaml
from openai import OpenAI

# ───────────────────────────────────────────────
#  Global limits (can be overridden in config)
# ───────────────────────────────────────────────
MAX_STEPS = 30
MAX_RETRIES_PER_STEP = 3
MAX_OUTPUT_CHARS = 300000
MAX_CONTEXT_MESSAGES = 20
MAX_AGENT_DEPTH = 3
MAX_CHILD_AGENTS = 5
CHILD_AGENT_TIMEOUT = 60      # seconds


class Agent:
    def __init__(self, config: dict, model: str, depth: int, agent_name: str, verbose: bool = False):
        self.config = config
        self.model = model
        self.depth = depth
        self.agent_name = agent_name
        self.verbose = verbose
        self.spawned_children = 0

        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.history: list[dict] = []
        self.recent_actions: list[dict] = []        # for loop detection
        self.session_tokens_in = 0
        self.session_tokens_out = 0

        # Load limits (prefer config → globals)
        limits = config.get("limits", {})
        self.max_steps           = limits.get("max_steps",   MAX_STEPS)
        self.max_depth           = limits.get("max_depth",   MAX_AGENT_DEPTH)
        self.max_children        = limits.get("max_children",MAX_CHILD_AGENTS)
        self.max_output_chars    = MAX_OUTPUT_CHARS
        self.max_context_messages = MAX_CONTEXT_MESSAGES

        # Logging (always relative to this script directory, not current working directory)
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.logs_dir = os.path.join(self.base_dir, "logs")
        os.makedirs(self.logs_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(self.logs_dir, f"{agent_name}_{ts}.jsonl")
        self._log_session_start()

        self.command_info, self.command_handlers = self._load_commands()
        self.agent_info = self._load_agents()
        self.system_prompt = self._build_system_prompt()

        if self.verbose:
            print(f"[START] Agent '{agent_name}' | depth={depth} | model={model}")
            print(f"   config role  : {config.get('role','<unset>')}")
            print(f"   permissions  : {', '.join(config.get('permissions',[])) or '<none>'}")
            print(f"   max steps    : {self.max_steps}")
            print(f"   log file     → {self.log_path}\n")

    def _load_commands(self) -> tuple[dict, dict]:
        command_info: dict = {}
        command_handlers: dict = {}

        commands_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "commands")
        os.makedirs(commands_dir, exist_ok=True)

        for filename in sorted(os.listdir(commands_dir)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue

            path = os.path.join(commands_dir, filename)
            module_name = f"commands.{filename[:-3]}"

            try:
                spec = importlib.util.spec_from_file_location(module_name, path)
                if not spec or not spec.loader:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                name = getattr(module, "COMMAND_NAME", None)
                description = getattr(module, "DESCRIPTION", None)
                usage_example = getattr(module, "USAGE_EXAMPLE", None)
                handler = getattr(module, "execute", None)
                if not callable(handler):
                    handler = getattr(module, "run", None)

                if not name or not isinstance(name, str):
                    continue
                if not callable(handler):
                    continue

                command_info[name] = {
                    "description": description or "No description provided.",
                    "usage_example": usage_example or "{}"
                }
                command_handlers[name] = handler
            except Exception:
                continue

        return command_info, command_handlers

    def _load_agents(self) -> dict:
        agent_info: dict = {}

        agents_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents")
        os.makedirs(agents_dir, exist_ok=True)

        for filename in sorted(os.listdir(agents_dir)):
            if not (filename.endswith(".yaml") or filename.endswith(".yml")):
                continue

            path = os.path.join(agents_dir, filename)
            try:
                with open(path, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}

                name = os.path.splitext(filename)[0]
                description = cfg.get("description") or cfg.get("role") or "No description provided."
                agent_info[name] = {
                    "description": description
                }
            except Exception:
                continue

        return agent_info

    def _log(self, step: int, action: str, parameters: dict, result: str):
        entry = {
            "type": "step",
            "step": step,
            "action": action,
            "parameters": parameters,
            "result": result[:500] + "…" if len(result) > 500 else result,
            "timestamp": datetime.now().isoformat(),
            "agent": self.agent_name,
            "model": self.model,
            "depth": self.depth
        }
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False)
                f.write("\n")
        except:
            pass

    def _log_session_start(self):
        entry = {
            "type": "session_start",
            "agent": self.agent_name,
            "model": self.model,
            "depth": self.depth,
            "timestamp": datetime.now().isoformat()
        }
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False)
                f.write("\n")
        except:
            pass

    def _log_session_end(self):
        total = self.session_tokens_in + self.session_tokens_out
        entry = {
            "type": "session_end",
            "agent": self.agent_name,
            "model": self.model,
            "tokens": {
                "inbound": self.session_tokens_in,
                "outbound": self.session_tokens_out,
                "total": total
            },
            "timestamp": datetime.now().isoformat()
        }
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False)
                f.write("\n")
        except:
            pass

    def _build_system_prompt(self) -> str:
        role = self.config.get("role", "assistant")
        base = self.config.get("base_system_prompt", "").strip()

        cmd_list = ""
        allowed = self.config.get("permissions", [])
        for name in allowed:
            if name not in self.command_info:
                continue
            info = self.command_info[name]
            cmd_list += f"• {name}\n  {info['description']}\n  Example: {info['usage_example']}\n\n"

        allowed_agents_list = ""
        allowed_agents = self.config.get("allowed_agents", [])
        for name in allowed_agents:
            info = self.agent_info.get(name)
            if not info:
                continue
            allowed_agents_list += f"• {name}\n  {info['description']}\n\n"

        return f"""You are a {role} agent.

{base}

You MUST respond with EXACTLY ONE valid JSON object and nothing else.

Possible actions:

1. Execute allowed command
{{
  "action": "command",
  "name": "<command_name>",
  "parameters": {{ ... }}
}}

2. Give final answer and stop
{{
  "action": "final_answer",
  "content": "PLAIN TEXT ONLY"
}}

CRITICAL RULES:
- ONLY output valid JSON — no explanations, no markdown, no ```json blocks
- Use one of the allowed commands below
- Do not repeat the same action/parameters more than twice
- NEVER wrap action in final_answer
- Always perform all required steps by commands


ALLOWED COMMANDS:
{cmd_list}
ALLOWED AGENTS:
{allowed_agents_list}

STRATEGY:
- Think step-by-step inside your reasoning (but do NOT output reasoning)
- Prefer shortest reliable path
- If command fails → try different approach, do NOT loop
- Never ask for confirmation
- Always perform all steps

SAFETY:
- Never run destructive commands (rm -rf, shutdown, etc.)
"""

    def _extract_json(self, text: str) -> dict | None:
        # Remove common markdown fences that appear despite json mode
        text = re.sub(r'^```json\s*|\s*```$', '', text.strip(), flags=re.MULTILINE | re.IGNORECASE)
        text = text.strip()

        decoder = json.JSONDecoder()

        # Try from each JSON object start and return the first object that fully parses.
        # This is robust to extra pre/post text and braces inside JSON strings.
        starts = [i for i, ch in enumerate(text) if ch == '{']
        for start in starts:
            try:
                obj, _end = decoder.raw_decode(text[start:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue

        return None

    def _run_agent(self, params: dict) -> str:
        if self.depth + 1 > self.max_depth:
            return "ERROR: maximum nesting depth reached"
        if self.spawned_children >= self.max_children:
            return "ERROR: maximum number of child agents reached"

        child_agent = params.get("agent")
        child_prompt = params.get("prompt")
        if not child_agent or not child_prompt:
            return "ERROR: 'agent' and 'prompt' required"

        self.spawned_children += 1

        cmd = [
            sys.executable, os.path.abspath(__file__),
            "--agent", child_agent,
            "--prompt", child_prompt,
            "--depth", str(self.depth + 1),
        ]
        #if self.model:
        #    cmd += ["--model", self.model]
        if self.verbose:
            cmd += ["--verbose"]

        child_log_path = None
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            child_log_path = os.path.join(self.logs_dir, f"{child_agent}_{ts}.jsonl")
        except Exception:
            child_log_path = None

        self._log(
            step=0,
            action="run_agent",
            parameters={"agent": child_agent, "prompt": child_prompt},
            result=(f"child session starting | log file → {child_log_path}" if child_log_path else "child session starting")
        )

        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=CHILD_AGENT_TIMEOUT
            )
            if r.returncode == 0:
                return f"FINAL_ANSWER: {r.stdout.strip()}"
            else:
                err = r.stderr.strip()[:400]
                return f"ERROR: child agent failed\n{r.returncode=}\n{err}"
        except subprocess.TimeoutExpired:
            return "ERROR: child agent timed out"
        except Exception as e:
            return f"ERROR: could not start child: {e}"

    def execute_command(self, name: str, params: dict) -> str:
        if name == "run_agent":
            return self._run_agent(params)

        handler = self.command_handlers.get(name)
        if not handler:
            return "ERROR: command not implemented"

        try:
            return str(handler(params))
        except Exception as e:
            return f"ERROR: {e}"

    def _is_codex(self) -> bool:
        return "codex" in self.model.lower()

    def _build_prompt(self, messages: list[dict]) -> str:
        prompt = ""

        for m in messages:
            role = m["role"]
            content = m["content"]

            if role == "system":
                prompt += f"INSTRUCTIONS:\n{content}\n\n"
            elif role == "user":
                prompt += f"USER:\n{content}\n\n"
            elif role == "assistant":
                prompt += f"ASSISTANT:\n{content}\n\n"

        prompt += "ASSISTANT:\n"
        return prompt

    def run(self, initial_prompt: str):
        self.history = [{"role": "user", "content": initial_prompt}]
        step = 0

        while step < self.max_steps:
            step += 1
            if self.verbose:
                print(f"[{step:2d}] Calling {self.model} …")

            messages = [
                {"role": "system", "content": self.system_prompt}
            ] + self.history[-self.max_context_messages:]

            parsed = None
            for attempt in range(1, MAX_RETRIES_PER_STEP + 1):
                if self.verbose and attempt > 1:
                    print(f"   retry {attempt}/{MAX_RETRIES_PER_STEP}")

                full_response = ""

                try:
                
                    with self.client.responses.stream(
                        model=self.model,
                        input=messages,
                        temperature=self.config.get("temperature", 0.7),
                        max_output_tokens=self.config.get("max_tokens", 4096),
                    ) as stream:

                        for event in stream:
                            if event.type == "response.output_text.delta":
                                if self.verbose:
                                    print(event.delta, end="", flush=True)
                                full_response += event.delta

                        final_response = stream.get_final_response()
                        usage = getattr(final_response, "usage", None)
                        if usage:
                            self.session_tokens_in += int(getattr(usage, "input_tokens", 0) or 0)
                            self.session_tokens_out += int(getattr(usage, "output_tokens", 0) or 0)

                except Exception as e:
                    if self.verbose:
                        print(f"   API error: {e}")
                    time.sleep(0.7)
                    continue

                parsed = self._extract_json(full_response)
                if parsed:
                    break

                # Tell model what went wrong
                error_feedback = (
                    "Your last response was not valid JSON.\n"
                    "You MUST output EXACTLY one JSON object with no extra text.\n"
                    f"Last response started: {full_response[:180]!r}…"
                )
                self.history.append({"role": "user", "content": error_feedback})

            if not parsed:
                if self.verbose:
                    print(" → Parsing failed after all retries")
                self._log(step, "parse_failure", {}, "Max retries reached")
                print("ERROR: Could not parse valid JSON after retries.")
                self._log_session_end()
                return

            action = parsed.get("action")
            if not action:
                self.history.append({"role": "user", "content": "Missing 'action' field in JSON"})
                continue

            # Simple loop detection (last 3 identical actions)
            curr = {"action": action}
            if action == "command":
                curr["name"] = parsed.get("name")
                curr["params"] = parsed.get("parameters", {})
            self.recent_actions.append(curr)
            if len(self.recent_actions) > 3:
                self.recent_actions.pop(0)
            if len(self.recent_actions) == 3 and len({
                json.dumps(d, sort_keys=True)
                for d in self.recent_actions
            }) == 1:
                if self.verbose:
                    print(" → Loop detected — forcing final answer")
                print("Agent appears stuck in loop. Terminating.")
                self._log_session_end()
                return

            if action == "final_answer":
                content = parsed.get("content", "(no content)")

                # 🚨 Detect wrapped JSON → reject + retry
                is_invalid = False

                if isinstance(content, str):
                    stripped = content.strip()

                    # Fast check (cheap)
                    if stripped.startswith("{") and stripped.endswith("}"):
                        try:
                            inner = json.loads(stripped)
                            if isinstance(inner, dict) and "action" in inner:
                                is_invalid = True
                        except:
                            pass

                if is_invalid:
                    if self.verbose:
                        print(" → Invalid final_answer (wrapped JSON), retrying...")

                    error_feedback = (
                        "INVALID OUTPUT:\n"
                        "You returned JSON inside 'content'. This is not allowed.\n\n"
                        "You MUST return either:\n"
                        '1. {"action":"command","name":"...","parameters":{}}\n'
                        '2. {"action":"final_answer","content":"plain text"}\n\n'
                        "Do NOT wrap JSON in strings."
                    )

                    self.history.append({"role": "user", "content": error_feedback})
                    continue  # 🔁 retry same step

                # ✅ Valid final answer → finish
                if self.verbose:
                    print(f"\n → Final answer:")

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
                        print(f" → {name} {params}")
                    obs = self.execute_command(name, params)

                obs = obs[:self.max_output_chars] + "…" if len(obs) > self.max_output_chars else obs

                self.history.append({"role": "assistant", "content": json.dumps(parsed)})
                self.history.append({"role": "user", "content": f"Observation: {obs}"})
                self._log(step, name, params, obs)

                if self.verbose:
                    print(f"   ↳ {obs[:120]}{'…' if len(obs)>120 else ''}")

            else:
                self.history.append({"role": "user", "content": "Invalid action — must be 'command' or 'final_answer'"})

        # max steps reached
        if self.verbose:
            print(f"Reached max steps ({self.max_steps}) without final answer.")
        self._log(step, "max_steps_reached", {}, "terminated without final_answer")
        print("Agent reached maximum step limit without producing a final answer.")

# ────────────────────────────────────────────────
#  CLI
# ────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lightweight ReAct JSON agent")
    parser.add_argument("--agent",   required=True,  help="agent config name (agents/<name>.yaml)")
    parser.add_argument("--prompt",  required=True,  help="initial user prompt / task")
    parser.add_argument("--model",   default=None,   help="override model name")
    parser.add_argument("--depth",   type=int, default=0, help="current hierarchy depth (internal)")
    parser.add_argument("-v", "--verbose", action="store_true", help="show detailed progress")

    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "agents", f"{args.agent}.yaml")
    if not os.path.isfile(config_path):
        print(f"Error: config not found → {config_path}")
        sys.exit(1)

    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading config: {e}")
        sys.exit(1)

    model = args.model or config.get("model")
    if not model:
        print("Error: model must be set in config or via --model")
        sys.exit(1)

    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable is required")
        sys.exit(1)

    agent = Agent(
        config=config,
        model=model,
        depth=args.depth,
        agent_name=args.agent,
        verbose=args.verbose
    )

    agent.run(args.prompt)
