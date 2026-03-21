#!/usr/bin/env python3
"""
Production-ready lightweight ReAct-style AI Agent
Follows strict JSON protocol, hierarchical spawning, bounded execution
"""

import argparse
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
MAX_OUTPUT_CHARS = 2000
MAX_CONTEXT_MESSAGES = 20
MAX_AGENT_DEPTH = 3
MAX_CHILD_AGENTS = 5
CHILD_AGENT_TIMEOUT = 60      # seconds

# ───────────────────────────────────────────────
# Built-in command metadata (shown in system prompt)
# ───────────────────────────────────────────────
COMMAND_INFO = {
    "read_file": {
        "description": "Read the content of a file and return it as text.",
        "usage_example": '{"path": "example.txt"}'
    },
    "write_file": {
        "description": "Write (or overwrite) content to a file.",
        "usage_example": '{"path": "example.txt", "content": "Hello world"}'
    },
    "append_to_file": {
        "description": "Append content to an existing file.",
        "usage_example": '{"path": "log.txt", "content": "\\nNew line"}'
    },
    "ls": {
        "description": "List files and directories in the given path.",
        "usage_example": '{"path": "."}'
    },
    "linux_command": {
        "description": "Run a safe Linux shell command (timeout 10s, dangerous patterns blocked).",
        "usage_example": '{"command": "ls -la"}'
    },
    "run_agent": {
        "description": "Spawn a child agent with given role and prompt.",
        "usage_example": '{"role": "reviewer", "prompt": "Review this", "agent": "reviewer"}'
    }
}

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

        # Load limits (prefer config → globals)
        limits = config.get("limits", {})
        self.max_steps           = limits.get("max_steps",   MAX_STEPS)
        self.max_depth           = limits.get("max_depth",   MAX_AGENT_DEPTH)
        self.max_children        = limits.get("max_children",MAX_CHILD_AGENTS)
        self.max_output_chars    = MAX_OUTPUT_CHARS
        self.max_context_messages = MAX_CONTEXT_MESSAGES

        # Logging
        os.makedirs("logs", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = f"logs/{agent_name}_{ts}.jsonl"

        self.system_prompt = self._build_system_prompt()

        if self.verbose:
            print(f"[START] Agent '{agent_name}' | depth={depth} | model={model}")
            print(f"   config role  : {config.get('role','<unset>')}")
            print(f"   permissions  : {', '.join(config.get('permissions',[])) or '<none>'}")
            print(f"   max steps    : {self.max_steps}")
            print(f"   log file     → {self.log_path}\n")

    def _log(self, step: int, action: str, parameters: dict, result: str):
        entry = {
            "step": step,
            "action": action,
            "parameters": parameters,
            "result": result[:500] + "…" if len(result) > 500 else result,
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
            if name not in COMMAND_INFO:
                continue
            info = COMMAND_INFO[name]
            cmd_list += f"• {name}\n  {info['description']}\n  Example: {info['usage_example']}\n\n"

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
  "content": "your complete answer here"
}}

CRITICAL RULES:
- ONLY output valid JSON — no explanations, no markdown, no ```json blocks
- Use one of the allowed commands below
- Do not repeat the same action/parameters more than twice
- If stuck or no progress → use final_answer

ALLOWED COMMANDS:
{cmd_list}

STRATEGY:
- Think step-by-step inside your reasoning (but do NOT output reasoning)
- Prefer shortest reliable path
- If command fails → try different approach, do NOT loop

SAFETY:
- Never run destructive commands (rm -rf, shutdown, etc.)
"""

    def _extract_json(self, text: str) -> dict | None:
        # Remove common markdown fences that appear despite json mode
        text = re.sub(r'^```json\s*|\s*```$', '', text.strip(), flags=re.MULTILINE | re.IGNORECASE)
        text = text.strip()

        start = text.find('{')
        if start == -1:
            return None

        count = 0
        end = -1
        for i in range(start, len(text)):
            if text[i] == '{':
                count += 1
            elif text[i] == '}':
                count -= 1
                if count == 0:
                    end = i + 1
                    break
        if end == -1:
            return None

        candidate = text[start:end]
        # Aggressive cleanup
        candidate = re.sub(r',\s*([}\]])', r'\1', candidate)   # trailing commas
        candidate = candidate.replace("'", '"')

        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None

    # ─── Command implementations ────────────────────────────────────────

    def _read_file(self, params: dict) -> str:
        path = params.get("path", "").strip()
        if not path:
            return "ERROR: missing 'path'"
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()[:self.max_output_chars]
        except Exception as e:
            return f"ERROR: {e}"

    def _write_file(self, params: dict) -> str:
        path = params.get("path")
        content = params.get("content", "")
        if not path:
            return "ERROR: missing 'path'"
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return "File written successfully."
        except Exception as e:
            return f"ERROR: {e}"

    def _append_to_file(self, params: dict) -> str:
        path = params.get("path")
        content = params.get("content", "")
        if not path:
            return "ERROR: missing 'path'"
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            return "Content appended successfully."
        except Exception as e:
            return f"ERROR: {e}"

    def _ls(self, params: dict) -> str:
        path = params.get("path", ".")
        try:
            return "\n".join(sorted(os.listdir(path)))
        except Exception as e:
            return f"ERROR: {e}"

    def _linux_command(self, params: dict) -> str:
        cmd = params.get("command", "").strip()
        if not cmd:
            return "ERROR: missing 'command'"

        blocked = ["rm -rf", "shutdown", "reboot", "mkfs", ":(){:|:&};:"]
        for pat in blocked:
            if pat in cmd.lower():
                return f"ERROR: dangerous command pattern blocked ({pat})"

        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=10
            )
            out = (r.stdout + "\n" + r.stderr).strip()
            if r.returncode != 0:
                return f"ERROR (code {r.returncode}): {out}"
            return out[:self.max_output_chars]
        except subprocess.TimeoutExpired:
            return "ERROR: command timed out after 10 seconds"
        except Exception as e:
            return f"ERROR: {e}"

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
        if self.model:
            cmd += ["--model", self.model]
        if self.verbose:
            cmd += ["--verbose"]

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
        handlers = {
            "read_file":     self._read_file,
            "write_file":    self._write_file,
            "append_to_file": self._append_to_file,
            "ls":            self._ls,
            "linux_command": self._linux_command,
            "run_agent":     self._run_agent,
        }
        handler = handlers.get(name)
        if not handler:
            return "ERROR: command not implemented"
        return handler(params)

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
                return

            if action == "final_answer":
                content = parsed.get("content", "(no content)")
                if self.verbose:
                    print(f" → Final answer: {content}")
                print(content)
                self._log(step, "final_answer", {}, content)
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

    config_path = f"agents/{args.agent}.yaml"
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