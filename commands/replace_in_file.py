import os

COMMAND_NAME = "replace_in_file"
DESCRIPTION = "Replace a unique text block in a UTF-8 text file."
USAGE_EXAMPLE = '{"action":"command","name":"replace_in_file","parameters":{"path":"notes.txt","old_text":"old","new_text":"new"}}'


def execute(parameters: dict) -> str:
    try:
        if not isinstance(parameters, dict):
            return "ERROR: parameters must be an object"

        path = parameters.get("path")
        if not path or not isinstance(path, str):
            return "ERROR: 'path' is required"

        old_text = parameters.get("old_text")
        if old_text is None:
            return "ERROR: 'old_text' is required"
        if not isinstance(old_text, str):
            old_text = str(old_text)

        new_text = parameters.get("new_text")
        if new_text is None:
            return "ERROR: 'new_text' is required"
        if not isinstance(new_text, str):
            new_text = str(new_text)

        target = os.path.abspath(path)
        if os.path.isdir(target):
            return "ERROR: path is a directory"
        if not os.path.exists(target):
            return "ERROR: file not found"

        with open(target, "r", encoding="utf-8") as f:
            content = f.read()

        count = content.count(old_text)
        if count == 0:
            return "ERROR: old_text not found"
        if count > 1:
            return "ERROR: old_text must match exactly once"

        updated = content.replace(old_text, new_text, 1)

        with open(target, "w", encoding="utf-8") as f:
            f.write(updated)

        return f"OK: replaced text block in {path}"
    except UnicodeDecodeError:
        return "ERROR: file is not valid UTF-8 text"
    except Exception as e:
        return f"ERROR: {e}"
