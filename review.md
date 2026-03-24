# Skynet2 — Project Review

## Verdict: solid, not garbage

This is a well-structured, functional ReAct agent framework. The core loop is sound, the plugin system works, the safety boundaries are reasonable, and the multi-agent orchestration (both `run_agent` and persistent `call_agent`) is a genuinely useful feature you won't find in most open-source agent frameworks. It's clearly a working tool you're actively using, not a toy.

That said — there are real issues worth fixing. Organized by severity:

---

## 🔴 Actual Bugs

### 1. `apply_patch.py` and `apply_patch2.py` are identical
Line-for-line copy. `apply_patch2` has its own `COMMAND_NAME = "apply_patch2"` but the code is byte-for-byte the same. Neither is used in any agent's permissions. This is dead code — either one was meant to be an improved version and you forgot to finish it, or it's just a duplicate.

### 2. `extract_usage` double-counts cached tokens
```python
# agent_utils.py, responses path
input_tokens = _read(usage, "input_tokens", "prompt_tokens")
input_tokens += _read(input_details, "cached_tokens")  # ← ADDS cached on top
```
OpenAI's `input_tokens` already **includes** `cached_tokens`. Adding it again inflates your reported input token count. Same issue with `reasoning_tokens` being added to `output_tokens` — reasoning tokens are already part of `output_tokens` in the API response.

### 3. `_env_context_sent` never resets between `run()` calls
In `--keep-session-open` mode, `run()` is called multiple times. But `_env_context_sent` is set to `True` on the first call and never reset. So the second prompt in a session never gets the environment context. This might be intentional, but if the user changes directory between prompts, the stale context is both absent and wrong.

### 4. Hook output injected twice on first call
```python
system_content = self.system_prompt + "\n\nENVIRONMENT:\n" + self.environment_context
# environment_context already contains init_hook_output (line 631)
if self.init_hook_output:
    system_content += "\n\nINIT HOOK OUTPUT:\n" + self.init_hook_output  # ← duplicate
```
`self.environment_context` is built from `startup_context` + `init_hook_output` (line 631), then `init_hook_output` is appended again separately. The model sees the hook output twice on the first step.

---

## 🟡 Weird Decisions / Design Smells

### 5. `__import__("json")` used inline everywhere
At least 6 places in `agent.py` do `__import__("json").dumps(...)` instead of just `json.dumps(...)`. The `json` module isn't imported at the top of `agent.py` even though it's a core dependency used on every single step. Costs nothing to add `import json` and makes the code cleaner.

### 6. `selectors` imported inside a method
```python
def _call_agent(self, params, step):
    ...
    import selectors  # line ~370
```
This import belongs at the top of the file. It's a stdlib module and it's used every time a persistent child session is called.

### 7. `parallel_tool_calls` passed to Responses API but not wired to anything
```python
parallel_tool_calls=self.parallel_tool_calls,  # in _call_model
```
This parameter is passed to `responses.stream()` but your agent doesn't use OpenAI's native tool-calling — you use a custom JSON protocol. This kwarg does nothing useful and may cause errors if OpenAI tightens validation.

### 8. `limits` can be `None`, causing `.get()` on NoneType
```python
limits = config.get("limits", {})
```
If a YAML has `limits:` with no value, `config.get("limits", {})` returns `None`, not `{}`. Then `limits.get("max_steps", ...)` crashes. Should be `config.get("limits") or {}`.

### 9. Claude retry loop re-sends the same conversation
When Claude truncates at `max_tokens`, the code doubles `claude_max_tokens` and retries — but sends the exact same `claude_messages`. This means the model regenerates from scratch, paying full input tokens again. The retry is a cost multiplier, not a continuation.

### 10. The `process_all_json_blocks` CLI flag is marked "deprecated" but still functional
The argparse help says "deprecated compatibility flag" but the code still branches on it. Either remove it or un-deprecate it.

### 11. No command has a `run()` fallback — dead code path
```python
handler = getattr(module, "execute", None)
if not callable(handler):
    handler = getattr(module, "run", None)  # ← never triggered
```
Every single command implements `execute()`. The `run()` fallback in the loader is dead code.

---

## 🟢 Minor / Cosmetic

### 12. `ARCHITECTUDE.md` — typo in filename
Should be `ARCHITECTURE.md`.

### 13. Several agent YAMLs have non-command strings in `permissions`
```yaml
# code.yaml previously had:
permissions:
  - Treat every task as a coding task. Execute changes yourself.
```
These get silently ignored (the loader skips unknown names), but they're clearly base_system_prompt lines that leaked into the wrong field. The grep output from earlier showed this in `code.yaml`, `sonnet.yaml`, `review.yaml`, and `planner.yaml`. Most have been cleaned up but verify `planner.yaml` — it still has prompt text in permissions.

### 14. `test_extract_.py` — filename has trailing underscore
Looks like a partial rename. Should be `test_extract_json.py` (which also exists separately).

### 15. `run_agent.py` and `call_agent.py` command files have unused imports
`run_agent.py` imports `json`, `subprocess`, `sys`, `Path` — none are used. The `execute()` just returns an error string since the real logic is in `agent.py`.

### 16. Token logging on verbose close is slightly misleading
`_log_session_end` calls `_run_hook("on_run_finish")` before `log_session_end`. If the finish hook itself triggers logging or takes time, the session-end timestamp is after the hook. Not a bug but can confuse log analysis.

### 17. `_BLOCKED` command list is trivially bypassable
```python
_BLOCKED = ["rm -rf", "shutdown", ...]
```
`rm -r -f`, `rm --recursive --force`, `command rm -rf`, `bash -c 'rm -rf /'` all bypass this. This is a speed bump, not real security. Fine for personal use, but the ARCHITECTURE.md shouldn't call it a "safety model."

---

## Architecture Strengths (what's genuinely good)

- **Plugin system is clean**. Drop a `.py` in `commands/`, drop a `.yaml` in `agents/`, no orchestrator changes needed. This is the right design.
- **`call_agent` with persistent sessions** is a solid feature. Real inter-agent context preservation via stdin/stdout with selector-based async reading. It's pragmatic and it works.
- **Early JSON extraction during streaming** saves real money by aborting output generation as soon as a valid action is parsed.
- **Loop detection** (3 identical consecutive actions → terminate) is simple and effective.
- **The agent YAML configs are well-designed** — role, permissions, limits, hooks, startup_observe, allowed_agents. Good separation of policy from mechanism.
- **The TUI** is a nice operational dashboard for monitoring token spend.

---

## Summary

| Aspect | Rating |
|---|---|
| Core architecture | ✅ Sound |
| Plugin extensibility | ✅ Good |
| Multi-agent orchestration | ✅ Strong feature |
| Token/cost management | ⚠️ Improving (recent compact_history + obs trimming) |
| Code hygiene | ⚠️ Inline imports, dead code, duplicate files |
| Safety claims | ⚠️ Overstated in docs vs actual enforcement |
| Test coverage | ⚠️ Minimal (4 test files, only JSON parsing + text_block_replace covered) |
| Bug count | 🔴 4 real bugs found above |

**Bottom line**: This is a legitimate, working agent framework with good architectural instincts. Not garbage at all. Fix the token double-counting bug and the hook duplication, clean up the dead code, and it's solid.
