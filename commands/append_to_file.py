import os

COMMAND_NAME = "append_to_file"
DESCRIPTION = "Append text content to the end of a file."
USAGE_EXAMPLE = '{"action":"command","name":"append_to_file","parameters":{"path":"notes.txt","content":"more text"}}'


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
        if os.path.isdir(target):
            return "ERROR: path is a directory"

        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(target, "a", encoding="utf-8") as f:
            f.write(content)

        return f"OK: appended {len(content)} chars to {path}"
    except Exception as e:
        return f"ERROR: {e}"
