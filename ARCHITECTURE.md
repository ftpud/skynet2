# Architecture

## System Overview
This repository implements a lightweight, production-oriented AI agent runtime in Python (`agent.py`) that follows a bounded ReAct-style loop:
- Model produces exactly one JSON action
- Runtime executes an allowed command or returns a final answer
- Command result is fed back as an observation
- Loop continues until `final_answer` or limits are reached

The system is designed around:
- **Single-role agents** configured via YAML in `agents/`
- **Dynamic command loading** from `commands/`
- **Strict JSON protocol enforcement** in the system prompt and parser
- **Hierarchical execution** via `run_agent` with depth/child limits
- **Structured JSONL logging** under `logs/`

---

## Repository Layout
- `agent.py` — main runtime, CLI entrypoint, loop orchestration, parsing, logging, command/agent discovery
- `agents/` — per-agent YAML configs (role, model, permissions, limits)
  - `main.yaml` — orchestrator profile
  - `code.yaml` — coding profile (includes file-edit commands + `run_agent`)
  - `plan.yaml` — planning profile (read-only discovery)
  - `research.yaml` — additional profile (present in tree)
- `commands/` — pluggable command modules
  - `read_file.py`, `write_file.py`, `append_to_file.py`
  - `replace_in_file.py`, `text_block_replace.py`
  - `ls.py`, `linux_command.py`, `run_agent.py`
- `logs/` and `*.log` — runtime logs/artifacts
- `README.md` — requirements/specification and behavior contract

---

## High-Level Component Model

```text
User CLI
  |
  v
agent.py (Agent runtime)
  |- loads agent config (agents/<name>.yaml)
  |- discovers commands (commands/*.py)
  |- builds strict system prompt
  |- runs ReAct loop with OpenAI Responses API
  |
  +--> Command execution layer
  |      |- local command handlers (dynamic modules)
  |      |- special-cased run_agent (subprocess child)
  |
  +--> Logging layer (JSONL in logs/)
```

Core responsibilities:
- **Orchestration:** step loop, retries, context windowing, termination
- **Policy enforcement:** permissions, limits, JSON action schema
- **Execution:** invoke command handlers and capture observations
- **Resilience:** parse recovery, retry feedback, exception-to-string conversion

---

## Runtime Lifecycle

## 1) Startup / Initialization
1. CLI parses:
   - `--agent` (required)
   - `--prompt` (required)
   - `--model` (optional override)
   - `--depth` (internal for child agents)
   - `--verbose`
2. Loads `agents/<agent>.yaml`
3. Validates model and `OPENAI_API_KEY`
4. Instantiates `Agent`:
   - loads limits from config (with global defaults)
   - creates log file `logs/<agent>_<timestamp>.jsonl`
   - discovers commands from `commands/`
   - discovers available agents from `agents/`
   - builds system prompt with allowed commands/agents

## 2) ReAct Loop
For each step (up to `max_steps`):
1. Compose messages = system prompt + bounded history
2. Call OpenAI Responses API (streaming)
3. Accumulate text deltas
4. Extract first valid JSON object
5. If parse fails, append corrective feedback and retry (up to retry limit)
6. Execute action:
   - `command` → validate permission, execute, append `Observation: ...`
   - `final_answer` → validate content is plain text (not wrapped JSON), print and exit
7. Detect loops (3 identical recent actions) and terminate if stuck

## 3) Termination Paths
- Valid `final_answer`
- Parse failure after retries
- Loop detected
- Max steps reached

---

## Command Architecture
Commands are discovered dynamically from `commands/*.py` using importlib.

Expected module contract (as implemented by loader):
- `COMMAND_NAME` (string)
- optional `DESCRIPTION`
- optional `USAGE_EXAMPLE`
- callable `execute(parameters)` (or fallback `run`)

At runtime:
- Only commands listed in agent `permissions` are executable
- Unknown/unloaded commands are ignored at discovery or rejected at execution
- Command exceptions are caught and converted to `ERROR: ...` strings
- Output is truncated to `max_output_chars`

### Special Case: `run_agent`
`agent.py` intercepts `run_agent` and handles it internally:
- Enforces depth and child-count limits
- Spawns child process: `python agent.py --agent ... --prompt ... --depth ...`
- Applies timeout (`CHILD_AGENT_TIMEOUT`)
- Returns `FINAL_ANSWER: <stdout>` on success or `ERROR: ...` on failure

---

## Agent Configuration Model (`agents/*.yaml`)
Common fields used by runtime:
- `role` — inserted into system prompt
- `model` — default model
- `temperature`, `max_tokens` — passed to model call
- `permissions` — allowlist of executable commands
- `allowed_agents` — listed in prompt for delegation visibility
- `base_system_prompt` — extra instruction text
- `limits`:
  - `max_steps`
  - `max_depth`
  - `max_children`

### Notable configured profiles
- **main**: orchestration-oriented, broad command access
- **code**: coding/editing command set + delegation to `plan`
- **plan**: read-only planning profile (`read_file`, `ls`)

---

## JSON Protocol and Parsing
The runtime enforces a strict two-action JSON contract in the system prompt:
- command action
- final_answer action

Parsing behavior in `agent.py`:
- strips common markdown fences
- scans for `{` positions
- attempts `json.JSONDecoder().raw_decode(...)`
- accepts first parsed dict object

If invalid:
- appends explicit correction message to history
- retries within per-step retry budget

Additional guard:
- rejects `final_answer.content` that itself contains wrapped action JSON

---

## Context, State, and Data Flow
State held in-memory per agent instance:
- `history` (bounded to `MAX_CONTEXT_MESSAGES`)
- `recent_actions` (last 3 for loop detection)
- `spawned_children` counter

Data flow:
1. User prompt enters history
2. Model emits JSON action
3. Runtime executes command
4. Observation appended as user message
5. Loop repeats until completion

Persistence:
- Structured step logs written to JSONL (`logs/...jsonl`)
- No database/state store beyond files/logs

---

## Observability and Operations
Logging (`_log`) records:
- step
- action
- parameters
- truncated result preview
- timestamp

Operational safeguards:
- bounded steps/retries/context
- permission checks before command execution
- child-agent depth/count/timeout controls
- exception handling around API and command execution

---

## Extension Guide
### Add a new command
1. Create `commands/<name>.py`
2. Define `COMMAND_NAME`, `DESCRIPTION`, `USAGE_EXAMPLE`
3. Implement `execute(parameters: dict) -> str`
4. Add command name to target agent `permissions`

### Add a new agent profile
1. Create `agents/<agent>.yaml`
2. Set role/model/permissions/limits
3. Invoke via CLI `--agent <agent>`
4. Optionally expose in another agent’s `allowed_agents`

---

## Known Gaps vs README Requirements (Current Implementation)
- `MAX_OUTPUT_CHARS` in code is `300000` (README states `2000`)
- Retry loop uses global `MAX_RETRIES_PER_STEP`, not config override
- `_extract_json` does not implement trailing-comma/single-quote repair described in README
- `run_agent` command is handled internally; module exists but runtime bypasses it
- `allowed_agents` is informational in prompt; enforcement is not explicit in `_run_agent`

These are implementation realities and should be considered if strict spec conformance is required.
