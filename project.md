# Project Map

## Core
- `agent.py`: main orchestrator.
- `agent_cli.py`: CLI parsing and runtime config loading.
- `agent_constants.py`: shared execution limits.
- `agent_loaders.py`: command and agent config discovery.
- `agent_logging.py`: JSONL logging helpers.
- `agent_utils.py`: prompt, JSON extraction, and token helpers.

## Agents
- `agents/code.yaml`: coding-focused agent config.
- `agents/console.yaml`: console-oriented agent config.
- `agents/gcode.yaml`: agent config.
- `agents/pcode.yaml`: agent config.
- `agents/plan.yaml`: planning agent config.
- `agents/planner.yaml`: planner agent config.
- `agents/review.yaml`: review agent config.
- `agents/smart_code.yaml`: smart coding agent config.
- `agents/sonnet.yaml`: sonnet agent config.

## Commands
- `commands/append_to_file.py`: append text to a file.
- `commands/ask_user.py`: prompt the user for input.
- `commands/linux_command.py`: run a single Linux shell command.
- `commands/ls.py`: list files and directories.
- `commands/multiple_file_read.py`: read multiple text files in sequence.
- `commands/multiple_linux_commands.py`: run multiple Linux shell commands.
- `commands/read_file.py`: read a text file.
- `commands/replace_in_file.py`: replace text within one file.
- `commands/replace_in_multiple_files.py`: replace text across multiple files.
- `commands/run_agent.py`: invoke another configured agent.
- `commands/text_block_replace.py`: replace anchored text blocks in a file.
- `commands/write_file.py`: write text to a file.

## UI
- `tui/tui3.py`: terminal UI.

## Tests
- `tests/test_extract_json.py`: JSON extraction test.
- `tests/test_text_block_replace.py`: text block replacement test.

## Runtime/Generated
- `logs/*.jsonl`: run logs.
- `error.log`: error output.
- `__pycache__/`, `*/__pycache__/`: bytecode cache.

## Repo
- `.gitignore`: ignore rules.
- `.git/*`: git internals (ignore for navigation).
- `project.md`: repository map and navigation guide.
- `test.md`: markdown file in repo root.
- `test_backup.md`: backup markdown file in repo root.

## AI Navigation Hint
Focus order: `agent.py` -> `agents/` -> `commands/` -> `tui/` -> `tests/`.
Ignore: `.git/`, `logs/`, `__pycache__/`, `*.pyc`, `error.log`.
