# TODO / Missing Items (derived from README.md)

Since `todo.md` was missing, this file lists unfinished requirements found in `README.md`.

## 1) Core Entrypoint & CLI
- [ ] Create `agent.py` entrypoint.
- [ ] Implement CLI arguments:
  - [ ] `--config` (required)
  - [ ] `--prompt` (required)
  - [ ] `--model` (optional override)
- [ ] Validate Python 3.11+ runtime expectations.

## 2) Dependencies & Environment
- [ ] Ensure dependency usage supports:
  - [ ] `openai >= 1.40.0`
  - [ ] `PyYAML`
  - [ ] Python standard library only otherwise
- [ ] Enforce `OPENAI_API_KEY` presence.

## 3) Configuration Handling (`config.yaml`)
- [ ] Implement YAML config loading.
- [ ] Validate required keys:
  - [ ] `role`
  - [ ] `model`
  - [ ] `temperature`
  - [ ] `max_tokens`
  - [ ] `permissions` (list)
  - [ ] `base_system_prompt`
  - [ ] `limits` with max_steps/max_depth/max_children
- [ ] Support model override from CLI.

## 4) Global Execution Limits (Mandatory)
- [ ] Enforce `MAX_STEPS = 30`.
- [ ] Enforce `MAX_RETRIES_PER_STEP = 3`.
- [ ] Enforce `MAX_OUTPUT_CHARS = 2000`.
- [ ] Enforce `MAX_CONTEXT_MESSAGES = 20`.
- [ ] Enforce `MAX_AGENT_DEPTH = 3`.
- [ ] Enforce `MAX_CHILD_AGENTS = 5`.
- [ ] Enforce `CHILD_AGENT_TIMEOUT = 60`.
- [ ] On any limit hit, terminate with `final_answer`.

## 5) Command Framework (`/commands`)
- [ ] Create `commands/` package.
- [ ] Implement required command modules:
  - [ ] `read_file`
  - [ ] `write_file`
  - [ ] `append_to_file`
  - [ ] `linux_command`
  - [ ] `run_agent`
  - [ ] `ls`
- [ ] Ensure each module defines:
  - [ ] `COMMAND_NAME`
  - [ ] `DESCRIPTION`
  - [ ] `USAGE_EXAMPLE`
  - [ ] `execute(parameters: dict) -> str`
- [ ] Ensure commands never raise; always return string.
- [ ] Return errors as `ERROR: <message>`.
- [ ] Truncate command output to `MAX_OUTPUT_CHARS`.

## 6) Dynamic Command Loading
- [ ] Discover modules under `/commands` at startup.
- [ ] Validate required command attributes/functions.
- [ ] Filter commands by config permissions.
- [ ] Safely ignore broken/invalid modules.

## 7) System Prompt Construction
- [ ] Build system prompt with:
  - [ ] Role definition
  - [ ] Allowed commands with name/description/usage
  - [ ] Strict JSON interaction contract
- [ ] Include required contract/rules text from README.

## 8) Main ReAct Loop
- [ ] Implement reason-act-observe loop.
- [ ] Send system prompt + bounded history to OpenAI (streaming enabled).
- [ ] Collect full model response.
- [ ] Extract first valid JSON object.
- [ ] Validate action schema.
- [ ] Retry malformed responses up to `MAX_RETRIES_PER_STEP` with corrective feedback.

## 9) Robust JSON Parsing
- [ ] Implement bracket-balancing JSON extraction from first `{`.
- [ ] Parse with `json.loads`.
- [ ] Recovery attempts:
  - [ ] remove trailing commas
  - [ ] convert single quotes to double quotes
- [ ] Use only the first valid JSON object.

## 10) Action Execution Rules
- [ ] If `action == "command"`:
  - [ ] Verify command is allowed
  - [ ] Execute command
  - [ ] Append `Observation: <result>` to history
- [ ] If `action == "final_answer"`:
  - [ ] Print `content`
  - [ ] Exit immediately

## 11) Loop/Repetition Detection
- [ ] Track last 3 actions.
- [ ] If identical sequence repeats, force termination with final answer.
- [ ] Detect same command+parameters repetition and terminate safely.

## 12) Context Management
- [ ] Keep bounded history: `history = history[-MAX_CONTEXT_MESSAGES:]`.
- [ ] Truncate large observations/output.

## 13) Hierarchical Child Agent Execution (`run_agent`)
- [ ] Accept params: `role`, `prompt`, `config`.
- [ ] Enforce depth and child-count limits.
- [ ] Enforce child timeout.
- [ ] Execute child via subprocess or recursive call.
- [ ] Capture child output and extract only final answer.
- [ ] Return exactly: `FINAL_ANSWER: <child result>`.

## 14) `linux_command` Safety
- [ ] Block dangerous patterns:
  - [ ] `rm -rf`
  - [ ] `shutdown`
  - [ ] `reboot`
  - [ ] `mkfs`
  - [ ] `:(){ :|:& };:`
- [ ] Enforce timeout ≤ 10s.
- [ ] Capture stdout+stderr.
- [ ] Truncate output.

## 15) Error Handling & Resilience
- [ ] Convert all failures to string responses.
- [ ] Prevent crashes in main loop and commands.
- [ ] Apply retry logic where required.

## 16) Structured Logging
- [ ] Implement JSONL logging for each step with:
  - [ ] `step`
  - [ ] `action`
  - [ ] `parameters`
  - [ ] `result`
  - [ ] `timestamp`

## 17) Requested Artifact Completed
- [x] Created `todo.md` listing missing/unimplemented items derived from `README.md`.
