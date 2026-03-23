COMMAND_NAME = "call_agent"
DESCRIPTION = "Call another configured agent in a persistent session and return its latest final answer while preserving child context across calls."
USAGE_EXAMPLE = '{"action":"command","name":"call_agent","parameters":{"agent":"reviewer","prompt":"Review this plan","session_id":"review-thread-1"}}'


def execute(parameters: dict) -> str:
    return "ERROR: Not implemented (handled by core agent runtime)"
