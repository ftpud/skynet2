# Lightweight ReAct JSON Agent

A production-oriented, local, multi-agent CLI framework that runs OpenAI models in a strict JSON action loop.

This project provides:
- A **core agent runtime** (`agent.py`) with bounded execution and logging
- A **pluggable command system** (`commands/*.py`)
- **Role-based agent configs** (`agents/*.yaml`)
- Optional **hierarchical delegation** via `run_agent`
- A **TUI dashboard** (`tui/app.py`) for token-usage visibility from logs

---

## Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Repository Layout](#repository-layout)
- [How It Works](#how-it-works)
- [Agent Configuration](#agent-configuration)
- [Commands](#commands)
- [Running the Project](#running-the-project)
- [Logging and Observability](#logging-and-observability)
- [TUI Dashboard](#tui-dashboard)
- [Known Issues / Gaps](#known-issues--gaps)
- [Security Notes](#security-notes)
- [Extending the System](#extending-the-system)
- [Troubleshooting](#troubleshooting)
- [Quick Start](#quick-start)

---

## Overview

This repository implements a lightweight ReAct-style agent loop where the model must return exactly one JSON object per step:

- `{"action":"command", ...}` to execute a tool
- `{"action":"final_answer", ...}` to terminate

The runtime enforces:
- Step limits
- Retry limits for malformed JSON
- Context window trimming
- Child-agent depth and count limits
- Basic loop detection

The design is intentionally simple and file-based, making it easy to inspect, modify, and run locally.

---

## Architecture

### 1) Core runtime (`agent.py`)

`agent.py` is the orchestrator. It:
- Loads an agent YAML config (`agents/<name>.yaml`)
- Dynamically loads command modules from `commands/`
- Builds a strict system prompt listing allowed commands and child agents
- Calls OpenAI Responses API in streaming mode
- Parses model output into JSON
- Executes commands and feeds observations back into the loop
- Writes structured JSONL logs to `logs/`

### 2) Command plugins (`commands/*.py`)

Each command module exports:
- `COMMAND_NAME`
- `DESCRIPTION`
- `USAGE_EXAMPLE`
- `execute(parameters: dict) -> str`

Commands are auto-discovered at runtime.

### 3) Agent roles (`agents/*.yaml`)

Each role defines:
- model
- temperature / max tokens
- allowed command permissions
- allowed child agents
- optional limits
- role/base prompt text

### 4) Optional delegation (`run_agent`)

The runtime has built-in child-agent spawning logic (`Agent._run_agent`) with depth/child limits and timeout.

---

## Repository Layout

- `agent.py` — main runtime and CLI entrypoint
- `agents/`
  - `main.yaml` — orchestrator profile
  - `code.yaml` — coding specialist profile
  - `plan.yaml` — planning specialist profile
  - `research.yaml` — research specialist profile
  - `review.yaml` — review specialist profile
- `commands/`
  - `read_file.py`, `write_file.py`, `append_to_file.py`
  - `replace_in_file.py`, `text_block_replace.py`
  - `ls.py`, `linux_command.py`, `run_agent.py`
- `tui/app.py` — live token usage dashboard from logs
- `ai_config.json` — additional metadata/config hints
- `logs/` — JSONL session and step logs

---

## How It Works

1. Start agent with CLI args (`--agent`, `--prompt`)
2. Runtime loads YAML config and validates model/API key
3. Runtime builds system prompt with:
   - strict JSON output contract
   - allowed commands
   - allowed child agents
4. Runtime enters step loop (bounded by `max_steps`)
5. Model returns JSON action
6. Runtime executes command or returns final answer
7. Observation is appended to conversation history
8. Session ends on `final_answer`, loop detection, parse failure, or max steps

### Guardrails implemented
- `MAX_STEPS` default: 30
- `MAX_RETRIES_PER_STEP` default: 3
- `MAX_CONTEXT_MESSAGES` default: 20
- `MAX_AGENT_DEPTH` default: 3
- `MAX_CHILD_AGENTS` default: 5
- `CHILD_AGENT_TIMEOUT` default: 60s

---

## Agent Configuration

Agent YAML fields used by runtime:
- `role`
- `model`
- `temperature`
- `max_tokens`
- `permissions` (allowed commands)
- `allowed_agents` (for `run_agent`)
- `base_system_prompt`
- `limits` (`max_steps`, `max_depth`, `max_children`)

Example (`agents/code.yaml`):
- Role: Coding specialist
- Model: `gpt-5.3-codex`
- Broad file/shell permissions + `run_agent`
- Allowed child agents: `plan`, `review`

---

## Commands

Implemented commands:
- `read_file` — read UTF-8 text file
- `write_file` — write UTF-8 text file (creates parent dirs)
- `append_to_file` — append text
- `replace_in_file` — unique block replacement
- `text_block_replace` — same behavior as above
- `ls` — list directory entries
- `linux_command` — run shell command with basic blocked patterns
- `run_agent` — intended child-agent launcher command module

Note: runtime intercepts `run_agent` and uses internal `_run_agent`; command module still exists but is not used when invoked through runtime dispatch.

---

## Running the Project

## Prerequisites
- Python 3.11+
- `OPENAI_API_KEY` set in environment
- Dependencies:
  - `openai`
  - `pyyaml`
  - `rich` (for TUI)

Install example:

```bash
pip install openai pyyaml rich
```

Set API key:

```bash
export OPENAI_API_KEY="your_key_here"
```

Run an agent:

```bash
python agent.py --agent main --prompt "Summarize this repository"
```

Verbose mode:

```bash
python agent.py --agent code --prompt "Inspect project and propose fixes" --verbose
```

Override model:

```bash
python agent.py --agent review --model gpt-5.4-mini --prompt "Review architecture"
```

---

## Logging and Observability

Logs are written to `logs/<agent>_<timestamp>.jsonl`.

Record types:
- `session_start`
- `step`
- `session_end`

`session_end` includes token totals:
- inbound
- outbound
- total

Step logs include action name, parameters, and truncated result preview.

---

## TUI Dashboard

`tui/app.py` reads JSONL logs and aggregates token usage by:
- model per hour
- agent per hour

Window defaults:
- last 12 hours
- refresh every 2 seconds

Run:

```bash
python tui/app.py
```

---

## Known Issues / Gaps

1. **`tui/app.py` appears incomplete**
   - File ends at `if __name__ == "__main__":` without calling `main()`.
   - Expected fix: add `main()` under that guard.

2. **`commands/run_agent.py` has typos and likely dead path**
   - Uses `ahent.py` / `ahent_path` instead of `agent.py`.
   - Runtime currently handles `run_agent` internally, so this module is effectively bypassed in normal flow.

3. **Duplicate replacement commands**
   - `replace_in_file` and `text_block_replace` are functionally identical.

4. **`ai_config.json` command names differ from runtime command set**
   - Mentions names like `execute_command`, `read_chain`, `list_dir`, etc., which are not present in `commands/`.
   - Treat as external metadata unless integrated intentionally.

5. **Minor prompt typo**
   - `agents/code.yaml` base prompt says `specialis` (cosmetic).

---

## Security Notes

- `linux_command` blocks only a small set of dangerous patterns.
- It still executes shell commands with `shell=True`.
- For stronger safety in production:
  - Use allowlisted commands
  - Avoid `shell=True`
  - Add path sandboxing
  - Add stricter timeout/output limits

---

## Extending the System

### Add a new command
1. Create `commands/<name>.py`
2. Export required metadata + `execute(parameters)`
3. Add command name to target agent `permissions`

### Add a new agent role
1. Create `agents/<role>.yaml`
2. Define model, permissions, limits, prompt
3. Run with `--agent <role>`

### Add child delegation
- Add child role name to parent `allowed_agents`
- Use `run_agent` action from model

---

## Troubleshooting

- **Error: config not found**
  - Ensure `agents/<name>.yaml` exists.

- **Error: OPENAI_API_KEY environment variable is required**
  - Export key before running.

- **Agent stuck / loop terminated**
  - Check prompt clarity and command permissions.

- **Could not parse valid JSON after retries**
  - Model output violated strict JSON contract; reduce temperature or tighten prompt.

- **No TUI output data**
  - Ensure logs exist and contain token usage/session records.

---

## Quick Start

```bash
export OPENAI_API_KEY="..."
pip install openai pyyaml rich
python agent.py --agent main --prompt "Research project in ./ and summarize"
python tui/app.py
```

If you want this repository to be production-hardened, start by fixing `tui/app.py` entrypoint, reconciling `ai_config.json` with actual commands, and tightening shell command safety.
