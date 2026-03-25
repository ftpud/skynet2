# Token Usage & Context Window Management

> How skynet2 builds, trims, and optimises the context window sent to the LLM
> on every API call.  Includes step-by-step examples, truncation rules, and
> cost implications.

---

## 1. What gets sent on every LLM call

- `session_tokens_in/out` accumulate the API-reported usage from each step.
- The verbose context header shows the real total input tokens spent so far
  from API usage already returned, not a pre-call estimate for the current step.


Each step in the agent loop makes one API call.  The **input** to that call is
assembled from three layers:

```
┌──────────────────────────────────────────────────────────┐
│  SYSTEM MESSAGE                                          │
│                                                          │
│  ┌─────────────────────────────────────┐                 │
│  │ system_prompt  (role, rules,        │  always present │
│  │   command descriptions, strategy)   │  ~3–5 k chars   │
│  ├─────────────────────────────────────┤                 │
│  │ ENVIRONMENT block (first call only) │  0 or 1–8 k     │
│  │   startup_observe outputs           │  per command     │
│  │   on_run_start hook output          │                 │
│  └─────────────────────────────────────┘                 │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  HISTORY WINDOW (last 20 messages)                       │
│                                                          │
│  [user   ] initial prompt            ← always kept       │
│  [assist ] compacted action JSON     ← capped            │
│  [user   ] Observation: trimmed obs  ← capped            │
│  [assist ] compacted action JSON     ← capped            │
│  [user   ] Observation: trimmed obs  ← capped            │
│  …                                                       │
│  [user   ] Observation: trimmed obs + pressure hint      │
│                                                          │
│  Sliding window: only the last MAX_CONTEXT_MESSAGES (20) │
│  messages are included.  Older messages are silently      │
│  dropped from the API call (but kept in self.history).   │
└──────────────────────────────────────────────────────────┘
```

### What's NOT sent
- Messages older than the 20-message window
- Raw command output (only the trimmed `history_obs` version)
- Full write-command payloads (replaced with `[N chars]` placeholder)

---

## 2. The trimming pipeline — step by step

When the agent executes a command, the observation goes through a multi-stage
pipeline before it enters history:

```
Command returns raw output (unbounded string)
        │
        ▼
   ┌─────────────────────────────────────────────────┐
   │ Stage 1: Raw output cap                         │
   │ obs[:MAX_OUTPUT_CHARS]  (300,000 chars)          │
   │ Safety net for runaway commands (find /, etc.)  │
   └─────────────────────────────────────────────────┘
        │
        ▼
   ┌─────────────────────────────────────────────────┐
   │ Stage 2: History compaction (command-aware)     │
   │                                                 │
   │ Write commands (write_file, replace_in_file,    │
   │   append_to_file, text_block_replace, etc.):    │
   │   → replaced with 1-line summary                │
   │     "write_file: ok (1234 bytes, 56 lines)"     │
   │                                                 │
   │ Read/other commands with output > 8k chars:     │
   │   → compress_observation() — head + tail        │
   │     keeps first ~2k AND last ~2k chars           │
   │     with "[…omitted N chars…]" in the middle    │
   │                                                 │
   │ Multi-file reads:                               │
   │   → each file compressed to ~1.2k chars         │
   │     then overall result capped to ~2k chars     │
   │                                                 │
   │ Small output (≤ 8k):                            │
   │   → kept as-is                                  │
   └─────────────────────────────────────────────────┘
        │
        ▼
   Stored in self.history as:
   {"role": "user", "content": "Observation: <history_obs>"}
```

### Assistant action compaction

The model's own JSON action is also compacted before storage:

```
Model outputs: {"action":"command","name":"write_file",
                "parameters":{"path":"app.py","content":"…50k of code…"}}
        │
        ▼
   ┌─────────────────────────────────────────────────┐
   │ _compact_action_for_history()                   │
   │                                                 │
   │ Total JSON ≤ 400 chars → keep as-is             │
   │                                                 │
   │ Write-heavy commands:                           │
   │   path, paths, command → kept in full            │
   │   content, old_string, new_string → "[N chars]" │
   │                                                 │
   │ Other commands:                                 │
   │   small params (≤ 80 chars) → kept              │
   │   large params → first 120 chars + "[N chars]"  │
   └─────────────────────────────────────────────────┘
        │
        ▼
   Stored in self.history as:
   {"role":"assistant","content":"{\"action\":\"command\",
     \"name\":\"write_file\",\"parameters\":{\"path\":\"app.py\",
     \"content\":\"[50000 chars]\"}}"}
```

**Why this matters:** Before this optimisation, a single `write_file` call with
30k of code would store 30k chars in the assistant message — and that message
would be re-sent on *every subsequent API call* within the 20-message window.
Now it stores ~100 chars.

---

## 3. Startup context — environment injection

Commands listed in `startup_observe` (YAML config) and `--startup-observe`
(CLI flag) are run once before the first step.  Their output is injected into
the **system message** as an `ENVIRONMENT` block.

```yaml
# agent config
startup_observe:
  - ls
  - cat project.md
```

**Trimming:** Each startup observe output is capped at `MAX_OBS_HISTORY_CHARS`
(8,000 chars).  This is critical because the system message is re-sent on
**every** API call — a 300k `find` output here would cost 300k input tokens
per step.

**Injection:** The environment block is included only on the **first** LLM
call of a run.  After that, `self._env_context_sent = True` and subsequent
calls use the plain system prompt (saving the environment block's size on
every future call).

---

## 4. Walked example — 5-step coding task

Agent: `pcode`, model: `gpt-5.4`

### Step 1 — Initial call

```
SYSTEM MESSAGE:
  system_prompt                          ~4,000 chars
  + ENVIRONMENT block:
    $ ls                                 ~200 chars
    $ cat project.md                     ~2,000 chars
                                         ─────────
                                  total: ~6,200 chars

HISTORY:
  [user] "Add input validation to        ~60 chars
          register_user() in api/users.py"
                                         ─────────
                               messages: 1
                          history chars: ~60 chars
                                         ═════════
                          TOTAL PAYLOAD: ~6,260 chars
```

**Model responds:** `read_file` on `api/users.py`

### Step 2 — After reading a file

```
SYSTEM MESSAGE:
  system_prompt (no ENVIRONMENT — already sent)
                                         ~4,000 chars

HISTORY (3 messages):
  [user  ] initial prompt                ~60 chars
  [assist] {"action":"command",          ~120 chars
            "name":"read_file",
            "parameters":{"path":"api/users.py"}}
  [user  ] Observation: <file content>   ~3,500 chars
           (file was 3.5k, under 8k cap — kept as-is)
                                         ─────────
                          history chars: ~3,680 chars
                                         ═════════
                          TOTAL PAYLOAD: ~7,680 chars
```

**Model responds:** `replace_in_file` with a 2k edit

### Step 3 — After a write command

```
HISTORY (5 messages):
  [user  ] initial prompt                ~60 chars
  [assist] read_file action              ~120 chars
  [user  ] Observation: <file content>   ~3,500 chars
  [assist] replace_in_file action        ~150 chars  ← was 2k, compacted!
           {"...","parameters":{
             "path":"api/users.py",
             "old_text":"[890 chars]",     ← payload replaced with size
             "new_text":"[1200 chars]"}}
  [user  ] Observation:                  ~50 chars
           "replace_in_file: ok (4521 bytes, 89 lines)"
           ← write command summarised to 1 line!
                                         ─────────
                          history chars: ~3,880 chars
                                         ═════════
                          TOTAL PAYLOAD: ~7,880 chars
```

**Notice:** The 2k `replace_in_file` payload was stored as ~150 chars.
The observation was summarised to 1 line instead of echoing the file.

### Step 4 — After reading a large file

Suppose the model reads a 40k-char file:

```
HISTORY (7 messages, last 7 all fit in 20-msg window):
  ...previous 5 messages...              ~3,880 chars
  [assist] read_file action              ~100 chars
  [user  ] Observation:                  ~4,000 chars
           first ~2k of file
           […omitted 36000 chars…]
           last ~2k of file
           ← head+tail compression, not blunt cut!
                                         ─────────
                          history chars: ~7,980 chars
                                         ═════════
                          TOTAL PAYLOAD: ~11,980 chars
```

The old blunt `[:8000]` cut would have lost the entire tail of the file.
Now the model sees both the beginning AND the end.

### Step 5 — Final answer

```
HISTORY (9 messages):
  ...accumulation from steps 1–4...      ~8,200 chars
  [user  ] Observation: tests pass       ~40 chars
  [hint  ] [context: 9 msgs, ~8240 chars]
                                         ─────────
                          history chars: ~8,240 chars
                                         ═════════
                          TOTAL PAYLOAD: ~12,240 chars
```

### Total for this 5-step task

| Step | Input chars | Input tokens (est.) | Output tokens (est.) |
|---|---|---|---|
| 1 | 6,260 | ~2,000 | ~200 |
| 2 | 7,680 | ~2,500 | ~400 |
| 3 | 7,880 | ~2,600 | ~2,000 (the edit) |
| 4 | 11,980 | ~4,000 | ~200 |
| 5 | 12,240 | ~4,100 | ~300 |
| **Total** | | **~15,200** | **~3,100** |

Without the compaction optimisations (old behaviour):

| Step | Input chars (old) | Difference |
|---|---|---|
| 3 | 9,880 (+2k from raw action) | +25% |
| 4 | 19,880 (+8k from blunt obs cut) | +66% |
| 5 | 20,240 | +65% |
| **Total** | **~21,500 tokens** | **+41% more expensive** |

---

## 5. Kept-session behaviour — `--keep-session-open`

When the session stays open between tasks, history from the previous task is
**automatically cleaned up** before the next task starts.

### The problem (before)

```
Task 1: 15 steps, 20k chars of history accumulated
Task 2: starts with 20k + new prompt → grows to 35k
Task 3: starts with 35k + new prompt → grows to 50k
...
Task 5: 80k chars of stale history → 500k+ input tokens across calls
```

### The solution — `_reset_for_new_task()`

Controlled by the `session_reset_mode` config key:

| Mode | Config value | Behaviour |
|---|---|---|
| **Summary** (default) | `session_reset_mode: summary` | Drops all history. Keeps a single user message with a ≤600-char recap of the last task's final answer. Best balance of savings vs. continuity. |
| **Reset** | `session_reset_mode: reset` | Nukes everything. Each task starts with zero history. Maximum token savings, zero continuity. |
| **Keep** | `session_reset_mode: keep` | Old behaviour. No cleanup. History snowballs. |

### Example — 3 tasks with `summary` mode

```
Task 1: "Fix the login bug"
  → 12 steps, history grows to 15 msgs / 18k chars
  → final answer: "Fixed null check in auth.py line 45"
  → _reset_for_new_task() runs:
    history = [
      {"role":"user","content":"[context] Previous task (#1) completed.
       Summary of result:\nFixed null check in auth.py line 45"}
    ]
    ← 1 message, ~100 chars (was 15 msgs / 18k chars)

Task 2: "Add rate limiting"
  → starts with 1 context msg + new prompt = 2 msgs / ~200 chars
  → 8 steps, history grows to 17 msgs / 14k chars
  → final answer: "Added RateLimiter middleware..."
  → _reset_for_new_task() runs:
    history = 1 msg / ~120 chars

Task 3: "Update the README"
  → starts fresh again: 2 msgs / ~180 chars
```

**Without session reset:**
Task 3 would start with 32 msgs / ~32k chars of stale history from tasks 1–2.

---

## 6. History pressure hints

When the accumulated history gets large, the runtime appends a hint to the
observation message:

```
Observation: <result>
[context: 18 msgs, ~24000 chars — consider compact_history if you have more work ahead]
```

This hint appears when **either**:
- `history_chars > 20,000`, OR
- `len(self.history) > max_context_messages - 4` (i.e., approaching the sliding window edge)

The model is instructed (via the system prompt) to call `compact_history`
when it sees this hint and still has significant work remaining.

### What `compact_history` does

```
Before:                           After:
  [user  ] initial prompt           [user  ] initial prompt
  [assist] action 1                 [assist] compact_history action
  [user  ] Observation 1            [user  ] "Summary of prior work:
  [assist] action 2                           Read auth.py (guards on L45),
  [user  ] Observation 2                      fixed token expiry in
  [assist] action 3                           refresh_token(), tests pass."
  [user  ] Observation 3            [assist] action 5  ← keep_recent=4
  [assist] action 4                 [user  ] Observation 5
  [user  ] Observation 4            [assist] action 6
  [assist] action 5                 [user  ] Observation 6
  [user  ] Observation 5
  [assist] action 6                 (12 messages → 7 messages)
  [user  ] Observation 6
```

The model provides the `summary` text, choosing what's important to remember.
The `keep_recent` parameter (default 4) controls how many recent messages
to preserve verbatim.

---

## 7. Context window for different communication types

### 7a. Single agent — one-shot (`agent.py`)

```
System prompt (~4k)
  + Environment block (first call only, each startup cmd ≤ 8k)
  + History window (last 20 messages)
    - user messages: prompts + observations (each obs ≤ 8k or compressed)
    - assistant messages: action JSON (write payloads compacted)
```

**Max theoretical size per call:**
- System prompt: ~5k chars
- Environment: ~16k chars (2 startup commands × 8k each, first call only)
- 20 history messages: 10 assistant (~150 each) + 10 user/obs (~4k each) = ~41.5k
- **Worst case first call: ~62k chars ≈ ~20k tokens**
- **Typical call: ~8–15k chars ≈ ~3–5k tokens**

### 7b. Persistent child agent (`call_agent`)

Child agents started via `call_agent` use `--keep-session-open`.
The parent sends follow-up prompts via stdin.

```
Same as single agent, but:
  - Session persists across parent's call_agent invocations
  - History accumulates across calls (within the 20-msg window)
  - session_reset_mode applies between tasks (default: summary)
```

**Token implication:** The child agent's first call costs system prompt + env.
Subsequent calls from the parent are cheap (just the new prompt added to
existing history).  But if the child does 20+ steps across multiple parent
calls, old messages slide out of the 20-msg window silently.

### 7c. Hierarchical agency (`agency`)

```
agency (orchestrator)
  ├─ call_agent → planner    [own context window, ~20k per call]
  ├─ call_agent → researcher [own context window, ~15k per call]
  ├─ call_agent → coder      [own context window, ~40k per call]
  └─ call_agent → reviewer   [own context window, ~20k per call]

Each child has its own isolated history.
The orchestrator's history contains the children's final answers (not their internals).
```

**Token implication:** Total tokens = orchestrator's calls + sum of all
children's calls.  Children's internal step-by-step reasoning is invisible
to the parent (only the final answer comes back as an observation).

### 7d. Swarm meeting (`swarm.py`)

```
Each participant agent per round:
  System prompt + ENVIRONMENT
  + History:
    [user] "Read the room, then post your contribution"
    [assist] room_read action
    [user] Observation: <full room contents>   ← grows every round!
    [assist] room_post action
    [user] Observation: posted

Room is append-only → every round adds all participants' posts.
Round 1: room has 3 posts → ~6k chars
Round 2: room has 6 posts → ~12k chars
Round 3: room has 9 posts → ~18k chars
```

**Token implication:** The swarm is the most expensive mode because every
participant reads the **full room** every round, and the room only grows.
3 agents × 3 rounds = 9 LLM calls, each reading an increasingly large room.

**Cost control:** Set `max_rounds: 2` and `done_threshold: 1` in the swarm
config to cap growth.

### 7e. Daemon (`agent_daemon.py`)

```
Same as --keep-session-open, but tasks arrive from a FIFO.
session_reset_mode applies between tasks.

With session_reset_mode: summary (default):
  Each task starts nearly clean — just a 1-line recap of the last task.

With session_reset_mode: keep:
  History accumulates across ALL tasks.
  Task 10 pays for the full history of tasks 1–9.
```

---

## 8. Truncation reference

### Constants (`agent_constants.py`)

| Constant | Default | What it caps |
|---|---|---|
| `MAX_OUTPUT_CHARS` | 300,000 | Raw command output (stage 1 safety net) |
| `MAX_OBS_HISTORY_CHARS` | 8,000 | Observation size threshold for compression |
| `OBSERVATION_FILE_PREVIEW_CHARS` | 1,200 | Per-file limit in multi-file read compression |
| `OBSERVATION_GENERIC_PREVIEW_CHARS` | 4,000 | Generic observation head+tail compression target |
| `OBSERVATION_COMPACT_PREVIEW_CHARS` | 2,000 | Overall cap after multi-file compression |
| `MAX_CONTEXT_MESSAGES` | 20 | Sliding window of messages sent to LLM |

### Per-agent overrides (`limits` in YAML)

```yaml
limits:
  max_obs_history_chars: 4000              # tighter observation cap
  observable_file_preview_chars: 800       # less per file in multi-read
  observable_generic_preview_chars: 2000   # tighter head+tail
  observable_compact_preview_chars: 1500   # tighter overall
```

### What gets truncated where

| Data | Stored in | Size in history | Size on current step |
|---|---|---|---|
| Startup observe output | System message (first call) | ≤ 8k per cmd | ≤ 8k per cmd |
| Write command obs | History (user msg) | 1-line summary (~50 chars) | Full output (≤ 300k) |
| Read command obs (small) | History (user msg) | As-is | As-is |
| Read command obs (large) | History (user msg) | Head+tail compressed (~4k) | Full output (≤ 300k) |
| Multi-file read obs | History (user msg) | ~1.2k per file, ~2k total | Full output (≤ 300k) |
| Assistant action (small) | History (assistant msg) | As-is (≤ 400 chars) | As-is |
| Assistant action (write) | History (assistant msg) | Path kept, payload → `[N chars]` | Full JSON |
| Assistant action (other) | History (assistant msg) | Params ≤ 80 chars kept, rest 120+size | Full JSON |

---

## 9. Verbose context preview

With `-v` (verbose mode), every step prints a context preview before the API
call:

```
[context] 7 msgs, ~8.2k chars
  [system] You are a Coding specialist a…: 4.1k
  [user  ] Add input validation to regis…: 62
  [assist] {"action":"command","name":"re…: 120
  [user  ] Observation: --- api/users.py…: 3.5k
  [assist] {"action":"command","name":"re…: 148
  [user  ] Observation: replace_in_file:…: 52
  [user  ] Run the tests to verify: 28
```

This shows exactly what's being sent, how large each message is, and which
messages are dominating the cost.  Use it to diagnose unexpectedly high
token usage.

---

## 10. Summary of optimisations

| Optimisation | What it saves | When it applies |
|---|---|---|
| Write-command observation → 1-line summary | ~2–50k per write step | Every write command |
| Assistant action payload compaction | ~2–50k per write step | Every write command |
| Head+tail observation compression | ~50% of large obs | Read commands > 8k |
| Environment block sent once | System prompt size on steps 2+ | Every run |
| Startup observe output capped to 8k | Prevents 300k system prompt | Every run |
| Sliding history window (20 msgs) | Unbounded growth | Every run |
| `compact_history` (model-initiated) | ~50–70% of history | Long sessions |
| `_reset_for_new_task()` (automatic) | ~95% of prior task history | `--keep-session-open` |
| `session_reset_mode: reset` | 100% of prior task history | `--keep-session-open` |

