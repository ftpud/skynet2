import json
import re


def build_system_prompt(config: dict, command_info: dict, agent_info: dict) -> str:
    role = config.get("role", "assistant")
    base = config.get("base_system_prompt", "").strip()

    cmd_list = ""
    allowed = config.get("permissions", [])
    for name in allowed:
        if name not in command_info:
            continue
        info = command_info[name]
        cmd_list += f"• {name}\n  {info['description']}\n  Example: {info['usage_example']}\n\n"

    allowed_agents_list = ""
    allowed_agents = config.get("allowed_agents", [])
    for name in allowed_agents:
        info = agent_info.get(name)
        if not info:
            continue
        allowed_agents_list += f"• {name}\n  {info['description']}\n\n"

    hooks = config.get("hooks", {}) or {}
    hooks_text = ""
    if hooks:
        hooks_text = "\nAGENT HOOKS (executed automatically by runtime):\n" + "\n".join(
            f"- {name}: {script}" for name, script in hooks.items() if script
        ) + "\n"

    return f"""You are a {role} agent.

{base}{hooks_text}

You MUST respond with EXACTLY ONE valid JSON object and nothing else.

Possible actions:

1. Execute allowed command
{{
  \"action\": \"command\",
  \"name\": \"<command_name>\",
  \"parameters\": {{ ... }}
}}

2. Give final answer and stop
{{
  \"action\": \"final_answer\",
  \"content\": \"PLAIN TEXT ONLY\"
}}

CRITICAL RULES:
- ONLY output valid JSON — no explanations, no markdown, no blocks
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


def extract_all_json_actions(text: str) -> list[dict]:
    text = text.strip()
    decoder = json.JSONDecoder()
    actions: list[dict] = []

    def _collect_from(src: str):
        starts = [i for i, ch in enumerate(src) if ch == '{']
        for start in starts:
            try:
                obj, _end = decoder.raw_decode(src[start:])
                if isinstance(obj, dict) and obj.get("action") in ("command", "final_answer"):
                    actions.append(obj)
            except json.JSONDecodeError:
                pass

    _collect_from(text)
    repaired = re.sub(r',\s*([}\]])', r'\1', text)
    if repaired != text:
        _collect_from(repaired)

    if actions:
        seen = set()
        unique = []
        for a in actions:
            key = json.dumps(a, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            unique.append(a)
        return unique

    depth = 0
    in_string = False
    escape = False
    block_start: int | None = None

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            if depth == 0:
                block_start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and block_start is not None:
                block = text[block_start:i + 1]
                try:
                    obj = json.loads(block)
                    if isinstance(obj, dict) and obj.get("action") in ("command", "final_answer"):
                        actions.append(obj)
                except json.JSONDecodeError:
                    try:
                        obj = json.loads(re.sub(r',\s*([}\]])', r'\1', block))
                        if isinstance(obj, dict) and obj.get("action") in ("command", "final_answer"):
                            actions.append(obj)
                    except json.JSONDecodeError:
                        pass
                block_start = None

    seen = set()
    unique = []
    for a in actions:
        key = json.dumps(a, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        unique.append(a)
    return unique


def extract_json(text: str) -> dict | None:
    actions = extract_all_json_actions(text)
    return actions[0] if actions else None


def is_codex(model: str) -> bool:
    return "codex" in model.lower()


def extract_usage(usage, api_type: str) -> tuple[int, int]:
    if usage is None:
        return (0, 0)
    if api_type == "chat_completions":
        return (
            int(getattr(usage, "prompt_tokens", 0) or 0),
            int(getattr(usage, "completion_tokens", 0) or 0),
        )
    return (
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
    )
