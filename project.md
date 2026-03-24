# Project Map

## Main Python Files
- `agent.py`: Main orchestrator.
- `agent_cli.py`: CLI parsing and runtime config loading.
- `agent_constants.py`: Shared execution limits.
- `agent_loaders.py`: Command and agent config discovery.
- `agent_logging.py`: Logging helpers.
- `agent_utils.py`: System prompt builder, JSON extraction, and token helpers.
- `swarm.py`: Multi-agent meeting room coordinator.

## Top-Level Files
- `README.md` — quick-start, CLI reference, agent/command inventory
- `PROJECT_OVERVIEW.md` — capabilities, scenarios, token economics, use cases
- `swarm.md` — swarm meeting system deep-dive
- `ARCHITECTURE.md` — runtime internals and design decisions
- `project.md` — this file (navigation map for agents)
- `.gitignore`

## Directories
- `agents/`: Agent YAML configs.
- `commands/`: Command implementations.
- `rooms/`: Swarm meeting room JSONL files (created at runtime).
- `tests/`: Test files.
- `tui/`: Terminal UI.
- `logs/`: Runtime logs.
- `agent_daemon/`: Persistent pipe-driven daemon.

## Agent Files
- `agents/agency.yaml`
- `agents/agency_coder.yaml`
- `agents/agency_planner.yaml`
- `agents/agency_researcher.yaml`
- `agents/agency_reviewer.yaml`
- `agents/code.yaml`
- `agents/console.yaml`
- `agents/gcode.yaml`
- `agents/pcode.yaml`
- `agents/plan.yaml`
- `agents/planner.yaml`
- `agents/review.yaml`
- `agents/smart_code.yaml`
- `agents/sonnet.yaml`
- `agents/swarm.yaml` ← swarm meeting config (participants, rounds, thresholds)
- `agents/swarm_analyst.yaml` ← analysis specialist swarm participant
- `agents/swarm_coder.yaml` ← implementation specialist swarm participant
- `agents/swarm_critic.yaml` ← review/quality specialist swarm participant

## Commands
- `append_to_file`
- `apply_patch`
- `ask_user`
- `call_agent`
- `compact_history`
- `linux_command`
- `ls`
- `multiple_file_read`
- `multiple_linux_commands`
- `read_file`
- `replace_in_file`
- `replace_in_multiple_files`
- `room_post` ← post to shared swarm meeting room
- `room_read` ← read shared swarm meeting room
- `run_agent`
- `text_block_replace`
- `write_file`

## Tests
- `tests/test_apply_patch.py`
- `tests/test_extract_actions.py`
- `tests/test_extract_json.py`
- `tests/test_text_block_replace.py`

## TUI
- `tui/tui3.py`
