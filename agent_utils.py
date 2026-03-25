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

    tool_use_rules = config.get("tool_use_rules", "").strip()
    if tool_use_rules:
        tool_use_rules = "\nTOOL USE:\n" + tool_use_rules + "\n"

    return f"""You are a {role} agent.

{base}{hooks_text}{tool_use_rules}
You MUST respond with valid JSON only and nothing else.

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
- If you need more than one step, return all needed actions together in one JSON array
- Default expectation: deliver working results, not just a plan
- Do not stop at analysis when you can continue to implementation, verification, and a concise closeout
- Prefer dedicated file tools over shell commands when a dedicated tool exists
- Batch related reads together when possible instead of reading files one-by-one
- NEVER ask the user for confirmation, clarification, or approval — just execute
- If details are ambiguous, make the most reasonable choice and proceed
- Always perform all required steps by commands

ALLOWED COMMANDS:
{cmd_list}
ALLOWED AGENTS:
{allowed_agents_list}

STRATEGY:
- Think first, then act
- Prefer the shortest reliable path
- Reuse existing patterns before adding new logic
- If command fails, try a different approach instead of looping
- Keep edits minimal, coherent, and behavior-safe
- End with a concrete result or a precise blocker

CONTEXT MANAGEMENT:
- Old observations are auto-trimmed; re-read files if you need their full contents again
- When you see a "[context: … consider compact_history]" hint, call compact_history
  before your next action if you still have significant work remaining
- Write a thorough summary: key facts, file paths, line numbers, what was done, what remains
- Do NOT compact if you are about to give final_answer — just finish

SAFETY:
- Never run destructive commands unless explicitly requested
- Never revert user changes you did not make
"""


def extract_all_json_actions(text: str) -> list[dict]:
    text = text.strip()
    if not text:
        return []

    def _is_action(obj) -> bool:
        return isinstance(obj, dict) and obj.get("action") in ("command", "final_answer")

    def _dedupe(items: list[dict]) -> list[dict]:
        seen = set()
        unique = []
        for item in items:
            key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    candidates = [text]
    repaired = re.sub(r",\s*([}\]])", r"\1", text)
    if repaired != text:
        candidates.append(repaired)

    actions: list[dict] = []
    decoder = json.JSONDecoder()

    for src in candidates:
        try:
            parsed = json.loads(src)
            if _is_action(parsed):
                return [parsed]
            if isinstance(parsed, list):
                list_actions = [item for item in parsed if _is_action(item)]
                if list_actions:
                    return _dedupe(list_actions)
        except json.JSONDecodeError:
            pass

        starts = [i for i, ch in enumerate(src) if ch in "[{"]
        for start in starts:
            try:
                obj, _end = decoder.raw_decode(src[start:])
            except json.JSONDecodeError:
                continue

            if _is_action(obj):
                actions.append(obj)
            elif isinstance(obj, list):
                actions.extend(item for item in obj if _is_action(item))

    if actions:
        return _dedupe(actions)

    depth = 0
    in_string = False
    escape = False
    block_start: int | None = None

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "[{":
            if depth == 0:
                block_start = i
            depth += 1
        elif ch in "]}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and block_start is not None:
                block = text[block_start:i + 1]
                try_blocks = [block]
                repaired_block = re.sub(r",\s*([}\]])", r"\1", block)
                if repaired_block != block:
                    try_blocks.append(repaired_block)
                for candidate in try_blocks:
                    try:
                        obj = json.loads(candidate)
                    except json.JSONDecodeError:
                        continue
                    if _is_action(obj):
                        actions.append(obj)
                        break
                    if isinstance(obj, list):
                        actions.extend(item for item in obj if _is_action(item))
                        break
                block_start = None

    return _dedupe(actions)


def extract_json(text: str) -> dict | None:
    actions = extract_all_json_actions(text)
    return actions[0] if actions else None


def is_codex(model: str) -> bool:
    return "codex" in model.lower()


def extract_usage(usage, api_type: str) -> tuple[int, int]:
    if usage is None:
        return (0, 0)

    def _read(obj, *names: str) -> int:
        for name in names:
            value = getattr(obj, name, None)
            if value is None and isinstance(obj, dict):
                value = obj.get(name)
            if value is not None:
                try:
                    return int(value or 0)
                except Exception:
                    continue
        return 0

    if api_type == "chat_completions":
        return (
            _read(usage, "prompt_tokens", "input_tokens"),
            _read(usage, "completion_tokens", "output_tokens"),
        )

    if api_type == "responses":
        input_tokens = _read(usage, "input_tokens", "prompt_tokens")
        output_tokens = _read(usage, "output_tokens", "completion_tokens")
        # NOTE: cached_tokens and reasoning_tokens are already included in
        # input_tokens and output_tokens respectively — do NOT add them again.
        return (input_tokens, output_tokens)

    return (
        _read(usage, "input_tokens", "prompt_tokens"),
        _read(usage, "output_tokens", "completion_tokens"),
    )


FILE_OBSERVATION_RE = re.compile(r"(?ms)^---\s+([^\n]+?)\s+---\n")


def _compress_text_block(body: str, limit: int) -> str:
    body = body.strip("\n")
    if len(body) <= limit:
        return body
    head = body[: max(0, limit // 2)].rstrip()
    tail_budget = max(0, limit - len(head) - 32)
    tail = body[-tail_budget:].lstrip() if tail_budget else ""
    omitted = max(0, len(body) - len(head) - len(tail))
    if not tail:
        return f"{head}\n[…omitted {omitted} chars…]"
    return f"{head}\n[…omitted {omitted} chars…]\n{tail}"


def compress_observation(text: str, file_preview_chars: int = 1200, generic_preview_chars: int = 4000, compact_preview_chars: int = 2000) -> str:
    text = (text or "").strip()
    if not text:
        return text

    matches = list(FILE_OBSERVATION_RE.finditer(text))
    if matches:
        parts = []
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            name = m.group(1).strip()
            body = text[start:end]
            compressed = _compress_text_block(body, file_preview_chars)
            parts.append(f"--- {name} ---\n{compressed}".rstrip())
        joined = "\n\n".join(parts)
        return _compress_text_block(joined, compact_preview_chars)

    return _compress_text_block(text, generic_preview_chars)
