# Token Flow Analysis — agent.py

## Overview

This document explains exactly how tokens flow through the ReAct agent loop, what gets sent to the model at each step, how the context window grows, and concrete recommendations to reduce token usage and costs.

---

## 1. Architecture: The ReAct Loop

The agent follows a **Reason → Act → Observe** loop:


User Prompt
    │
    ▼
┌─────────────────────────────────────────────┐
│  STEP N                                     │
│  Send: [system_prompt] + history[-20:]      │
│  Receive: JSON action from model            │
│  Execute command → get observation          │
│  Append assistant + observation to history  │
│  Repeat until final_answer or max_steps     │
└─────────────────────────────────────────────┘


Every single API call sends:

tokens_sent = system_prompt + all_history_messages (up to last 20)


---

## 2. What Gets Sent to the Model — Message Structure

Each API call constructs this message list (from `run()` method):

python
messages = [
    {"role": "system",    "content": system_prompt},   # ALWAYS sent, every step
    {"role": "user",      "content": initial_prompt},   # step 0 seed
    {"role": "assistant", "content": '{"action":"command","name":"read_file",...}'},
    {"role": "user",      "content": "Observation: <file contents>"},
    {"role": "assistant", "content": '{"action":"command","name":"write_file",...}'},
    {"role": "user",      "content": "Observation: success"},
    # ... up to 20 messages from history
]


### System Prompt Composition (`_build_system_prompt`)

The system prompt is built once at init and contains:

| Section | Typical Size |
|---|---|
| Role declaration | ~20 tokens |
| base_system_prompt from YAML | 50–300 tokens |
| JSON format instructions | ~150 tokens |
| ALLOWED COMMANDS list (name + description + example per command) | 50–200 tokens per command |
| ALLOWED AGENTS list | 30–100 tokens per agent |
| STRATEGY + SAFETY rules | ~80 tokens |

**Example system prompt token estimate:** 500–1500 tokens depending on how many commands/agents are configured.

---

## 3. Context Window Growth — Step by Step

Below is a concrete walkthrough of a 3-step task: *"read file, process it, write result"*

### Initial State (before Step 1)


Context Window:
┌──────────────────────────────────────────────────────┐
│ [system]  You are a coding agent...                  │
│           ALLOWED COMMANDS: read_file, write_file... │
│           ~800 tokens                                │
├──────────────────────────────────────────────────────┤
│ [user]    "Read ./notes.txt and summarize it"        │
│           ~12 tokens                                 │
└──────────────────────────────────────────────────────┘
Total sent to model: ~812 tokens
Model output: ~30 tokens


---

### After Step 1 — Model calls read_file

Model responds:

{"action": "command", "name": "read_file", "parameters": {"path": "./notes.txt"}}


Agent executes `read_file`, gets back 500 words (~700 tokens) of file content.
Both the assistant response AND the observation are appended to `self.history`.


Context Window sent at Step 2:
┌──────────────────────────────────────────────────────┐
│ [system]  ~800 tokens  (IDENTICAL to step 1)         │
├──────────────────────────────────────────────────────┤
│ [user]    "Read ./notes.txt and summarize it" ~12t   │
├──────────────────────────────────────────────────────┤
│ [assistant] {"action":"command","name":"read_file"…} │
│           ~25 tokens                                 │
├──────────────────────────────────────────────────────┤
│ [user]    "Observation: <full file contents>"        │
│           ~700 tokens  ← FILE CONTENT STAYS FOREVER  │
└──────────────────────────────────────────────────────┘
Total sent to model: ~1537 tokens
Model output: ~40 tokens


**Key insight:** The file content (700 tokens) is now permanently in the context and will be re-sent on EVERY subsequent step.

---

### After Step 2 — Model calls write_file

Model responds:

{"action": "command", "name": "write_file", "parameters": {"path": "./summary.txt", "content": "Summary: ..."}}


Observation returned: `"File written successfully"` (~5 tokens)


Context Window sent at Step 3:
┌──────────────────────────────────────────────────────┐
│ [system]  ~800 tokens                                │
├──────────────────────────────────────────────────────┤
│ [user]    initial prompt ~12 tokens                  │
├──────────────────────────────────────────────────────┤
│ [assistant] read_file command ~25 tokens             │
├──────────────────────────────────────────────────────┤
│ [user]    Observation: <file contents> ~700 tokens   │
├──────────────────────────────────────────────────────┤
│ [assistant] write_file command ~45 tokens            │
├──────────────────────────────────────────────────────┤
│ [user]    Observation: File written successfully ~5t  │
└──────────────────────────────────────────────────────┘
Total sent to model: ~1587 tokens
Model output: ~20 tokens (final_answer)


---

### Cumulative Token Cost for This 3-Step Example

| Step | Tokens IN | Tokens OUT | Running Total IN |
|------|-----------|------------|------------------|
| 1    | 812       | 30         | 812              |
| 2    | 1,537     | 40         | 2,349            |
| 3    | 1,587     | 20         | 3,936            |
| **Total** | **3,936** | **90** | — |

Notice: tokens IN grow with each step because history accumulates. The system prompt (~800t) is re-sent **every single step**.

---

## 4. Realistic Long-Task Example (10 steps)

Assume:
- System prompt: 800 tokens
- Initial prompt: 20 tokens
- Each command response: ~30 tokens
- Each observation: ~200 tokens average


Step 1:  800 + 20                              =  820 in
Step 2:  800 + 20 + 30 + 200                   = 1050 in
Step 3:  800 + 20 + 30+200 + 30+200            = 1280 in
Step 4:  800 + 20 + (30+200)×3                 = 1510 in
...
Step 10: 800 + 20 + (30+200)×9                 = 2890 in

Total IN:  (820 + 1050 + 1280 + ... + 2890)
         = 800×10 + 20×10 + 230×(0+1+2+...+9)
         = 8000 + 200 + 230×45
         = 8000 + 200 + 10350
         = ~18,550 tokens IN
Total OUT: 10 × ~35 = ~350 tokens OUT


With GPT-4o pricing ($2.50/1M in, $10/1M out):
- Input cost:  18,550 / 1,000,000 × $2.50 = **$0.046**
- Output cost:   350 / 1,000,000 × $10.00 = **$0.004**
- **Total: ~$0.05 for a 10-step task**

With a large observation (e.g. reading a 5000-token file at step 2):
- That 5000 tokens gets re-sent in steps 3–10 = 8 extra sends × 5000 = **40,000 extra tokens**
- Additional cost: 40,000 / 1M × $2.50 = **$0.10 extra** just for one large file read

---

## 5. The MAX_CONTEXT_MESSAGES=20 Sliding Window

From the code:
python
messages = [
    {"role": "system", "content": self.system_prompt}
] + self.history[-self.max_context_messages:]  # last 20 messages


This means:
- History is capped at **20 messages** (10 assistant + 10 user pairs = 10 steps)
- Beyond 10 steps, old context is **silently dropped** — the model loses memory of early actions
- The system prompt is **never dropped** — it's always prepended fresh
- Token counter (`session_tokens_in`) still counts the full payload each step

**Sliding window behavior:**

Step 1–10:  All history fits in window, nothing dropped
Step 11:    Message from step 1 (user prompt) is dropped
Step 12:    Assistant response from step 1 is dropped
...         Early observations permanently lost from context
Step 20:    Only steps 11–20 visible to model


This is a hard tradeoff: prevents runaway token costs but causes the model to forget early context.

---

## 6. Token Counting in Code

The agent tracks tokens via API usage responses:

python
# OpenAI Chat Completions
self.session_tokens_in  += usage.prompt_tokens
self.session_tokens_out += usage.completion_tokens

# OpenAI Responses API (Codex)
self.session_tokens_in  += usage.input_tokens
self.session_tokens_out += usage.output_tokens

# Claude
self.session_tokens_in  += usage.input_tokens
self.session_tokens_out += usage.output_tokens


These are logged at session end:

{
  "type": "session_end",
  "tokens": {
    "inbound": 18550,
    "outbound": 350,
    "total": 18900
  }
}


**Important caveat:** When streaming is cancelled early (after JSON is parsed), the usage count may be **incomplete** — especially for Claude where `get_final_message()` is skipped on early parse.

---

## 7. Early Stream Cancellation — Token Savings

The agent uses an optimization: it parses JSON **while streaming** and breaks as soon as a valid JSON object is found:

python
for chunk in stream:
    full_response += delta
    parsed_early = self._extract_json(full_response)
    if parsed_early is not None:
        break   # ← stop reading, don't wait for full response


This saves output tokens when the model generates verbose reasoning before/after the JSON. However:
- The model is still **billed for all tokens it generated** up to the break point
- Tokens generated after the break are NOT billed (generation stops server-side only if the connection is closed)
- For OpenAI streaming, closing the stream does NOT stop generation — you're billed for the full completion
- For Claude, breaking the stream context manager does cancel generation

---

## 8. Child Agent Token Costs

When `run_agent` is called, a **subprocess** is spawned:

python
cmd = [sys.executable, os.path.abspath(__file__),
       "--agent", child_agent,
       "--prompt", child_prompt,
       "--depth", str(self.depth + 1), ...]
subprocess.run(cmd, ...)


The child agent:
- Loads its **own** system prompt (its own YAML config)
- Maintains its **own** history and token counters
- Parent's token counter does **NOT** include child's tokens
- Each child can spawn up to 5 grandchildren, up to depth 3

**Worst case token multiplication:**

Parent:  1 agent  × N steps × (system + history)
Child:   5 agents × M steps × (system + history) each
Grand:   25 agents × K steps × (system + history) each

Total API calls = N + 5M + 25K


With depth=3, max_children=5: up to **1 + 5 + 25 = 31 concurrent agent sessions**, each with their own token burn.

---

## 9. Identified Inefficiencies & Reduction Strategies

### 9.1 System Prompt Re-sent Every Step ❌ HIGH IMPACT

**Problem:** The system prompt (500–1500 tokens) is prepended to every API call.

**Current code:**
python
messages = [
    {"role": "system", "content": self.system_prompt}  # re-sent every step
] + self.history[-self.max_context_messages:]


**Solutions:**
- **OpenAI:** Use the [Prompt Caching](https://platform.openai.com/docs/guides/prompt-caching) feature — system prompts >1024 tokens are automatically cached. Cached tokens cost 50% less. No code change needed, just ensure system prompt is >1024 tokens and stable.
- **Claude:** Use `cache_control` on the system prompt block — cached reads cost ~10% of full price.
- **Estimated saving:** 40–60% of input token costs for long sessions.

### 9.2 Large Observations Permanently in Context ❌ HIGH IMPACT

**Problem:** When a command returns large output (file contents, command output), it stays in history and is re-sent every subsequent step.

**Example:** Reading a 3000-token file at step 2 of a 10-step task re-sends those 3000 tokens 8 more times = 24,000 wasted tokens.

**Current code:**
python
self.history.append({"role": "user", "content": f"Observation: {obs}"})
# obs can be up to MAX_OUTPUT_CHARS = 300,000 characters!


**Solutions:**
- **Truncate observations** stored in history (not just what's displayed). Store a summary like `"Observation: [read_file result, 3000 tokens, stored externally]"` and keep full content in a separate dict.
- **Summarize large observations** before appending: if `len(obs) > 500 tokens`, call a cheap model (gpt-4o-mini) to summarize it first.
- **Estimated saving:** 30–70% of input tokens for file-heavy tasks.

### 9.3 Redundant History Messages ⚠️ MEDIUM IMPACT

**Problem:** Every command generates 2 history messages (assistant action + user observation). For a 10-step task that's 20 messages — exactly at the `MAX_CONTEXT_MESSAGES=20` limit, meaning the initial user prompt gets dropped.

**Solution:** Compress completed action+observation pairs into a single summary message:
python
# Instead of 2 messages:
{"role": "assistant", "content": '{"action":"command","name":"read_file",...}'}
{"role": "user",      "content": "Observation: <3000 tokens>"}

# Use 1 compressed message:
{"role": "user", "content": "[Step 2] read_file('./notes.txt') → success, 3000 chars read"}

This halves the message count and allows more steps before context truncation.

### 9.4 Verbose System Prompt ⚠️ MEDIUM IMPACT

**Problem:** The system prompt includes full descriptions and usage examples for every allowed command, even ones rarely used.

**Current format:**

• read_file
  Read the contents of a text file from disk.
  Example: {"action":"command","name":"read_file","parameters":{"path":"notes.txt"}}


**Optimized format:**

read_file(path) — read UTF-8 file
write_file(path, content) — write file
linux_command(command) — run shell command


This can reduce system prompt by 30–50% (200–600 tokens) with minimal impact on model performance for capable models.

### 9.5 Token Counter Inaccuracy During Early Stream Exit ⚠️ LOW IMPACT

**Problem:** When JSON is parsed early from the stream, the usage counter may be 0 (especially Claude), leading to inaccurate cost tracking.

**Solution:** Always call `get_final_message()` in a background thread or use the `usage` from the stream's `__message` attribute before breaking.

### 9.6 Model Selection ⚠️ MEDIUM IMPACT

**Problem:** Using GPT-4o or Claude Sonnet for every step, including trivial ones.

**Solution:** Use a cheaper model (gpt-4o-mini at $0.15/1M in vs $2.50/1M for GPT-4o) for:
- Simple file reads/writes
- Observation summarization
- Steps where the action is obvious

Reserve expensive models for complex reasoning steps.

---

## 10. Summary Table — Token Reduction Opportunities

| Optimization | Effort | Token Saving | Cost Saving |
|---|---|---|---|
| Enable prompt caching (OpenAI/Claude) | Low — zero code change | 40–60% of system prompt tokens | High |
| Truncate/summarize large observations in history | Medium | 30–70% of input tokens | Very High |
| Compress action+observation into single message | Medium | ~30% fewer history tokens | Medium |
| Shorten system prompt command descriptions | Low | 200–600 tokens/step | Medium |
| Use gpt-4o-mini for simple steps | Medium | 90% cost reduction per cheap step | High |
| Fix token counter on early stream exit | Low | Accuracy only, no actual saving | — |

---

## 11. Conclusion

The agent's token usage follows a **triangular growth pattern** — each step re-sends all previous history plus the fixed system prompt. The dominant costs are:

1. **System prompt** (~800t) × number of steps — mitigated for free by prompt caching
2. **Large observations** (file contents, command output) that persist in history for all remaining steps
3. **Child agents** that each run independent sessions with their own full token budgets

The most impactful single change would be **observation truncation in history storage**: instead of keeping the full file content in history, store a short summary and reference. Combined with prompt caching (zero-effort on OpenAI), this could reduce costs by **50–80%** for typical file-manipulation tasks without changing agent behavior.

The current `MAX_CONTEXT_MESSAGES=20` sliding window is a reasonable safety valve but causes silent context loss after 10 steps — a compressed history approach would be strictly better.
