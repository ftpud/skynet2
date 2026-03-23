# Project Map

## Main Python Files
- `agent.py`: Main orchestrator.
- `agent_cli.py`: CLI parsing and runtime config loading.
- `agent_constants.py`: Shared execution limits.
- `agent_loaders.py`: Command and agent config discovery.
- `agent_logging.py`: Logging helpers.
- `agent_utils.py`: Prompt extraction and token helpers.

## Top-Level Files
- `ARCHITECTUDE.md`
- `README.md`
- `project.md`
- `.gitignore`

## Directories
- `agents/`: Agent YAML configs.
- `commands/`: Command implementations.
- `tests/`: Test files.
- `tui/`: Terminal UI.
- `logs/`: Runtime logs.
- `__pycache__/`: Bytecode cache.
- `.git/`: Git metadata.

## Agent Files
- `agents/code.yaml`
- `agents/console.yaml`
- `agents/gcode.yaml`
- `agents/pcode.yaml`
- `agents/plan.yaml`
- `agents/planner.yaml`
- `agents/review.yaml`
- `agents/smart_code.yaml`
- `agents/sonnet.yaml`

## Commands
- `append_to_file`
- `ask_user`
- `linux_command`
- `ls`
- `multiple_file_read`
- `multiple_linux_commands`
- `read_file`
- `replace_in_file`
- `replace_in_multiple_files`
- `run_agent`
- `call_agent`
- `text_block_replace`
- `write_file`

## Tests
- `tests/test_extract_.py`
- `tests/test_text_block_replace.py`

## TUI
- `tui/tui3.py`
