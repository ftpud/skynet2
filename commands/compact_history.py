COMMAND_NAME = "compact_history"
DESCRIPTION = (
    "Compact the conversation history to save context window space. "
    "Provide a 'summary' of everything important learned so far (key facts, "
    "file paths, decisions, what was done and what remains). "
    "The runtime will replace all old messages with this summary, keeping only "
    "the most recent messages. Also accepts optional 'keep_recent' (int, default 4) "
    "to control how many recent message pairs to preserve verbatim."
)
USAGE_EXAMPLE = (
    '{"action":"command","name":"compact_history","parameters":{'
    '"summary":"Read config.py (DB creds on L45). Fixed bug in handler.py L120: '
    'changed == to !=. Still need to update tests.","keep_recent":4}}'
)


# NOTE: execute() is defined here for the loader to register metadata,
# but the actual logic runs inside Agent.execute_command() because it
# needs direct access to self.history.
def execute(parameters: dict) -> str:
    return "ERROR: compact_history must be handled by the agent runtime"

