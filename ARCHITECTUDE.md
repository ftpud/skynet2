# ARCHITECTUDE

## Overview
This project is a lightweight, production-oriented ReAct-style  agent runtime. It executes a strict loop where an LLM must return exactly one  object per step, either to run a command or provide a final answer.

Core goals of the architecture:
- Deterministic agent protocol (strict  actions)
- Bounded execution (step, depth, child, timeout limits)
- Pluggable commands and agent configs
- Provider abstraction (OpenAI and Claude)
- Structured logging for observability

---

## High-Level Runtime Flow
1. **CLI entrypoint** (`agent.py` + `agent_cli.py`)
   - Parse runtime arguments.
   - Load selected agent YAML config.
   - Resolve model/provider and validate API keys.

2. **Agent initialization** (`Agent.__init__` in `agent.py`)
   - Load command handlers dynamically from `commands/`.
   - Load available agent metadata from `agents/`.
   - Build system prompt from config + discovered capabilities.
   - Initialize logging and optional verbose logging.
   - Execute startup hook (`on_run_start`) if configured.

3. **Execution loop** (`Agent.run`)
   - Optionally run startup observation shell commands and inject as observations.
   - Append user prompt to history.
   - For each step (bounded by `MAX_STEPS` / config override):
     - Call model with system prompt + recent history window.
     - Parse  response robustly.
     - If `action=command`, execute permitted command and append observation.
     - If `action=final_answer`, print and terminate.
     - Detect repeated identical actions to prevent loops.

4. **Shutdown**
   - Execute finish hook (`on_run_finish`) with token stats.
   - Write session end log entry.

---

## Component Architecture

### 1) Orchestrator: `agent.py`
`Agent` is the central runtime coordinator.

Primary responsibilities:
- Provider client initialization (`OpenAI` or `Anthropic`)
- Runtime limits and state management
- Prompt/message assembly
- Model streaming calls and early  extraction
- Command dispatch and child-agent spawning
- History management and loop detection
- Logging and hook execution

Key internal subsystems:
- **Streaming output subsystem**: `_vstream`, `_vend_stream` for verbose token streaming.
- **Hook subsystem**: `_run_hook` executes configured shell hooks with agent context env vars.
- **Child agent subsystem**: `_run_agent` spawns nested agent process with depth/child limits.
- **Model abstraction**: `_call_model` handles provider-specific streaming APIs.

### 2) CLI + Config Loader: `agent_cli.py`
Responsibilities:
- Define CLI contract (`--agent`, `--prompt`, `--model`, provider flags, verbosity, startup observe, etc.).
- Load YAML config from `agents/<name>.yaml`.
- Resolve provider precedence:
  1. `--provider-override`
  2. `--provider`
  3. config `provider`
  4. default `openai`
- Validate required API key for selected provider.

### 3) Constants: `agent_constants.py`
Centralized hard limits:
- `MAX_STEPS = 30`
- `MAX_RETRIES_PER_STEP = 3`
- `MAX_OUTPUT_CHARS = 300000`
- `MAX_CONTEXT_MESSAGES = 20`
- `MAX_AGENT_DEPTH = 3`
- `MAX_CHILD_AGENTS = 5`
- `CHILD_AGENT_TIMEOUT = 600`

These are defaults; some are overridable via agent config `limits`.

### 4) Dynamic Discovery Loaders: `agent_loaders.py`
Two discovery pipelines:
- **Commands** (`load_commands`): imports each `commands/*.py`, extracts metadata (`COMMAND_NAME`, `DESCRIPTION`, `USAGE_EXAMPLE`) and callable handler (`execute` or fallback `run`).
- **Agents** (`load_agents`): reads each `agents/*.yaml`, extracts description from `description` or `role`.

Design benefit: extensibility without changing orchestrator code.

### 5) Logging Layer: `agent_logging.py`
L-based append-only logging:
- `session_start`
- `step`
- `session_end`

Each step log includes action, parameters, truncated result, timestamp, and runtime identity (agent/provider/model/depth).

### 6) Prompt + Parsing Utilities: `agent_utils.py`
- `build_system_prompt`: composes strict protocol prompt from role/base prompt/permissions/allowed agents/hooks.
- `extract_`: resilient parser that attempts:
  - direct decode from any `{` start
  - trailing-comma repair
  - largest balanced  object fallback
- `is_codex`: model capability hint.
- `extract_usage`: normalizes token usage fields across API types.

---

## Data and Control Boundaries

### Agent Config Boundary (`agents/*.yaml`)
Config controls:
- role and base system prompt
- model/provider defaults
- command permissions
- allowed child agents
- limits overrides
- hooks and startup observations

This creates policy-driven behavior without code changes.

### Command Boundary (`commands/*.py`)
Commands are isolated modules loaded at runtime. The orchestrator only calls registered handlers with  parameters and stringifies results.

### Provider Boundary
`Agent._call_model` encapsulates provider differences:
- OpenAI Responses API path for Codex-like models
- OpenAI Chat Completions streaming path for others
- Claude streaming path with retry/escalation on token truncation

---

## Execution Safety Model

Safety controls implemented in runtime:
- Strict -only action protocol
- Permission check before command execution
- Max steps and retries per step
- Max context window size
- Output truncation for observations
- Child depth and child count limits
- Child process timeout
- Loop detection for repeated identical actions
- Non-destructive guidance embedded in system prompt

---

## Hierarchical Agent Architecture

`run_agent` enables recursive delegation:
- Parent validates depth/child quotas.
- Spawns child process (`python agent.py ...`) with incremented depth.
- Child has independent session/log lifecycle.
- Parent receives child stdout and wraps as observation.

This supports decomposition while preserving bounded execution.

---

## Observability and Diagnostics

### Standard logs
Stored in `logs/` as L, suitable for machine parsing.

### Verbose logs
Optional shared verbose stream file captures:
- streamed model output
- child command invocation details
- child stderr/final line snippets

### Hooks
Lifecycle hooks (`on_run_start`, `on_run_finish`) allow external instrumentation and automation with environment context.

---

## Error Handling Strategy

- Config/API key errors fail fast in CLI loader.
- Command import failures are isolated and skipped.
- Command execution exceptions are converted to `ERROR:` observations.
- Model call exceptions trigger retry with backoff.
- Invalid/non- model outputs trigger corrective feedback and retry.
- Persistent parse failure terminates gracefully with log entry.

---

## Extensibility Guide

### Add a new command
1. Create `commands/<name>.py`.
2. Define:
   - `COMMAND_NAME`
   - `DESCRIPTION`
   - `USAGE_EXAMPLE`
   - `execute(params)` (or `run(params)`)
3. Add command name to agent YAML `permissions`.

### Add a new agent profile
1. Create `agents/<agent>.yaml`.
2. Set role/model/provider/permissions/limits.
3. Optionally expose it via another agent’s `allowed_agents`.

No orchestrator edits required for either extension path.

---

## Architectural Strengths
- Clear separation of concerns across modules.
- Policy-driven behavior via YAML.
- Runtime-bounded and failure-aware loop.
- Provider abstraction with streaming support.
- Strong operational logging and hook points.
- Minimal coupling between orchestrator and command implementations.

## Architectural Tradeoffs
- Child-agent communication is process-based (simple, but higher overhead).
-  extraction is heuristic and may still fail on pathological outputs.
- Command sandboxing is policy-based, not OS-level isolation.
- Provider-specific logic is centralized in one method, which can grow complex.

---

## File Responsibility Summary
- `agent.py`: runtime orchestrator, model calls, loop, command dispatch, child spawning.
- `agent_cli.py`: argument parsing and runtime config/provider resolution.
- `agent_constants.py`: global execution limits.
- `agent_loaders.py`: dynamic command/agent discovery.
- `agent_logging.py`: L session/step logging.
- `agent_utils.py`: system prompt construction,  extraction, usage normalization.
- `agents/`: declarative agent policies.
- `commands/`: executable tool surface.
- `logs/`: runtime artifacts.
- `tests/`: validation suite.
- `tui/`: terminal UI layer.
