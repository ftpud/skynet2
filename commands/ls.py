import os

COMMAND_NAME = "ls"
DESCRIPTION = "List files and directories in a target path."
USAGE_EXAMPLE = '{"action":"command","name":"ls","parameters":{"path":"."}}'


def execute(parameters: dict) -> str:
    try:
        if parameters is None:
            parameters = {}
        if not isinstance(parameters, dict):
            return "ERROR: parameters must be an object"

        path = parameters.get("path", ".")
        if not isinstance(path, str):
            return "ERROR: 'path' must be a string"

        target = os.path.abspath(path)
        if not os.path.exists(target):
            return "ERROR: path not found"
        if not os.path.isdir(target):
            return "ERROR: path is not a directory"

        entries = sorted(os.listdir(target))
        if not entries:
            return "(empty)"
        return "\n".join(entries)
    except Exception as e:
        return f"ERROR: {e}"
