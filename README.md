# skynet2

A lightweight, production-oriented ReAct agent runtime.  Give it a task in plain text — it plans, acts, observes, and delivers results autonomously.  No agent framework boilerplate, no heavyweight SDK: just a tight loop, a plugin system, and YAML-configured agent personalities.

---

## Requirements

- Python 3.10+
- `pip install openai pyyaml anthropic`
- `OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY` in your environment

---

## Quick start

```bash
# Simple one-shot task
python agent.py --agent code --prompt "Add input validation to register_user() in api/users.py"

# Interactive session — keep responding until you close it
python agent.py --agent console --prompt "Show git status" --keep-session-open

# Watch reasoning in real time
python agent.py --agent code --prompt "Fix the failing test in tests/test_auth.py" --verbose

# Multi-agent agency pipeline (plan → code → review)
python agent.py --agent agency --prompt "Implement JWT refresh token rotation"

# Swarm meeting — three agents collaborate in a shared room
python swarm.py --topic "Design a rate-limiting layer for the REST API"
```

---

## Execution modes

### 1. Single agent — `agent.py`
One agent, one task, one answer.

```bash
python agent.py --agent <name> --prompt "<task>"
```

| Flag | Purpose |
|---|---|
| `--agent` | Agent config name (maps to `agents/<name>.yaml`) |
| `--prompt` | Task description |
| `--model` | Override model from config |
| `--provider` | `openai` or `claude` |
| `--provider-override` | Force provider for this agent AND all children it spawns |
| `--keep-session-open` | After the answer, wait for follow-up input on stdin |
| `--startup-observe CMD` | Run CMD at startup and inject output as initial context (repeatable) |
| `--verbose` / `-v` | Stream model output and step details to stderr |
| `--verbose-log` | Write verbose output to a shared log file |
| `--process-all-json-blocks` | Execute every batched action in a multi-action response |

### 2. Agency pipeline — `agents/agency.yaml`
Orchestrator that delegates to planner, coder, researcher, and reviewer via persistent sessions.

```bash
python agent.py --agent agency --prompt "Migrate the user module from SQLite to PostgreSQL"
```

### 3. Swarm meeting — `swarm.py`
Multiple agents share a room and build on each other's contributions.

```bash
python swarm.py --topic "Evaluate three approaches to background job processing"
python swarm.py --config agents/swarm.yaml --topic "Review the auth architecture" --verbose
python swarm.py --summary --room-file rooms/evaluate_three_approaches_20260324.jsonl
```

### 4. Persistent daemon — `agent_daemon/agent_daemon.py`
Keeps an agent alive as a background process, reading tasks from a named pipe.

```bash
cd agent_daemon
python agent_daemon.py --agent code --agent-dir ../

# From any terminal, cron, webhook handler, or script:
echo "run the nightly test suite" > /tmp/skynet2_code.fifo
```

---

## Built-in agents

| Agent | Model | Purpose |
|---|---|---|
| `code` | gpt-5.3-codex | Direct coding tasks — minimal reads, precise edits |
| `gcode` | gpt-5.3-codex | Like `code` but auto-branches in git and prompts to merge/drop |
| `pcode` | gpt-5.4 | Coding with persistent child sessions for large multi-file work |
| `sonnet` | claude-sonnet-4-6 | Claude-backed coding agent |
| `console` | gpt-5.3-codex | Interactive shell assistant with git awareness |
| `review` | gpt-5.4-mini | Evidence-based code review |
| `plan` | gpt-5.4-mini | Step-by-step planning without execution |
| `planner` | claude-sonnet-4-6 | Claude planner that delegates to `code` agent |
| `smart_code` | gpt-5.4-mini | Orchestrates `code` + `review` in sequence |
| `agency` | gpt-5.4 | Full pipeline: planner → researcher → coder → reviewer |
| `swarm_analyst` | gpt-5.4-mini | Swarm participant — analysis and requirements |
| `swarm_coder` | gpt-5.3-codex | Swarm participant — implementation |
| `swarm_critic` | gpt-5.4-mini | Swarm participant — review and consensus |

---

## Built-in commands

Commands are the tools agents can call.  Each is a plain Python file in `commands/`.

| Command | What it does |
|---|---|
| `read_file` | Read a file; supports `start_line`, `end_line`, `max_chars` |
| `multiple_file_read` | Read several files in one call; supports `max_chars_per_file` |
| `write_file` | Write or create a file (creates parent dirs) |
| `append_to_file` | Append text to a file |
| `replace_in_file` | Exact string replacement (must match exactly once) |
| `replace_in_multiple_files` | Batch replacements across multiple files |
| `text_block_replace` | Fuzzy anchor-based block replacement with AST fallback |
| `apply_patch` | Apply a unified patch in Codex format |
| `ls` | List a directory |
| `linux_command` | Run a shell command (60s timeout, blocked patterns) |
| `multiple_linux_commands` | Run several shell commands in sequence |
| `compact_history` | Summarise and compress conversation history to save tokens |
| `run_agent` | Spawn a child agent (one-shot, wait for answer) |
| `call_agent` | Persistent child agent session — send follow-ups, preserve context |
| `ask_user` | Prompt user for input (only for agents that need it) |
| `room_read` | Read the shared swarm meeting room |
| `room_post` | Post to the shared swarm meeting room |

---

## Agent YAML reference

```yaml
# Identity
role: "Short role label used in the system prompt"
description: "Used in parent agent's allowed_agents list"
provider: openai          # openai | claude
model: gpt-5.4-mini
temperature: 0.2
max_tokens: 8192

# What this agent can do
permissions:
  - read_file
  - write_file
  - linux_command
  - run_agent             # spawn one-shot child
  - call_agent            # persistent child session
  - compact_history       # compress history mid-session
  - room_read             # swarm only
  - room_post             # swarm only

# Agents this agent is allowed to spawn (shown in its system prompt)
allowed_agents:
  - code
  - review

# Shell commands run once at startup; output injected as initial context
startup_observe:
  - cat project.md
  - git --no-pager status --short

# Shell hooks with access to AGENT_* env vars
hooks:
  on_run_start: |
    echo "Setup work here"
  on_run_finish: |
    echo "Tokens used: $AGENT_SESSION_TOKENS_IN in / $AGENT_SESSION_TOKENS_OUT out"

# Per-agent overrides for global limits
limits:
  max_steps: 30
  max_depth: 3
  max_children: 5
  max_obs_history_chars: 8000   # per-observation cap in stored history

# Injected verbatim at the start of the system prompt
base_system_prompt: |
  You are a ...
```

---

## Swarm config reference

```yaml
# agents/swarm.yaml (or any custom name passed via --config)
participants:
  - swarm_analyst
  - swarm_coder
  - swarm_critic

max_rounds: 4          # hard round cap
done_threshold: 2      # stop when this many agents post type=done
response_timeout: 300  # seconds per agent turn
```

---

## Token budget controls

| Mechanism | Where | Effect |
|---|---|---|
| `max_steps` in limits | agent yaml | Hard cap on LLM calls per run |
| `max_context_messages: 20` | agent_constants.py | Sliding history window |
| `max_obs_history_chars: 8000` | limits / constant | Truncates stored observations |
| `compact_history` command | any agent | Model-initiated mid-session summarisation |
| `startup_observe` | agent yaml | Context injected only on first step, not repeated |
| `max_chars_per_file` | `multiple_file_read` param | Per-file read cap |
| `start_line` / `end_line` | `read_file` param | Read only relevant lines |

---

## Logging

Every run writes a JSONL log to `logs/`:

```
logs/code_20260324_120000.jsonl        # step-by-step action log
logs/verbose_code_20260324_120000.log  # full streamed output (with --verbose-log)
logs/swarm_20260324_120000.log         # swarm coordinator log
rooms/topic_slug_20260324_120000.jsonl # swarm room (permanent meeting record)
```

Each step entry:
```json
{
  "type": "step",
  "step": 3,
  "action": "replace_in_file",
  "parameters": {"path": "api/users.py", "old_text": "...", "new_text": "..."},
  "result": "OK: replaced text block in api/users.py",
  "tokens": {"inbound": 4821, "outbound": 312, "total": 5133},
  "timestamp": "2026-03-24T12:00:03.412"
}
```

The TUI at `tui/tui3.py` reads these logs and shows a live token dashboard:

```bash
python tui/tui3.py
```

---

## Adding a command

```python
# commands/my_tool.py
COMMAND_NAME = "my_tool"
DESCRIPTION = "One sentence shown to the model in the system prompt."
USAGE_EXAMPLE = '{"action":"command","name":"my_tool","parameters":{"arg":"value"}}'

def execute(parameters: dict) -> str:
    # return a string — shown to the model as an Observation
    return "result"
```

Add `my_tool` to an agent's `permissions` list.  No other changes needed.

---

## Adding an agent

```bash
# 1. Create the config
cp agents/code.yaml agents/my_agent.yaml
# edit role, model, permissions, base_system_prompt

# 2. Use it
python agent.py --agent my_agent --prompt "Do something"

# 3. Make it callable by other agents
# In the parent agent yaml:
#   allowed_agents: [my_agent]
```

