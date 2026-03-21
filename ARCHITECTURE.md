# Architecture

## Overview
This repository is a local, multi-agent CLI framework that runs OpenAI models in a strict JSON action loop. The system is centered on a single runtime (`agent.py`) that loads role configurations from YAML, dynamically discovers command plugins, executes model-selected actions, and records structured JSONL logs for observability.

At a high level, the architecture consists of:
- **Runtime orchestration layer** (`agent.py`)
- **Role/configuration layer** (`agents/*.yaml`)
- **Command/plugin layer** (`commands/*.py`)
- **Logging/telemetry layer** (`logs/*.jsonl`)
- **Terminal UI layer** (`tui/*.py`)
- **Auxiliary metadata** (`ai_config.json`, `README.md`, `todo.txt`, `issue.log`)

---

## Repository Structure
- `agent.py` — main runtime, CLI entrypoint, model loop, command dispatch, child-agent spawning, logging
- `agents/`
  - `code.yaml` — coding specialist profile
  - `console.yaml` — shell-oriented helper profile
  - `plan.yaml` — planning specialist profile
  - `review.yaml` — review specialist profile
  - `smart_code.yaml` — orchestration/validation profile
- `commands/`
  - `read_file.py`, `write_file.py`, `append_to_file.py`
  - `replace_in_file.py`, `text_block_replace.py`
  - `ls.py`, `linux_command.py`, `run_agent.py`
- `tui/`
  - `app.py` — hourly token dashboard (currently missing entrypoint call)
  - `tui2.py` — per-minute dashboard variant (also missing entrypoint call)
  - `tui3.py` — advanced dashboard variant (partially inspected)
- `logs/` — JSONL runtime logs
- `ai_config.json` — external/auxiliary config metadata (not wired into runtime)
- `README.md` — user-facing documentation

---

## Runtime Architecture (`agent.py`)

### Core Responsibilities
`Agent` encapsulates the full execution lifecycle:
1. Load runtime limits and configuration
2. Discover commands dynamically from `commands/`
3. Discover available child agents from `agents/`
4. Build strict system prompt with allowed commands/agents
5. Execute iterative model loop with retries and guardrails
6. Dispatch commands and collect observations
7. Support hierarchical delegation via child process spawning
8. Persist structured logs (`session_start`, `step`, `session_end`)

### Initialization Flow
On startup, the runtime:
- Reads selected YAML config (`agents/<name>.yaml`)
- Resolves model (CLI override or config default)
- Validates `OPENAI_API_KEY`
- Instantiates `Agent(config, model, depth, agent_name, verbose, log_path)`

During `Agent.__init__`:
- Limits are loaded from `config.limits` with global fallbacks
- Logs directory is created (`./logs`)
- Log file path is selected (or inherited from parent via `--log-path`)
- Session start is logged
- Commands and agents are discovered
- System prompt is generated

### Prompt Construction
`_build_system_prompt()` composes a strict instruction contract including:
- Required JSON-only output format
- Allowed actions (`command`, `final_answer`)
- Critical behavioral rules
- Enumerated allowed commands with descriptions/examples
- Enumerated allowed child agents
- Safety constraints

This prompt is role-aware (`role`, `base_system_prompt`) and permission-aware (`permissions`, `allowed_agents`).

### Model Interaction Loop
`run(initial_prompt)` executes a bounded loop:
- Maintains conversation history (`system` + recent context window)
- Calls OpenAI Responses API in streaming mode
- Accumulates text deltas into `full_response`
- Extracts first valid JSON object from output (`_extract_json`)
- Retries malformed outputs up to `MAX_RETRIES_PER_STEP`
- Appends command observations back into history
- Terminates on valid `final_answer`, loop detection, parse failure, or max steps

### JSON Parsing Strategy
`_extract_json()`:
- Strips common markdown fences
- Scans for `{` positions
- Uses `json.JSONDecoder().raw_decode` from each candidate start
- Returns first parsed dict

This is resilient to extra surrounding text and partial formatting noise.

### Command Dispatch
`execute_command(name, params, step)`:
- Intercepts `run_agent` and routes to internal `_run_agent`
- Otherwise dispatches to dynamically loaded command handler
- Wraps handler exceptions into `ERROR:` strings

Permission enforcement occurs in the main loop before dispatch:
- If command not in `config.permissions`, returns permission error observation

### Child-Agent Delegation
`_run_agent(params, step)` implements hierarchical execution:
- Enforces depth and child-count limits
- Requires `agent` and `prompt` parameters
- Creates dedicated child log path
- Spawns subprocess: `python agent.py --agent ... --prompt ... --depth ... --log-path ...`
- Applies timeout (`CHILD_AGENT_TIMEOUT`)
- Returns child stdout as `FINAL_ANSWER: ...` on success

### Guardrails and Limits
Global defaults (overridable in config where supported):
- `MAX_STEPS = 30`
- `MAX_RETRIES_PER_STEP = 3`
- `MAX_OUTPUT_CHARS = 300000`
- `MAX_CONTEXT_MESSAGES = 20`
- `MAX_AGENT_DEPTH = 3`
- `MAX_CHILD_AGENTS = 5`
- `CHILD_AGENT_TIMEOUT = 600`

Additional protections:
- Repeated-action loop detection (3 identical recent actions)
- Rejection of invalid `final_answer` content that wraps JSON action objects
- Output truncation before history/logging

### Logging Model
Each session writes JSONL entries to one file:
- `session_start`
- `step` (action, parameters, truncated result, metadata)
- `session_end` (token totals)

Token accounting is collected from API usage fields and aggregated in-session.

---

## Agent Configuration Layer (`agents/*.yaml`)

### Shared Schema (as used by runtime)
- `role`
- `model`
- `temperature`
- `max_tokens`
- `permissions` (allowed command names)
- `allowed_agents` (for delegation)
- `base_system_prompt`
- `limits` (`max_steps`, `max_depth`, `max_children`)

### Defined Roles
- **code**: broad file/shell editing permissions + `run_agent`; allowed child: `plan`
- **console**: shell/file utility profile without delegation
- **plan**: read-only planning profile (`read_file`, `ls`)
- **review**: inspection profile with shell access
- **smart_code**: orchestrator profile with only `run_agent`; allowed children: `code`, `review`

### Notable Configuration Observations
- `code.yaml` contains a minor typo in base prompt text (`specialis`)
- `smart_code.yaml` prompt includes minor spelling/numbering issues but remains functional
- Runtime tolerates missing `allowed_agents` by defaulting to empty list

---

## Command Plugin Architecture (`commands/*.py`)

### Plugin Contract
Each command module is expected to expose:
- `COMMAND_NAME` (string)
- `DESCRIPTION` (string)
- `USAGE_EXAMPLE` (string)
- `execute(parameters: dict) -> str` (or fallback `run` callable)

Runtime discovery is dynamic via `importlib.util.spec_from_file_location`.

### Implemented Commands
- `read_file`: UTF-8 text read
- `write_file`: overwrite/create file, create parent dirs
- `append_to_file`: append content, create parent dirs
- `replace_in_file`: single unique text replacement
- `text_block_replace`: functionally equivalent to `replace_in_file`
- `ls`: directory listing
- `linux_command`: shell command execution with simple blocked-pattern checks
- `run_agent`: placeholder module returning `ERROR: Not implemented`

### Dispatch Nuance for `run_agent`
Although `commands/run_agent.py` exists, runtime intercepts `run_agent` internally and does not rely on this module for normal operation.

### Security Posture
`linux_command` uses `subprocess.run(..., shell=True)` with a small denylist (`rm -rf`, `shutdown`, etc.). This is useful but not a hardened sandbox.

---

## TUI / Observability Layer (`tui/*.py`)

### `tui/app.py`
- Reads logs from `./logs`
- Parses timestamps and token usage from multiple possible record shapes
- Aggregates token totals by model and by agent over last 12 hours
- Renders live Rich dashboard with sparkline bars
- Refreshes periodically
- **Current issue**: file ends with `if __name__ == "__main__":` and does not call `main()`

### `tui/tui2.py`
- Similar Rich dashboard
- Aggregates per-minute since app start
- Tracks model and agent totals with minute-level sparklines
- **Current issue**: also ends with `if __name__ == "__main__":` without `main()` call

### `tui/tui3.py`
- More advanced dashboard variant (partially inspected)
- Includes richer formatting and expanded token extraction logic

---

## Data and Control Flow

### Primary Control Flow
1. CLI receives `--agent` and `--prompt`
2. Runtime loads YAML config
3. Runtime builds system prompt from role + permissions
4. Model emits JSON action
5. Runtime validates and executes action
6. Observation is fed back as user message
7. Loop continues until termination condition

### Delegation Flow
1. Parent emits `run_agent`
2. Runtime validates depth/child limits
3. Child process launched with inherited context via CLI args
4. Child runs independent loop and logs to dedicated file
5. Parent receives child final output as observation text

### Logging Flow
- Every session writes structured JSONL records
- TUI readers scan log files and aggregate token metrics

---

## Architectural Strengths
- Clear separation of runtime, config, commands, and UI
- Dynamic command discovery enables easy extensibility
- Strict JSON protocol simplifies deterministic tool execution
- Built-in bounded execution and retry logic
- Hierarchical delegation with explicit depth/child limits
- Structured logs support post-hoc analysis and live dashboards

---

## Architectural Risks / Gaps
- `linux_command` safety model is minimal for production threat models
- `run_agent` command module is a stub (runtime interception hides this)
- Duplicate replacement commands increase maintenance surface
- TUI entrypoint guards in `app.py` and `tui2.py` are incomplete
- `ai_config.json` command names diverge from actual runtime command set and appears unused by `agent.py`

---

## Extensibility Notes

### Adding a Command
1. Create `commands/<name>.py` with required metadata and `execute`
2. Add command name to target agent `permissions`
3. Runtime auto-discovers on next run

### Adding an Agent Role
1. Create `agents/<role>.yaml`
2. Define model, prompt, permissions, limits
3. Invoke via `--agent <role>`

### Enhancing Safety
Potential hardening directions:
- Replace shell denylist with allowlist
- Avoid `shell=True` where possible
- Add path sandboxing/chroot-like constraints
- Add stricter output and runtime quotas per command

---

## Relationship to `README.md`
The README’s conceptual architecture aligns with the implementation in `agent.py`, command modules, and TUI/logging design. A few documented caveats (TUI entrypoint issue, duplicate replace commands, `ai_config.json` mismatch) are consistent with current repository state.
