import os

COMMAND_NAME = "read_file"
DESCRIPTION = (
    "Read the contents of a text file from disk. "
    "Optional: start_line (1-based, inclusive), end_line (1-based, inclusive), "
    "max_chars (cap total returned characters). "
    "Use line ranges to avoid reading large files in full."
)
USAGE_EXAMPLE = (
    '{"action":"command","name":"read_file","parameters":{"path":"notes.txt"}} '
    'or {"action":"command","name":"read_file","parameters":{"path":"big.py","start_line":10,"end_line":50}}'
)


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

        start_line = parameters.get("start_line")
        end_line = parameters.get("end_line")
        max_chars = parameters.get("max_chars")

        with open(target, "r", encoding="utf-8") as f:
            if start_line is not None or end_line is not None:
                lines = f.readlines()
                total_lines = len(lines)
                s = max(1, int(start_line)) if start_line is not None else 1
                e = min(total_lines, int(end_line)) if end_line is not None else total_lines
                selected = lines[s - 1 : e]
                content = "".join(selected)
                header = f"[lines {s}-{e} of {total_lines}]\n"
            else:
                content = f.read()
                header = ""

        if max_chars is not None:
            limit = int(max_chars)
            if len(content) > limit:
                content = content[:limit] + f"\n[…truncated at {limit} chars]"

        return header + content
    except UnicodeDecodeError:
        return "ERROR: file is not valid UTF-8 text"
    except Exception as e:
        return f"ERROR: {e}"
