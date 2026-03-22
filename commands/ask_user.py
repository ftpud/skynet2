COMMAND_NAME = "ask_user"
DESCRIPTION = "Prompt the user for input and return their response."
USAGE_EXAMPLE = '{"action":"command","name":"ask_user","parameters":{"prompt":"What should I do next?"}}'


def execute(parameters: dict) -> str:
    if not isinstance(parameters, dict):
        return "ERROR: parameters must be an object"

    prompt = parameters.get("prompt")
    if not prompt or not isinstance(prompt, str):
        return "ERROR: 'prompt' is required"

    try:
        return input(prompt + " ")
    except EOFError:
        return "ERROR: no user input available"
    except Exception as e:
        return f"ERROR: {e}"
