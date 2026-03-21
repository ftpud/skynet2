# AI Agent Runtime

A lightweight, production-oriented Python AI agent runtime that executes a bounded ReAct loop with a strict JSON action protocol.

## What this project is

This repository provides a self-contained agent system that:
- Runs a **reason → act → observe** loop
- Accepts only **one JSON action per model turn**
- Executes only **allowed commands** from agent config
- Supports **hierarchical delegation** via `run_agent`
- Enforces **limits** (steps, retries, context, depth, children)
- Logs execution in **structured JSONL**

Core runtime: `agent.py`

## Repository layout

- `agent.py` — CLI entrypoint and runtime loop
- `agents/` — YAML agent profiles (role/model/permissions/limits)
- `commands/` — pluggable command modules
- `logs/` — JSONL runtime logs
- `ARCHITECTURE.md` — implementation architecture and behavior notes

## Requirements

- Python 3.11+
- `openai`
- `PyYAML`
- Environment variable: `OPENAI_API_KEY`

Install dependencies:

```bash
pip install openai pyyaml
```

## CLI usage

```bash
python agent.py --agent <agent_name> --prompt "Your task here" [--model <model_name>]
```

Common options used by runtime:
- `--agent` (required)
- `--prompt` (required)
- `--model` (optional override)
- `--depth` (internal for child agents)
- `--verbose`

## Agent configuration (`agents/<name>.yaml`)

Typical fields:

```yaml
role: "coder"
model: "gpt-5.4"
temperature: 0.7
max_tokens: 4096

permissions:
  - read_file
  - write_file
  - append_to_file
  - replace_in_file
  - text_block_replace
  - linux_command
  - run_agent
  - ls

base_system_prompt: ""

limits:
  max_steps: 30
  max_depth: 3
  max_children: 5
```

## Command contract

Each module in `commands/` should expose:
- `COMMAND_NAME: str`
- `DESCRIPTION: str` (recommended)
- `USAGE_EXAMPLE: str` (recommended)
- `execute(parameters: dict) -> str` (or `run` fallback)

Runtime behavior:
- Commands are dynamically discovered
- Only commands in `permissions` are executable
- Exceptions are converted to `ERROR: ...`
- Output is truncated to configured max output size

## JSON interaction protocol

The model is instructed to return exactly one JSON object per turn:

```json
{
  "action": "command",
  "name": "read_file",
  "parameters": {"path": "README.md"}
}
```

or

```json
{
  "action": "final_answer",
  "content": "complete response"
}
```

No extra text is allowed outside the JSON object.

## Runtime loop (high level)

1. Load agent config and allowed commands
2. Build strict system prompt
3. Call model (streaming)
4. Extract first valid JSON object
5. Execute command or return final answer
6. Append observation and continue until termination

Termination conditions include:
- `final_answer`
- max steps reached
- repeated-loop detection
- parse failure after retries

## Delegation with `run_agent`

`run_agent` is handled by runtime with safeguards:
- max depth
- max child count
- child timeout

Returns:
- `FINAL_ANSWER: <child result>` on success
- `ERROR: ...` on failure

## Logging

Each step is logged to JSONL in `logs/` with fields like:
- `step`
- `action`
- `parameters`
- `result`
- `timestamp`

## Notes on spec vs implementation

For exact implementation details and current conformance notes, see:
- `ARCHITECTURE.md`

This file documents known differences between strict requirements and current runtime behavior.
