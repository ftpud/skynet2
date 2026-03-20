from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI
import yaml

from utils.parser import parse_first_json_object, validate_action_payload

DEFAULT_LIMITS = {
    "max_steps": 30,
    "max_retries_per_step": 3,
    "max_output_chars": 2000,
    "max_context_messages": 20,
    "max_agent_depth": 3,
    "max_child_agents": 5,
    "child_agent_timeout": 60,
}

REQUIRED_CONFIG_FIELDS = ("role", "model", "permissions")
COMMAND_REQUIRED_ATTRIBUTES = ("COMMAND_NAME", "DESCRIPTION", "USAGE_EXAMPLE", "execute")

MAX_STEPS = DEFAULT_LIMITS["max_steps"]
MAX_RETRIES_PER_STEP = DEFAULT_LIMITS["max_retries_per_step"]
MAX_OUTPUT_CHARS = DEFAULT_LIMITS["max_output_chars"]
MAX_CONTEXT_MESSAGES = DEFAULT_LIMITS["max_context_messages"]
MAX_AGENT_DEPTH = DEFAULT_LIMITS["max_agent_depth"]
MAX_CHILD_AGENTS = DEFAULT_LIMITS["max_child_agents"]
CHILD_AGENT_TIMEOUT = DEFAULT_LIMITS["child_agent_timeout"]

LOG_PATH = Path(__file__).resolve().parent / "agent.log"
IO_LOG_PATH = Path(__file__).resolve().parent / "IO.log"
COMMANDS_DIR = Path(__file__).resolve().parent / "commands"

VERBOSE = False


def load_config(config_path: str) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError("Config must be a YAML mapping")

    missing = [field for field in REQUIRED_CONFIG_FIELDS if field not in data]
    if missing:
        raise ValueError(f"Missing required config fields: {', '.join(missing)}")

    if not isinstance(data.get("permissions"), list):
        raise ValueError("Config field 'permissions' must be a list")

    limits = data.get("limits") or {}
    if limits and not isinstance(limits, dict):
        raise ValueError("Config field 'limits' must be a mapping if provided")

    merged_limits = dict(DEFAULT_LIMITS)
    merged_limits.update({k: v for k, v in limits.items() if k in merged_limits})
    data["limits"] = merged_limits

    return data


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Agent System")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    parser.add_argument("--prompt", required=True, help="Initial user prompt")
    parser.add_argument("--model", required=False, help="Override config model")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose IO output")
    return parser.parse_args(argv)


def merge_cli_with_config(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    merged = dict(config)
    merged["prompt"] = args.prompt
    if args.model:
        merged["model"] = args.model
    return merged


def validate_runtime_config(config: dict[str, Any]) -> None:
    for field in REQUIRED_CONFIG_FIELDS:
        if not config.get(field):
            raise ValueError(f"Missing required field: {field}")
    if not isinstance(config.get("permissions"), list) or not config["permissions"]:
        raise ValueError("permissions must be a non-empty list")


def apply_limits_from_config(config: dict[str, Any]) -> None:
    global MAX_STEPS
    global MAX_RETRIES_PER_STEP
    global MAX_OUTPUT_CHARS
    global MAX_CONTEXT_MESSAGES
    global MAX_AGENT_DEPTH
    global MAX_CHILD_AGENTS
    global CHILD_AGENT_TIMEOUT

    limits = config.get("limits") or {}
    MAX_STEPS = int(limits.get("max_steps", DEFAULT_LIMITS["max_steps"]))
    MAX_RETRIES_PER_STEP = int(limits.get("max_retries_per_step", DEFAULT_LIMITS["max_retries_per_step"]))
    MAX_OUTPUT_CHARS = int(limits.get("max_output_chars", DEFAULT_LIMITS["max_output_chars"]))
    MAX_CONTEXT_MESSAGES = int(limits.get("max_context_messages", DEFAULT_LIMITS["max_context_messages"]))
    MAX_AGENT_DEPTH = int(limits.get("max_agent_depth", DEFAULT_LIMITS["max_agent_depth"]))
    MAX_CHILD_AGENTS = int(limits.get("max_child_agents", DEFAULT_LIMITS["max_child_agents"]))
    CHILD_AGENT_TIMEOUT = int(limits.get("child_agent_timeout", DEFAULT_LIMITS["child_agent_timeout"]))


def init_logger(log_path: Path = LOG_PATH, io_log_path: Path = IO_LOG_PATH) -> Path:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)
    io_log_path.parent.mkdir(parents=True, exist_ok=True)
    io_log_path.touch(exist_ok=True)
    return log_path


def log_jsonl(event: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    payload = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def log_io(direction: str, content: str, io_log_path: Path = IO_LOG_PATH) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "direction": direction,
        "content": content,
    }
    with io_log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    if VERBOSE:
        print(f"[{direction}] {content}")


def discover_command_modules(commands_dir: Path = COMMANDS_DIR) -> list[Any]:
    modules: list[Any] = []
    packages = ("agent.commands", "commands")

    for file_path in sorted(commands_dir.glob("*.py")):
        if file_path.name == "__init__.py":
            continue

        module_name = file_path.stem
        module = None
        for package in packages:
            import_path = f"{package}.{module_name}"
            try:
                module = importlib.import_module(import_path)
                break
            except Exception:
                continue
        if module is None:
            continue

        if any(not hasattr(module, attr) for attr in COMMAND_REQUIRED_ATTRIBUTES):
            continue

        command_name = getattr(module, "COMMAND_NAME", None)
        description = getattr(module, "DESCRIPTION", None)
        usage_example = getattr(module, "USAGE_EXAMPLE", None)
        execute_fn = getattr(module, "execute", None)

        if not isinstance(command_name, str) or not command_name.strip():
            continue
        if not isinstance(description, str) or not description.strip():
            continue
        if not isinstance(usage_example, str) or not usage_example.strip():
            continue
        if not callable(execute_fn):
            continue

        modules.append(module)

    return modules


def filter_commands_by_permissions(modules: list[Any], permissions: list[str]) -> list[Any]:
    allowed_permissions = {p for p in permissions if isinstance(p, str)}
    return [m for m in modules if getattr(m, "COMMAND_NAME", "") in allowed_permissions]


def build_command_registry(modules: list[Any]) -> dict[str, Any]:
    return {getattr(module, "COMMAND_NAME"): module for module in modules}


def init_history(system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
    history: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return trim_history(history)


def trim_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    return history if len(history) <= MAX_CONTEXT_MESSAGES else history[-MAX_CONTEXT_MESSAGES:]


def build_system_prompt(role: str, command_modules: list[Any]) -> str:
    command_blocks = []
    for module in sorted(command_modules, key=lambda m: getattr(m, "COMMAND_NAME", "")):
        command_blocks.append(
            "- {name}: {desc}\n  Usage: {usage}".format(
                name=getattr(module, "COMMAND_NAME"),
                desc=getattr(module, "DESCRIPTION"),
                usage=getattr(module, "USAGE_EXAMPLE"),
            )
        )

    command_text = "\n".join(command_blocks) if command_blocks else "- None"
    return (
        f"You are a {role} agent.\n\n"
        "You have ONLY TWO possible actions:\n\n"
        "1. Execute a command:\n"
        '{"action":"command","name":"command_name","parameters":{...}}\n\n'
        "2. Provide final answer:\n"
        '{"action":"final_answer","content":"complete response"}\n\n'
        "CRITICAL RULES:\n"
        "- Output EXACTLY ONE JSON object\n"
        "- NO extra text before or after JSON\n"
        "- NO multiple JSON objects\n"
        "- NO explanations outside JSON\n\n"
        "AVAILABLE COMMANDS:\n"
        f"{command_text}\n"
    )


def init_openai_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is required")
    return OpenAI(api_key=api_key)


def collect_streaming_response(stream: Any) -> str:
    chunks: list[str] = []
    for event in stream:
        delta = getattr(event.choices[0].delta, "content", None)
        if delta:
            chunks.append(delta)
    return "".join(chunks)


def truncate_output(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS]


def validate_command_action(action: dict[str, Any], registry: dict[str, Any]) -> None:
    if action["name"] not in registry:
        raise ValueError(f"Command not allowed: {action['name']}")


def execute_command_action(action: dict[str, Any], registry: dict[str, Any]) -> str:
    module = registry[action["name"]]
    try:
        result = module.execute(action.get("parameters", {}))
    except Exception as exc:
        result = f"ERROR: {exc}"
    if not isinstance(result, str):
        result = f"ERROR: command returned non-string output"
    return truncate_output(result)


def call_llm(client: OpenAI, model: str, history: list[dict[str, str]]) -> str:
    stream = client.chat.completions.create(model=model, messages=history, stream=True)
    return collect_streaming_response(stream)


def fallback_final_answer(step: int, reason: str) -> str:
    return f"Final answer: terminated at step {step}. {reason}"


def run_react_loop(client: OpenAI, config: dict[str, Any], history: list[dict[str, str]], command_registry: dict[str, Any]) -> str:
    recent_actions: list[str] = []
    step = 0
    retries = 0

    while step < MAX_STEPS:
        step += 1
        try:
            response_text = call_llm(client, config["model"], history)
            log_io("assistant", response_text)
            action = validate_action_payload(parse_first_json_object(response_text))
            action_key = json.dumps(action, sort_keys=True)

            recent_actions.append(action_key)
            recent_actions = recent_actions[-3:]
            if len(recent_actions) == 3 and recent_actions[0] == recent_actions[1] == recent_actions[2]:
                return fallback_final_answer(step, "loop detected")

            if action["action"] == "final_answer":
                return action["content"]

            validate_command_action(action, command_registry)
            result = execute_command_action(action, command_registry)
            history.append({"role": "assistant", "content": response_text})
            history.append({"role": "user", "content": f"Observation: {result}"})
            log_io("observation", result)
            history[:] = trim_history(history)
            retries = 0
            log_jsonl({"step": step, "action": action["name"], "parameters": action.get("parameters", {}), "result": result, "error": None, "duration_ms": 0})
        except Exception as exc:
            retries += 1
            history.append({"role": "user", "content": f"Previous response contained error.\nYou MUST output exactly one valid JSON.\n\nLast error:\n{exc}"})
            log_io("error", str(exc))
            history[:] = trim_history(history)
            if retries >= MAX_RETRIES_PER_STEP:
                return fallback_final_answer(step, f"retry limit reached: {exc}")

    return fallback_final_answer(step, "MAX_STEPS reached")


def main(argv: list[str] | None = None) -> int:
    global VERBOSE
    args = parse_args(argv)
    VERBOSE = bool(args.verbose)
    config = load_config(args.config)
    config = merge_cli_with_config(config, args)
    validate_runtime_config(config)
    apply_limits_from_config(config)

    init_logger()
    all_modules = discover_command_modules()
    allowed_modules = filter_commands_by_permissions(all_modules, config["permissions"])
    command_registry = build_command_registry(allowed_modules)

    system_prompt = build_system_prompt(config["role"], allowed_modules)
    history = init_history(system_prompt + "\n" + config.get("base_system_prompt", ""), config["prompt"])
    log_io("prompt", config["prompt"])
    client = init_openai_client()
    log_jsonl(
        {
            "step": 0,
            "action": "init",
            "parameters": {"role": config["role"], "model": config["model"], "max_context_messages": MAX_CONTEXT_MESSAGES, "loaded_commands": sorted(command_registry.keys())},
            "result": "initialized",
            "error": None,
            "duration_ms": 0,
            "history_size": len(history),
        }
    )

    final_answer = run_react_loop(client, config, history, command_registry)
    log_io("final_answer", final_answer)
    print(final_answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
