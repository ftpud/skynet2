MAX_STEPS = 30
MAX_RETRIES_PER_STEP = 3
MAX_OUTPUT_CHARS = 300000
# Observations are trimmed to this length before being stored in history.
# Much smaller than MAX_OUTPUT_CHARS so old observations don't bloat the
# context window on every subsequent API call.
MAX_OBS_HISTORY_CHARS = 8000
MAX_CONTEXT_MESSAGES = 20
MAX_AGENT_DEPTH = 3
MAX_CHILD_AGENTS = 5
CHILD_AGENT_TIMEOUT = 600
