# Project Map

## Actual Tree Structure
```text
.
├── .gitignore
├── LICENSE.md
├── PROJECT_OVERVIEW.md
├── README.md
├── agent.py
├── agent_cli.py
├── agent_constants.py
├── agent_daemon/
│   ├── agent_daemon.py
│   ├── logs/
│   └── requirements.txt
├── agent_loaders.py
├── agent_logging.py
├── agent_utils.py
├── agents/
│   ├── agency.yaml
│   ├── agency_coder.yaml
│   ├── agency_planner.yaml
│   ├── agency_researcher.yaml
│   ├── agency_reviewer.yaml
│   ├── anime_chaos_critic.yaml
│   ├── anime_critic.yaml
│   ├── anime_reviewer.yaml
│   ├── anime_swarm.yaml
│   ├── code.yaml
│   ├── console.yaml
│   ├── gcode.yaml
│   ├── pcode.yaml
│   ├── plan.yaml
│   ├── planner.yaml
│   ├── review.yaml
│   ├── smart_code.yaml
│   ├── sonnet.yaml
│   ├── swarm.yaml
│   ├── swarm_analyst.yaml
│   ├── swarm_coder.yaml
│   ├── swarm_critic.yaml
│   └── test.yaml
├── commands/
│   ├── append_to_file.py
│   ├── apply_patch.py
│   ├── ask_user.py
│   ├── call_agent.py
│   ├── compact_history.py
│   ├── linux_command.py
│   ├── ls.py
│   ├── multiple_file_read.py
│   ├── multiple_linux_commands.py
│   ├── read_file.py
│   ├── replace_in_file.py
│   ├── replace_in_multiple_files.py
│   ├── room_post.py
│   ├── room_read.py
│   ├── run_agent.py
│   ├── text_block_replace.py
│   └── write_file.py
├── project.md
├── rooms/
│   └── *.jsonl
├── swarm.md
├── swarm.py
├── tests/
│   ├── test_apply_patch.py
│   ├── test_extract_actions.py
│   ├── test_extract_json.py
│   └── test_text_block_replace.py
├── token_usage.md
└── tui/
    └── tui3.py
```

## Notes
- Omitted runtime/cache-only directories from the tree: `.git/`, `__pycache__/`, `.pytest_cache/`, top-level `logs/`, and nested `__pycache__/` folders.
- `rooms/` contains many runtime-generated JSONL meeting transcripts, so it is summarized as `*.jsonl`.
- `agent_daemon/logs/` exists as a runtime log directory.
