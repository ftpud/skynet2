# Project Overview — Capabilities, Scenarios & Token Economics

> This document describes what skynet2 **can do**, how to compose its parts, and what it costs.
> For installation and CLI flags see [README.md](README.md).
> For the swarm system specifically see [swarm.md](swarm.md).

---

## The core idea

skynet2 is a **ReAct loop runtime** plus a plugin system.  Every agent follows the same protocol:

```
Observe (startup context + history)
  → Think (LLM call, JSON output)
    → Act (execute one command, append observation)
      → loop until final_answer
```

The interesting part is the **composition layer** on top of that loop: agents can spawn other agents, run them in persistent sessions, pool context in a shared room, or be driven from the outside through a named pipe.  Every capability is just a different wiring of the same primitives.

---

## Capability map

```
┌─────────────────────────────────────────────────────────────────┐
│  EXECUTION MODES                                                │
│                                                                 │
│  One-shot          Interactive        Persistent daemon         │
│  agent.py          --keep-session     agent_daemon.py           │
│  └─ 1 task         └─ many tasks      └─ FIFO queue, 24/7       │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  ORCHESTRATION PATTERNS                                         │
│                                                                 │
│  Single agent      Hierarchical       Swarm                     │
│  code / console    agency pipeline    swarm.py                  │
│  └─ direct work    └─ plan→code→review └─ shared room          │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  TOOL SURFACE                                                   │
│                                                                 │
│  File I/O          Shell              Agent spawning            │
│  read/write/patch  linux_command      run_agent / call_agent    │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  COST CONTROLS                                                  │
│                                                                 │
│  Obs compression   Action compaction  compact_history           │
│  Write→1-line sum  Write→[N chars]    Model-initiated trim      │
│  Head+tail reads   Env context once   Session reset (auto)      │
│  Line-range reads  Per-file limits    Sliding 20-msg window     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Execution modes in depth

### One-shot
The default.  Run a task, get an answer, exit.  Clean, auditable, scriptable.

```bash
python agent.py --agent code --prompt "Rename UserService to AccountService across the codebase"
```

Suitable for: CI steps, git hooks, Makefile targets, anything you'd put in a shell script.

---

### Interactive session (`--keep-session-open`)
The agent answers, then waits for your next message.  Between tasks, history
is automatically cleaned up according to `session_reset_mode` (default:
`summary` — keeps a one-line recap of the last answer, drops everything else).

```bash
python agent.py --agent console --prompt "Start here" --keep-session-open
```

The agent remembers a brief summary of what it did in prior turns, but the
full step-by-step history is dropped to prevent input token snowballing.
Configure in the agent YAML:

```yaml
session_reset_mode: summary   # default — brief recap between tasks
# session_reset_mode: reset   # nuke all history, zero continuity
# session_reset_mode: keep    # old behaviour — full history preserved (expensive)
```

Effective for:
- Iterative debugging ("that's not quite right, now also handle the edge case where…")
- Exploration sessions where the next step depends on what was just found
- Pair-programming style work

---

### Persistent daemon (`agent_daemon.py`)
An agent that lives as a background process, accepting tasks from a named pipe (FIFO).

```bash
python agent_daemon.py --agent code --agent-dir ../
# Now running forever, reading /tmp/skynet2_code.fifo
```

External tasks arrive as plain text lines:
```bash
echo "run the test suite and fix any failures"   > /tmp/skynet2_code.fifo
echo "update CHANGELOG.md for today's commits"   > /tmp/skynet2_code.fifo
```

Messages are **queued** — if the agent is busy with task 1, task 2 waits.  Between tasks, history is automatically cleaned up according to `session_reset_mode` (default: `summary` — keeps a brief recap, drops the rest).  Set `session_reset_mode: keep` in the agent YAML if you want full history continuity across tasks.

Integrates with anything that can write to a file path:
- cron
- GitHub Actions / CI webhooks
- monitoring systems (alert → write task to FIFO)
- other scripts

---

## Orchestration patterns in depth

### Single agent — direct execution
For clear, bounded tasks.  The agent reads what it needs, makes changes, verifies, and stops.

```
User prompt
  └─ agent reads relevant files (targeted, not whole repo)
       └─ agent makes changes
            └─ agent verifies (runs tests, lints, etc.)
                 └─ final_answer
```

Best agents: `code`, `gcode`, `pcode`, `sonnet`, `console`

---

### Hierarchical agency — `agency`
For complex tasks that benefit from separation of concerns.  A persistent orchestrator coordinates specialists via `call_agent` (stateful sessions — context survives across calls).

```
agency (orchestrator)
  ├─ call_agent → agency_planner   "analyse the request and produce a plan"
  │   └─ returns: ordered plan with acceptance criteria
  ├─ call_agent → agency_researcher  "find where the auth logic lives"
  │   └─ returns: file map, existing patterns, constraints
  ├─ call_agent → agency_coder  "implement step 1 of the plan"
  │   └─ returns: changes made
  ├─ call_agent → agency_reviewer  "validate the changes"
  │   └─ returns: PASS or list of issues
  ├─ call_agent → agency_coder  "fix the issues reviewer found"  (same session)
  └─ final_answer
```

The `call_agent` command creates a **persistent subprocess**.  Subsequent calls to the same `session_id` send follow-up messages to the same agent process — context accumulates.  This means the coder can remember "I already read auth.py, it has a guard on line 45" across multiple delegation steps.

---

### Swarm — shared-room collaboration
For tasks where multiple independent perspectives improve the result.  No central controller: every participant reads the same room and decides what to contribute.

```
Round 0: facilitator posts topic
Round 1:
  analyst reads room → posts analysis of the problem space
  coder   reads room → posts a proposal based on analyst's findings
  critic  reads room → posts review of both, flags an edge case
Round 2:
  analyst reads updated room → posts clarification on the edge case
  coder   reads updated room → posts revised implementation
  critic  reads updated room → posts LGTM + posts type=done
  ... another agent posts done → threshold reached → meeting ends
```

Room is an append-only JSONL file.  Every post is visible to all future participants in all future rounds.

---

## Agent composition — what can call what

```
agency          call_agent → agency_planner (persistent session)
                call_agent → agency_coder   (persistent session)
                call_agent → agency_reviewer
                call_agent → agency_researcher

planner         run_agent  → code           (one-shot per plan step)

smart_code      run_agent  → code
                run_agent  → review

pcode           call_agent → pcode          (recursive — pcode calls itself)

gcode           run_agent  → gcode          (recursive — for large tasks)
```

`run_agent` = one-shot subprocess.  Parent waits, gets the output, moves on.
`call_agent` = persistent subprocess.  Parent can send follow-ups.  Context survives.

Depth limit (default 3), child count limit (default 5–12), and timeout (600s) prevent runaway recursion.

---

## Token economics

Token counts below are **realistic estimates** for the current agent configs running on a medium-complexity Python codebase (~50 files, ~5K lines).  "Input" includes system prompt + history window.  Numbers rounded to nearest thousand.

### Scenario 1 — Quick fix (1–2 files, clear task)

**Agent:** `code`  
**Example:** "Fix the off-by-one error in `pagination.py` line 47"

| Step | Input tokens | Output tokens |
|---|---|---|
| System prompt + initial context | 3 K | — |
| Read file (targeted) | +2 K | — |
| LLM call 1 (decide to edit) | 5 K | 0.3 K |
| LLM call 2 (edit + final_answer) | 6 K | 0.5 K |
| **Total** | **~11 K** | **~0.8 K** |

**Rough cost:** ~$0.03 on gpt-5.3-codex · ~$0.005 on gpt-5.4-mini

---

### Scenario 2 — Feature addition (3–6 files, moderate complexity)

**Agent:** `code`  
**Example:** "Add request rate limiting middleware to the Flask app"

| Step | Input tokens | Output tokens |
|---|---|---|
| System prompt + startup observe | 4 K | — |
| 3× read_file (middleware, routes, config) | +8 K | — |
| 4× LLM calls (plan, implement, verify, answer) | 45 K cumulative | 3 K |
| **Total** | **~45 K** | **~3 K** |

**Rough cost:** ~$0.18 on gpt-5.3-codex · ~$0.04 on gpt-5.4-mini

---

### Scenario 3 — Multi-file refactor

**Agent:** `smart_code` (orchestrates `code` + `review`)  
**Example:** "Rename `UserService` to `AccountService` across the codebase"

| Agent | Input tokens | Output tokens |
|---|---|---|
| smart_code orchestrator | 8 K | 1 K |
| code (reads 8 files, makes 6 edits) | 60 K | 8 K |
| review (reads changed files) | 20 K | 2 K |
| **Total** | **~88 K** | **~11 K** |

**Rough cost:** ~$0.55 on gpt-5.3-codex + gpt-5.4-mini mix

---

### Scenario 4 — Agency pipeline (complex feature)

**Agent:** `agency`  
**Example:** "Implement JWT refresh token rotation with Redis token store"

| Agent | Calls | Input tokens | Output tokens |
|---|---|---|---|
| agency orchestrator | 10 steps | 40 K | 5 K |
| agency_planner | 1 session | 25 K | 8 K |
| agency_researcher | 1 session | 20 K | 4 K |
| agency_coder | 5 delegations | 120 K | 20 K |
| agency_reviewer | 2 reviews | 30 K | 4 K |
| **Total** | | **~235 K** | **~41 K** |

**Rough cost:** ~$1.50–$3.00 depending on model mix (gpt-5.4 orchestrator, gpt-5.3-codex coder)

---

### Scenario 5 — Swarm design meeting

**Config:** 3 agents × 3 rounds  
**Example:** `swarm.py --topic "Design the caching architecture"`

| Agent | Rounds | Input/turn | Output/turn | Total |
|---|---|---|---|---|
| swarm_analyst | 3 | 15 K → 35 K (grows) | 2 K | ~75 K |
| swarm_coder | 3 | 20 K → 50 K (grows) | 5 K | ~120 K |
| swarm_critic | 3 | 20 K → 50 K (grows) | 2 K | ~90 K |
| **Total** | | | | **~285 K** |

Room grows each round because every agent reads the full history.  Most expensive orchestration mode per token.

**Rough cost:** ~$0.25–$0.80 on gpt-5.4-mini · ~$2.00–$4.00 if coder runs on gpt-5.3-codex

> **Tip:** Set `max_rounds: 2` and `done_threshold: 1` for a cheaper focused swarm.  
> Total drops to ~90 K tokens.

---

### Scenario 6 — Overnight daemon (10 cron tasks)

**Setup:** `agent_daemon.py` with `code` agent, 10 tasks delivered overnight via cron  
**Each task:** average 30 K tokens (moderate changes)  
**Session reset mode:** `summary` (default)

| | Tokens |
|---|---|
| Session warm-up (initial prompt) | 5 K |
| 10 tasks × 30 K each | 300 K |
| Inter-task overhead (recap message only) | ~0.5 K |
| **Total overnight** | **~305 K** |

With `session_reset_mode: summary` (default), each task starts nearly clean —
just a ~100-char recap of the last answer.  This prevents the old snowball
problem where later tasks paid for the full history of all prior tasks.

**Old behaviour** (`session_reset_mode: keep`):
History carries forward (+15% per task), total would be ~350 K.

**Rough cost:** ~$1.20–$2.00 on gpt-5.3-codex

---

### Scenario 7 — Interactive refactoring session

**Mode:** `--keep-session-open`, `session_reset_mode: summary`, 8 follow-up messages  
**Agent:** `pcode`

Each follow-up task starts nearly clean (recap of the last answer only).
Within a single task, observation compression and action compaction keep
the context tight:

| Turn | What happens | LLM call input |
|---|---|---|
| Turn 1 (task 1) | Initial prompt + reads | 20 K |
| Turn 1, step 3 | Write (action compacted, obs summarised) | 22 K |
| Turn 1, step 5 | Final answer → session reset | — |
| Turn 2 (task 2) | Recap (100 chars) + new prompt | 5 K |
| Turn 2, step 3 | Reads + edits | 12 K |
| Turn 2, step 4 | Final answer → session reset | — |
| … | … | … |
| **Total across 8 tasks** | | **~120 K input, ~12 K output** |

**Old behaviour** (`session_reset_mode: keep`, no action compaction):
Would accumulate ~35 K by turn 4, require `compact_history` at turn 5,
and total ~180 K input + ~15 K output across 8 turns — **50% more expensive**.

---

## Cost control strategies

> For the full technical breakdown of how context windows are built and
> trimmed, see **[token_usage.md](token_usage.md)**.

### Automatic (no config needed)
These optimisations are always active:

| Optimisation | Savings |
|---|---|
| **Write-command observation → 1-line summary** | ~2–50k per write step |
| **Assistant action payload compaction** | ~2–50k per write step |
| **Head+tail observation compression** (reads > 8k) | ~50% of large observations |
| **Environment block sent once** (first call only) | System prompt size on steps 2+ |
| **Startup observe output capped to 8k** | Prevents 300k in system prompt |
| **History pressure hints** | Triggers `compact_history` when needed |
| **Session reset between tasks** (`summary` mode default) | ~95% of prior task history |

### 1. Right-size the agent
| Task | Recommended agent | Why |
|---|---|---|
| Simple file edit | `code` | Direct, no orchestration overhead |
| Multi-file refactor | `smart_code` or `gcode` | Adds review without full agency cost |
| Complex feature | `agency` | Planning avoids costly wrong-direction coding |
| Architecture discussion | `swarm` (2 rounds) | Parallel perspectives, bounded cost |
| Overnight automation | daemon + `code` | Persistent session amortises context setup |

### 2. Use line-range reads
```json
{"action":"command","name":"read_file","parameters":{"path":"big.py","start_line":40,"end_line":80}}
```
Reading 40 lines instead of 400 cuts per-step cost by 10×.

### 3. Set `max_obs_history_chars` per agent
```yaml
limits:
  max_obs_history_chars: 4000  # trim stored observations aggressively
```
Large shell output (test runs, grep results) is trimmed before entering history.

### 4. Use `compact_history` on long sessions
Prompt the agent (or let it self-trigger from the hint) to compress old messages:
```json
{"action":"command","name":"compact_history","parameters":{
  "summary":"Read auth.py (guards on L45), fixed token expiry in refresh_token(), tests passing.",
  "keep_recent": 4
}}
```

### 5. Cap swarm rounds
```yaml
# agents/swarm.yaml
max_rounds: 2
done_threshold: 1
```

### 6. Use cheaper models for read-heavy agents
```yaml
# agency_researcher.yaml — it reads and summarises, no coding
provider: openai
model: gpt-5.4-mini   # cheaper for reasoning-light summarisation
```

---

## Use cases and scenarios

### Automated code maintenance
**Setup:** daemon + cron  
**Flow:**
```
0 2 * * *  echo "run tests and fix any failures"        > /tmp/skynet2_code.fifo
0 3 * * *  echo "update dependencies in requirements.txt" > /tmp/skynet2_code.fifo
0 4 * * 1  echo "generate CHANGELOG for this week"      > /tmp/skynet2_code.fifo
```
The daemon processes tasks overnight.  Because the session persists, the agent that fixed tests at 2AM already has the repo map in memory when it updates deps at 3AM.

---

### PR-gated review pipeline
**Setup:** CI webhook → write to FIFO  
**Flow:**
```
GitHub webhook (PR opened)
  └─ writes "review PR diff: $(git diff main...HEAD)" to FIFO
       └─ daemon runs review agent
            └─ posts review comment via linux_command (gh pr review ...)
```

---

### Architecture design session
**Setup:** `swarm.py` with analyst + coder + critic  
**Flow:**
```
swarm.py --topic "We need to replace our monolithic background job runner
                  with something that scales horizontally.
                  Evaluate celery vs rq vs temporal, recommend one."
```
Each agent reads the room, researches from the codebase, posts structured findings.  The critic forces a decision.  Room is the permanent record.

---

### Iterative feature development
**Setup:** `pcode` agent with `--keep-session-open`  
**Flow:**
```
You> Implement the user preferences API endpoint
  → agent plans, reads files, writes code, runs tests

You> Also add pagination to the list endpoint
  → agent already knows the codebase from turn 1

You> The tests are failing on Python 3.10, fix it
  → agent applies fix without re-reading everything
```

---

### Autonomous refactoring
**Setup:** `gcode` (auto-branches) + large task  
**Flow:**
```bash
python agent.py --agent gcode --prompt "
  Refactor the entire authentication module to use the new TokenStore
  abstraction introduced in PR #142.  Update all call sites.
  Run tests after each file change.
"
```
`gcode` creates a branch automatically (`gcode/20260324_120000`), makes all changes, then pauses and shows a diff.  The on_run_finish hook asks: `[(A)ccept/(d)iff/(x)drop/(e)xit]`.  You inspect, decide, and it merges or drops.

---

### Cross-language migration
**Setup:** `agency` pipeline  
**Prompt:**
```
Migrate the data access layer from raw SQL (sqlite3) to SQLAlchemy ORM.
Keep the existing test suite passing.  Do not change the public API.
```
Agency:
1. Planner produces a migration plan (models, queries, session management, tests)
2. Researcher maps existing SQL strings and their callers
3. Coder implements model by model in persistent session
4. Reviewer validates each batch before coder continues
5. Final answer: what changed, what to watch

---

### Security audit
**Setup:** `agency` with researcher + reviewer  
**Prompt:**
```
Audit the authentication and authorisation subsystem for common vulnerabilities:
SQL injection, privilege escalation, token fixation, timing attacks.
Produce a prioritised finding report.
```
Researcher traces code paths.  Reviewer assesses severity.  No code changes — read-only permissions.

---

### Living documentation
**Setup:** daemon + daily cron  
**Cron:**
```
0 9 * * *  echo "update project.md to reflect today's git log" > /tmp/skynet2_console.fifo
```
Agent reads `git log --since yesterday`, updates `project.md` and any relevant docs.

---

## Extending the system

### New command in 5 minutes
```python
# commands/grep_codebase.py
import subprocess
COMMAND_NAME = "grep_codebase"
DESCRIPTION = "Search for a pattern in the codebase. Returns matching lines with filenames."
USAGE_EXAMPLE = '{"action":"command","name":"grep_codebase","parameters":{"pattern":"TODO","path":"."}}'

def execute(parameters: dict) -> str:
    pattern = parameters.get("pattern", "")
    path = parameters.get("path", ".")
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", pattern, path],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout[:8000] or "(no matches)"
```
Add `grep_codebase` to an agent's permissions.  Done.

---

### New agent in 2 minutes
```yaml
# agents/security_auditor.yaml
role: "Security auditor"
description: "Reviews code for security vulnerabilities and produces a prioritised findings report."
provider: openai
model: gpt-5.4-mini
temperature: 0.0
max_tokens: 8192

permissions:
  - read_file
  - multiple_file_read
  - ls
  - linux_command

base_system_prompt: |
  You are a security auditor. Your output is always a prioritised findings report.
  Focus on: injection flaws, authentication issues, insecure data handling, privilege escalation.
  Reference specific files and line numbers. Never make code changes.
  Do NOT ask for clarification — audit what is present.

limits:
  max_steps: 20
  max_depth: 1
  max_children: 0
```

---

### New swarm participant
1. Create the YAML above with `room_read` and `room_post` in permissions
2. Add the agent name to `participants` in `agents/swarm.yaml`
3. Run `swarm.py` — no other changes

---

## Observability

### TUI token dashboard
```bash
python tui/tui3.py
```
Live view of: tokens per model per minute, session summaries, sparklines.

### Log replay
Every session produces a JSONL step log.  Parse it to answer: what did the agent read? what did it change? how many tokens per step?

```bash
# Token usage per session
jq 'select(.type=="session_end") | {agent, tokens}' logs/*.jsonl

# What files were read
jq 'select(.action=="read_file") | .parameters.path' logs/code_*.jsonl | sort -u

# Steps that cost the most
jq 'select(.type=="step") | {step, action, tokens: .tokens.total}' logs/*.jsonl | sort -t: -k2 -rn
```

### Room replay
```bash
python swarm.py --summary --room-file rooms/my-meeting.jsonl
```

---

## Limits reference

| Constant | Default | Override |
|---|---|---|
| `MAX_STEPS` | 30 | `limits.max_steps` in agent yaml |
| `MAX_CONTEXT_MESSAGES` | 20 | hardcoded (edit `agent_constants.py`) |
| `MAX_OBS_HISTORY_CHARS` | 8 000 | `limits.max_obs_history_chars` in agent yaml |
| `OBSERVATION_FILE_PREVIEW_CHARS` | 1 200 | `limits.observable_file_preview_chars` |
| `OBSERVATION_GENERIC_PREVIEW_CHARS` | 4 000 | `limits.observable_generic_preview_chars` |
| `OBSERVATION_COMPACT_PREVIEW_CHARS` | 2 000 | `limits.observable_compact_preview_chars` |
| `MAX_OUTPUT_CHARS` | 300 000 | hardcoded |
| `MAX_AGENT_DEPTH` | 3 | `limits.max_depth` in agent yaml |
| `MAX_CHILD_AGENTS` | 5 | `limits.max_children` in agent yaml |
| `CHILD_AGENT_TIMEOUT` | 600 s | hardcoded |
| `MAX_RETRIES_PER_STEP` | 3 | hardcoded |
| `session_reset_mode` | `summary` | `session_reset_mode` in agent yaml |

---

## Current agent inventory at a glance

```
Single-shot coding
  code          → direct edits, minimal reads, fast
  gcode         → like code + git branch + merge prompt
  pcode         → like code + persistent child sessions + hook-injected file context
  sonnet        → code but Claude Sonnet backend
  console       → shell tasks, git-aware, interactive-friendly

Planning & review
  plan          → read-only planning, no execution
  planner       → Claude planner that spawns code children
  review        → read-only code review, evidence-based
  smart_code    → code + review in sequence, validation loop

Multi-agent pipelines
  agency        → full pipeline: planner+researcher+coder+reviewer
  agency_planner     → requirements extraction + execution plan
  agency_coder       → implementation specialist (in agency context)
  agency_reviewer    → validation specialist (in agency context)
  agency_researcher  → codebase investigation specialist

Swarm (collaborative room)
  swarm_analyst → analysis and requirements
  swarm_coder   → proposals and implementation
  swarm_critic  → review, risks, consensus driving
```

