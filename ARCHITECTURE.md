# Agent Architecture

## Overview
`agent.py` implements a production-oriented, lightweight ReAct-style CLI agent that:
- Enforces strict single-JSON responses from the model
- Executes only permitted commands
- Supports hierarchical child-agent spawning
- Applies bounded execution limits (steps, retries, depth, output size)
- Logs step-by-step execution to JSONL

The runtime loop is: **Prompt → Model JSON action → Command execution / Final answer → Observation feedback → Repeat**.

---

## High-Level Components

### 1. CLI Entrypoint
At startup (`if __name__ == "__main__":`), the script:
1. Parses CLI args (`--agent`, `--prompt`, `--model`, `--depth`, `--verbose`)
2. Loads YAML config from `agents/<agent>.yaml`
3. Resolves model (CLI override or config)
4. Validates `OPENAI_API_KEY`
5. Instantiates `Agent`
6. Calls `agent.run(prompt)`

### 2. `Agent` Core Class
The `Agent` class encapsulates all orchestration:
- Config/model/depth state
- OpenAI client
- Conversation history
- Command registry and handlers
- Safety/limit controls
- Logging

### 3. Command Plugin System
Commands are dynamically loaded from `commands/*.py`:
- Required: `COMMAND_NAME` and callable `execute(params)` (or fallback `run(params)`)
- Optional: `DESCRIPTION`, `USAGE_EXAMPLE`

Loaded commands are split into:
- `command_info`: metadata for prompt construction
- `command_handlers`: executable callables

### 4. LLM Interaction Layer
Uses `self.client.responses.stream(...)` for streamed text deltas.
The agent accumulates output and parses a JSON object from it.

### 5. Execution + Feedback Loop
Each step:
1. Build messages (`system` + recent history)
2. Query model (with retries)
3. Parse JSON action
4. Execute command or finalize
5. Append observation back into history
6. Continue until final answer or limits reached

---

## Detailed Control Flow

## Initialization (`Agent.__init__`)
- Stores runtime parameters
- Initializes OpenAI client
- Initializes history and loop-detection buffer
- Reads limits from `config["limits"]` with global defaults
- Creates `logs/` and per-run JSONL log file
- Loads command plugins
- Builds system prompt including only permitted commands

## System Prompt Construction (`_build_system_prompt`)
Prompt includes:
- Agent role and base instructions from config
- Strict JSON output contract
- Allowed command list with descriptions/examples
- Strategy and safety rules

This is the primary policy boundary for model behavior.

## Main Loop (`run`)
Bounded by `max_steps`.

For each step:
1. Compose `messages` with system prompt + truncated history (`MAX_CONTEXT_MESSAGES`)
2. Attempt model call up to `MAX_RETRIES_PER_STEP`
3. Parse JSON via `_extract_json`
4. If parse fails repeatedly, terminate with error
5. Validate `action`
6. Loop detection: terminate if last 3 actions are identical
7. Branch:
   - `final_answer`: validate content is plain text (reject wrapped JSON), print and exit
   - `command`: permission-check, execute, append observation, continue
   - otherwise: inject corrective feedback

---

## JSON Parsing Strategy (`_extract_json`)
Robust parsing approach:
- Strips common markdown fences
- Scans for every `{` position
- Uses `json.JSONDecoder().raw_decode` from each candidate
- Returns first successfully parsed dict

This tolerates extra text around JSON and malformed prefixes.

---

## Command Execution Model

## `execute_command`
- Special-cases `run_agent` for hierarchical spawning
- Otherwise dispatches to loaded handler
- Wraps handler exceptions as `ERROR: ...`

## Permission Enforcement
Even if a command exists, it runs only if listed in `config["permissions"]`.
Otherwise observation is `ERROR: this command is not permitted`.

## Observation Feedback
After command execution:
- Assistant message stores the JSON action
- User message stores `Observation: <result>`

This preserves ReAct-style tool feedback for subsequent reasoning.

---

## Hierarchical Agent Spawning (`_run_agent`)
`run_agent` launches a child process of the same script with:
- `--agent <child_agent>`
- `--prompt <child_prompt>`
- `--depth parent+1`
- inherited model/verbosity options

Safety bounds:
- `max_depth`
- `max_children`
- subprocess timeout (`CHILD_AGENT_TIMEOUT`)

Child stdout is wrapped as `FINAL_ANSWER: ...`; failures return structured error text.

---

## Safety and Reliability Mechanisms

1. **Step bound**: `max_steps`
2. **Retry bound**: `MAX_RETRIES_PER_STEP` for invalid model output/API issues
3. **Context bound**: only recent `MAX_CONTEXT_MESSAGES`
4. **Output bound**: command output truncated to `MAX_OUTPUT_CHARS`
5. **Hierarchy bounds**: max depth + max child count + child timeout
6. **Loop detection**: abort on 3 identical consecutive actions
7. **Final-answer guard**: rejects JSON wrapped inside `final_answer.content`
8. **Permission gate**: command allowlist from config

---

## Logging
Each step writes JSONL to `logs/<agent>_<timestamp>.jsonl` with:
- step number
- action
- parameters
- truncated result preview
- timestamp

Logging failures are intentionally non-fatal.

---

## Configuration Contract (YAML)
Expected fields in `agents/<name>.yaml`:
- `role`: agent role label for prompt
- `base_system_prompt`: additional instruction text
- `model`: default model name
- `temperature`, `max_tokens`: model call settings
- `permissions`: list of allowed command names
- `limits` (optional):
  - `max_steps`
  - `max_depth`
  - `max_children`

---

## External Dependencies
- `openai` (Responses API streaming)
- `pyyaml`
- Python stdlib: argparse, importlib, json, os, re, subprocess, sys, time, datetime

---

## Architectural Summary
The design is a **bounded tool-using agent runtime** with:
- strict output protocol,
- dynamic command plugins,
- explicit permissioning,
- iterative observation-driven reasoning,
- and controlled multi-agent delegation.

It prioritizes operational safety and recoverability over autonomy by enforcing hard limits, retries, and validation at each stage.
