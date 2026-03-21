COMMAND_NAME = "run_agent"
DESCRIPTION = "Run another configured agent with a prompt and return its final answer."
USAGE_EXAMPLE = '{"action":"command","name":"run_agent","parameters":{"agent":"reviewer","prompt":"Review this plan"}}'


def execute(parameters: dict) -> str:
    return "ERROR: run_agent is handled internally by Agent.execute_command"
