# Lightweight ReAct  Agent

A production-ready, lightweight ReAct-style agent runtime that enforces a strict  action protocol, supports hierarchical child agents, and executes a controlled set of local commands.

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

## CLI Options

From `agent_cli.py`:

- `--agent` (required): agent config name (without `.yaml`)
- `--prompt` (required): initial task prompt
- `--model`: override model from config
- `--provider`: `openai` or `claude`
- `--provider-override`: force provider for parent + child agents
- `--depth`: internal nesting depth (used by runtime)
- `--log-path`: internal explicit log path
- `--verbose-log`: duplicate verbose output to file
- `--verbose-log-path`: shared verbose log file path
- `-v, --verbose`: print detailed progress
- `--startup-observe`: repeatable shell command injected as initial Observation

## Agent Configs (`agents/*.yaml`)

Each agent YAML typically defines:

- `role`
- `description`
- `model`
- `provider` (optional, defaults to `openai`)
- `permissions` (allowed command names)
- `allowed_agents` (agents callable via `run_agent`)
- `limits`:
  - `max_steps`
  - `max_depth`
  - `max_children`
- `temperature`
- `max_tokens`
- `base_system_prompt`
- `hooks` (optional shell hooks)

## Command Plugin Interface

Each command module in `commands/` should expose:

- `COMMAND_NAME` (str)
- `DESCRIPTION` (str)
- `USAGE_EXAMPLE` (str)
- `execute(params: dict)` function (or `run(params: dict)` fallback)

Commands are auto-discovered at startup by `agent_loaders.load_commands()`.

## Runtime Behavior

1. Load selected agent YAML.
2. Validate provider + API key.
3. Build strict system prompt including allowed commands/agents.
4. Optionally run startup observation commands.
5. Iterate ReAct loop until:
   - `final_answer`, or
   - max steps reached, or
   - unrecoverable parse failure.
6. Log all steps and session summary to L.

## Logging

Logs are written under `logs/` by default.

- Session start/end entries
- Per-step action/parameters/result entries
- Token usage totals at session end

Verbose mode can also be mirrored to a shared text log with `--verbose-log`.

## Child Agents

The `run_agent` command spawns a subprocess invocation of `agent.py` with incremented depth.

Safety limits are enforced:

- Maximum nesting depth
- Maximum number of child agents
- Child timeout

## Notes

- The runtime enforces strict  action format and retries on invalid model output.
- Non-permitted commands are blocked at execution time.
- Destructive shell behavior is discouraged by system prompt safety rules.

## Development

Run tests (if present):

```bash
pytest -q
```

Lint/format according to your local tooling preferences.
