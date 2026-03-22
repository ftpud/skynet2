# Project Map

## Core
- `agent.py`: main orchestrator.
- `agents/*.yaml`: agent role configs.
- `commands/*.py`: executable command handlers.

## UI
- `tui/tui3.py`: terminal UI.

## Tests
- `tests/test_extract_json.py`: JSON extraction test.

## Runtime/Generated
- `logs/*.jsonl`: run logs.
- `error.log`: error output.
- `__pycache__/`, `*/__pycache__/`: bytecode cache.

## Repo
- `.gitignore`: ignore rules.
- `.git/*`: git internals (ignore for navigation).

## AI Navigation Hint
Focus order: `agent.py` -> `agents/` -> `commands/` -> `tui/` -> `tests/`.
Ignore: `.git/`, `logs/`, `__pycache__/`, `*.pyc`, `error.log`.