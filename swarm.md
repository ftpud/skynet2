# Swarm — Multi-Agent Meeting Room

## What it is

Swarm is a collaborative multi-agent mode where several independent agents share a common "room" and work together on a topic.  Unlike the delegation model (one orchestrator assigns tasks to one specialist at a time), every swarm participant:

- Reads the **same shared context** — all posts from all agents so far
- Decides **what to contribute** based on what is already in the room
- Posts to the room **visible to all other agents** in subsequent turns
- Self-signals when they believe the discussion is **complete**

The result is emergent collaboration: the analyst structures the problem, the coder picks up the design and implements, the critic reviews — without any central controller telling them to.

---

## How it works

```
swarm.py --topic "Design a Redis caching layer"
         --config agents/swarm.yaml
```

```
Round 0  facilitator posts the topic
─────────────────────────────────────────────
Round 1  swarm_analyst  → room_read → room_post(analysis)
         swarm_coder    → room_read → room_post(proposal)
         swarm_critic   → room_read → room_post(review)
─────────────────────────────────────────────
Round 2  each agent reads ALL prior posts and builds on them
         agents post refinements, corrections, done signals
─────────────────────────────────────────────
         meeting ends when done_threshold agents post type=done
         OR max_rounds is reached
```

Each agent turn is a **one-shot `agent.py` run**.  The agent's job per turn:

1. Call `room_read` to see the full discussion
2. Do any thinking / investigation (reads files, runs commands, etc.)
3. Post contribution(s) with `room_post`
4. Optionally post `type=done` if the topic is resolved
5. Give `final_answer` summarising the turn (brief — detail lives in the room)

---

## Room format

The room is an **append-only JSONL file** in `rooms/`.  Each line is one post:

```json
{"round": 0, "author": "facilitator", "type": "task",     "content": "Design a Redis caching layer...", "timestamp": "..."}
{"round": 1, "author": "swarm_analyst", "type": "analysis", "content": "The main API endpoints are...",   "timestamp": "..."}
{"round": 1, "author": "swarm_coder",   "type": "proposal", "content": "I suggest a decorator-based ...", "timestamp": "..."}
{"round": 1, "author": "swarm_critic",  "type": "review",   "content": "The proposal looks good but ...", "timestamp": "..."}
{"round": 2, "author": "swarm_coder",   "type": "done",     "content": "Implementation complete.",        "timestamp": "..."}
{"round": 2, "author": "swarm_critic",  "type": "done",     "content": "Verified and signed off.",        "timestamp": "..."}
```

Post **types**:

| type | meaning |
|---|---|
| `task` | The meeting topic, posted by the facilitator |
| `analysis` | Structured breakdown, requirements, observations |
| `proposal` | Implementation approach or design decision |
| `code` | Completed change, snippet, or diff summary |
| `review` | Finding, concern, or risk |
| `question` | Something that needs clarification |
| `decision` | A conclusion being committed to |
| `done` | This agent believes the objective is achieved |
| `message` | General contribution not fitting other types |
| `error` | Posted automatically by the coordinator on agent failure |

---

## Files

| File | Purpose |
|---|---|
| `swarm.py` | Coordinator: creates room, drives rounds, detects consensus, prints output |
| `agents/swarm.yaml` | Meeting configuration (participants, rounds, thresholds) |
| `agents/swarm_analyst.yaml` | Analysis specialist participant |
| `agents/swarm_coder.yaml` | Implementation specialist participant |
| `agents/swarm_critic.yaml` | Review / quality specialist participant |
| `commands/room_read.py` | Command: read the shared room |
| `commands/room_post.py` | Command: post to the shared room |
| `rooms/` | Generated room JSONL files (one per meeting) |

---

## Commands

### `room_read`
Reads all posts from the shared room, formatted for easy agent consumption.

```json
{"action": "command", "name": "room_read", "parameters": {}}
{"action": "command", "name": "room_read", "parameters": {"last_n": 10}}
```

Returns a formatted view:
```
════════════════════════════════════════════════════════════════════
  MEETING ROOM  (5 posts)
════════════════════════════════════════════════════════════════════

┌── SETUP ───────────────────────────────────────────────────────
│ facilitator  [task]  2026-03-24 12:00:00
────────────────────────────────────────────────────────────────
  Design a Redis caching layer for the API

┌── ROUND 1 ─────────────────────────────────────────────────────
│ swarm_analyst  [analysis]  2026-03-24 12:00:15
────────────────────────────────────────────────────────────────
  The main hotspot is GET /api/users — called 200×/s...
```

### `room_post`
Posts a message to the room.  Author and round number are injected automatically from environment variables set by `swarm.py` — the agent only needs to supply `content` and `type`.

```json
{"action": "command", "name": "room_post", "parameters": {
  "content": "The cache TTL should be configurable per endpoint.",
  "type": "proposal"
}}
```

```json
{"action": "command", "name": "room_post", "parameters": {
  "content": "Implementation complete and verified.",
  "type": "done"
}}
```

---

## Configuration — `agents/swarm.yaml`

```yaml
participants:
  - swarm_analyst      # any agent name with a matching agents/<name>.yaml
  - swarm_coder
  - swarm_critic

max_rounds: 4          # hard cap — meeting ends after this many rounds
done_threshold: 2      # stop early when this many distinct agents post type=done
response_timeout: 300  # seconds allowed per agent turn

# optional global overrides (individual agent yamls take precedence)
# provider: openai
# model: gpt-5.4-mini
```

To run a different meeting configuration, copy `swarm.yaml`, change the participants list and pass it via `--config`.

---

## Participant agents

Each swarm agent needs `room_read` and `room_post` in its `permissions` list.  Beyond that it's a standard agent config — it can have any other permissions it needs to do its work (file reads, shell commands, code edits, etc.).

### `swarm_analyst`
- Model: `gpt-5.4-mini`
- Focus: requirements, constraints, risk identification, problem decomposition
- Permissions: `room_read`, `room_post`, `read_file`, `multiple_file_read`, `ls`, `linux_command`
- Characteristic posts: `analysis`, `question`, `decision`

### `swarm_coder`
- Model: `gpt-5.3-codex`
- Focus: translating analysis into proposals and concrete code changes
- Permissions: `room_read`, `room_post`, `read_file`, `write_file`, `replace_in_file`, `linux_command`, …
- Characteristic posts: `proposal`, `code`

### `swarm_critic`
- Model: `gpt-5.4-mini`
- Focus: reviewing contributions, finding defects and gaps, driving consensus
- Permissions: `room_read`, `room_post`, `read_file`, `linux_command`
- Characteristic posts: `review`, `decision`, `done`

---

## Running a meeting

```bash
# Basic — auto-detect skynet2 dir, use agents/swarm.yaml
python swarm.py --topic "Add rate limiting to the REST API"

# Verbose — shows each agent's reasoning in real time
python swarm.py --topic "Refactor the auth module" -v

# Custom config
python swarm.py --config agents/swarm.yaml --topic "Design the caching layer"

# Force model for all participants
python swarm.py --topic "..." --model gpt-4o-mini --provider openai

# Explicit room file (reproducible / resumable meetings)
python swarm.py --topic "..." --room-file rooms/my-meeting.jsonl

# Print a summary of a past meeting
python swarm.py --summary --room-file rooms/add_rate_limiting_20260324_120000.jsonl
```

---

## Adding a new participant

1. Create `agents/<name>.yaml` with `room_read` and `room_post` in permissions.
2. Write a `base_system_prompt` that explains the agent's role and the meeting protocol.
3. Add `<name>` to the `participants` list in `agents/swarm.yaml` (or a custom config).

Minimal participant template:

```yaml
role: "Swarm <role>"
description: "What this participant does in a meeting."
provider: openai
model: gpt-5.4-mini
temperature: 0.2
max_tokens: 8192

permissions:
  - room_read
  - room_post
  # add tools the agent needs for its role

base_system_prompt: |
  You are a <role> specialist in a multi-agent meeting (swarm).

  MEETING PROTOCOL:
  1. Call room_read to see the full discussion.
  2. Contribute with room_post (type: analysis / proposal / code / review / question / decision / done).
  3. Post type=done if the meeting objective is achieved from your perspective.
  4. Give final_answer summarising your turn briefly.

  Do NOT ask the user for anything — work from what is in the room.

limits:
  max_steps: 20
  max_depth: 1
  max_children: 0
```

---

## Difference from the agency model

| | Agency | Swarm |
|---|---|---|
| Control | Central orchestrator delegates tasks | No central controller — agents self-select |
| Context | Each agent sees only what the orchestrator sends | All agents share the same room |
| Communication | Orchestrator → specialist (1-to-1) | All agents read and write the same space |
| Turns | Orchestrator decides who acts next | Coordinator gives every participant a turn each round |
| Completion | Orchestrator judges "done" | Agents signal done themselves; consensus stops the meeting |
| Good for | Structured multi-step pipelines | Open-ended exploration, design discussions, mutual review |

---

## Environment variables (set by `swarm.py` per turn)

| Variable | Value | Used by |
|---|---|---|
| `SWARM_ROOM_FILE` | Absolute path to the room JSONL | `room_read`, `room_post` |
| `SWARM_AGENT_NAME` | The participating agent's name | `room_post` (sets author) |
| `SWARM_ROUND` | Current round number (integer) | `room_post` (sets round field) |

---

## Logs

- **Coordinator log**: `logs/swarm_<ts>.log` — rotating, 10 MB × 3 backups, always DEBUG
- **Room file**: `rooms/<topic-slug>_<ts>.jsonl` — permanent append-only record of the meeting
- **Agent logs**: each participant's `agent.py` run produces its own step log in `logs/`

