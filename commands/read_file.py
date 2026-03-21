import os

COMMAND_NAME = "read_file"
DESCRIPTION = "Read the contents of a text file from disk."
USAGE_EXAMPLE = '{"action":"command","name":"read_file","parameters":{"path":"notes.txt"}}'


def execute(parameters: dict) -> str:
    try:
        if not isinstance(parameters, dict):
            return "ERROR: parameters must be an object"

        path = parameters.get("path")
        if not path or not isinstance(path, str):
            return "ERROR: 'path' is required"

        target = os.path.abspath(path)
        if os.path.isdir(target):
            return "ERROR: path is a directory"
        if not os.path.exists(target):
            return "ERROR: file not found"

        with open(target, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        return "ERROR: file is not valid UTF-8 text"
    except Exception as e:
        return f"ERROR: {e}"
