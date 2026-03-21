import os

COMMAND_NAME = "write_file"
DESCRIPTION = "Write text content to a file, creating parent directories when needed."
USAGE_EXAMPLE = '{"action":"command","name":"write_file","parameters":{"path":"notes.txt","content":"hello"}}'


def execute(parameters: dict) -> str:
    try:
        if not isinstance(parameters, dict):
            return "ERROR: parameters must be an object"

        path = parameters.get("path")
        if not path or not isinstance(path, str):
            return "ERROR: 'path' is required"

        content = parameters.get("content")
        if content is None:
            return "ERROR: 'content' is required"
        if not isinstance(content, str):
            content = str(content)

        target = os.path.abspath(path)
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)

        if os.path.isdir(target):
            return "ERROR: path is a directory"

        with open(target, "w", encoding="utf-8") as f:
            f.write(content)

        return f"OK: wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"ERROR: {e}"
