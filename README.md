# Lightweight ReAct Agent

A lightweight ReAct-style agent runtime that enforces a strict  action protocol, supports hierarchical child agents, and executes a controlled set of local commands.

## Features

- Strict **single  object** response protocol (`command` or `final_answer`)
- Pluggable command system via `commands/*.py`
- Multi-agent orchestration with bounded depth and child count (`run_agent`)
- Provider support:
  - OpenAI
  - Anthropic Claude
- Streaming model output handling with  extraction/recovery
- Session + step logging to L
- Optional verbose console logging and shared verbose log file
- Startup observation hooks (`--startup-observe`)
- Runtime hooks from agent config (`on_run_start`, `on_run_finish`, etc.)

## Project Structure

- `agent.py` — main runtime/orchestrator
- `agent_cli.py` — CLI argument parsing + runtime config loading
- `agent_loaders.py` — dynamic loading of commands and agent configs
- `agent_logging.py` — L logging helpers
- `agent_utils.py` — system prompt builder,  extraction, token usage helpers
- `agents/` — YAML agent definitions
- `commands/` — command implementations
- `logs/` — runtime logs
- `tests/` — tests
- `tui/` — terminal UI components

## Requirements

- Python 3.10+
- Dependencies:
  - `openai`
  - `pyyaml`
  - `anthropic` (only if using Claude provider)

Install example:

```bash
pip install openai pyyaml anthropic
```

## Environment Variables

Set API keys based on provider:

- OpenAI: `OPENAI_API_KEY`
- Claude: `ANTHROPIC_API_KEY`

## Quick Start

Run an agent config from `agents/<name>.yaml`:

```bash
python agent.py --agent code --prompt "List files in this repo"
```

With verbose output:

```bash
python agent.py --agent code --prompt "Inspect project map" --verbose
```

Force provider/model:

```bash
python agent.py --agent code --prompt "Do task" --provider openai --model gpt-4.1-mini
```

## CLI Options (All Supported Runtime Flags)

From `agent_cli.py`:

- `--agent` (required): agent config name (without `.yaml`)
- `--prompt` (required): initial task prompt
- `--model`: override model from config
- `--provider`: provider override for current run (`openai` or `claude`)
- `--provider-override`: force provider for parent + child agents
- `--depth`: internal nesting depth (used by runtime)
- `--log-path`: internal explicit log path
- `--verbose-log`: duplicate verbose output to file
- `--verbose-log-path`: shared verbose log file path
- `-v, --verbose`: print detailed progress
- `--startup-observe`: repeatable shell command injected as initial Observation

## Configuration Reference (`agents/*.yaml`)

Each agent YAML can define the following fields.

### Core Identity

- `role` (string): short role name used in prompt framing
- `description` (string): behavior and scope description

### Model/Provider

- `provider` (string, optional): `openai` or `claude` (defaults to `openai`)
- `model` (string): model identifier for selected provider
- `temperature` (number, optional): sampling temperature
- `max_tokens` (integer, optional): output token cap

### Permissions and Routing

- `permissions` (list[string]): allowed command names this agent may execute
- `allowed_agents` (list[string], optional): child agent names callable via `run_agent`

### Limits

- `limits.max_steps` (integer): max ReAct loop steps
- `limits.max_depth` (integer): max child nesting depth
- `limits.max_children` (integer): max number of child agent invocations

### Prompting

- `base_system_prompt` (string, optional): custom system prompt prefix/override

### Hooks

- `hooks` (object, optional): shell hooks executed at lifecycle points, e.g.:
  - `on_run_start`
  - `on_run_finish`
  - (and other runtime-supported hook names)

## Contracts

This project relies on explicit contracts between runtime, model output, command plugins, and child agents.

### 1) Model Output Contract

Every model turn must resolve to exactly one  object:

- Command action:

```
{"action":"command","name":"<command_name>","parameters":{}}
```

- Final answer action:

```
{"action":"final_answer","content":"plain text"}
```

Contract rules:

- Exactly one top-level  object
- `action` must be `command` or `final_answer`
- `command` requires `name` and `parameters` object
- `final_answer` requires `content`
- Invalid output triggers extraction/retry/recovery logic

### 2) Command Plugin Contract

Each module in `commands/` must export:

- `COMMAND_NAME: str`
- `DESCRIPTION: str`
- `USAGE_EXAMPLE: str`
- `execute(params: dict)` function
  - `run(params: dict)` may be used as fallback

Behavioral contract:

- Input is a -like dict (`parameters`)
- Output must be serializable/loggable
- Errors should be raised with clear messages for observation logging

### 3) Agent Config Contract

Agent YAML must be parseable and include required runtime fields for execution.

Minimum practical contract:

- identity (`role`, `description`)
- model selection (`model`, optional `provider`)
- execution policy (`permissions`)
- safety bounds (`limits.*`)

If provider is configured, matching API key must exist in environment.

### 4) Child Agent (`run_agent`) Contract

Parent-to-child invocation contract:

- Child is launched as subprocess `python agent.py ...`
- Depth is incremented and validated against `limits.max_depth`
- Child count is validated against `limits.max_children`
- Provider override behavior follows `--provider-override`
- Child execution is time-bounded (timeout enforced)

### 5) Logging Contract

Runtime writes structured L logs (default under `logs/`):

- Session start/end records
- Per-step action + parameters + result/error
- Token usage summary at end

If verbose logging is enabled, console-style traces may also be mirrored to `--verbose-log-path`.

### 6) Startup Observation Contract

`--startup-observe` may be provided multiple times.

For each command:

- Shell command is executed before normal loop
- Captured output is injected as an Observation
- Observation becomes part of model-visible context

## Runtime Flow

1. Load selected agent YAML.
2. Validate provider and required API key.
3. Build strict system prompt with allowed commands/agents.
4. Optionally run startup observation commands.
5. Execute ReAct loop until:
   - `final_answer`, or
   - max steps reached, or
   - unrecoverable parse failure.
6. Persist session and step logs.

## Security and Safety Notes

- Non-permitted commands are blocked at execution time.
- Strict action schema reduces malformed tool calls.
- Destructive shell behavior is discouraged by system prompt policy.
- Child-agent depth/count/time limits reduce runaway orchestration.

## Development

Run tests (if present):

```bash
pytest -q
```

Lint/format according to your local tooling preferences.
