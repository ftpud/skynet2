# Project Map

## Main Python Files
- `agent.py`: Main orchestrator.
- `agent_cli.py`: CLI parsing and runtime config loading.
- `agent_constants.py`: Shared execution limits.
- `agent_loaders.py`: Command and agent config discovery.
- `agent_logging.py`: L logging helpers.
- `agent_utils.py`: Prompt,  extraction, and token helpers.

## Directories
- `agents/`: Agent YAML configs.
- `commands/`: Command implementations.
- `tests/`: Test files.
- `tui/`: Terminal UI.
- `logs/`: Runtime logs.
- `__pycache__/`: Bytecode cache.

## Agent Files
- `agents/code.yaml`
- `agents/console.yaml`
- `agents/plan.yaml`
- `agents/planner.yaml`
- `agents/review.yaml`

## Commands
- `append_to_file`
- `linux_command`
- `ls`
- `multiple_file_read`
- `multiple_linux_commands`
- `read_file`
- `run_agent`
- `text_block_replace`
- `write_file`
