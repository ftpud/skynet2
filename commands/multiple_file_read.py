import os

COMMAND_NAME = "multiple_file_read"
DESCRIPTION = "Read the contents of multiple text files from disk in sequence and return all contents chained together."
USAGE_EXAMPLE = '{"action":"command","name":"multiple_file_read","parameters":{"paths":["file1.txt","file2.txt"]}}'


def execute(parameters: dict) -> str:
    try:
        if not isinstance(parameters, dict):
            return "ERROR: parameters must be an object"

        paths = parameters.get("paths")
        if not paths or not isinstance(paths, list):
            return "ERROR: 'paths' is required and must be a list"

        if len(paths) == 0:
            return "ERROR: 'paths' list must not be empty"

        results = []

        for path in paths:
            if not path or not isinstance(path, str):
                results.append(f"--- ERROR: invalid path entry '{path}' ---")
                continue

            target = os.path.abspath(path)

            if os.path.isdir(target):
                results.append(f"--- ERROR: '{path}' is a directory ---")
                continue
            if not os.path.exists(target):
                results.append(f"--- ERROR: '{path}' file not found ---")
                continue

            try:
                with open(target, "r", encoding="utf-8") as f:
                    content = f.read()
                results.append(f"--- {path} ---\n{content}")
            except UnicodeDecodeError:
                results.append(f"--- ERROR: '{path}' is not valid UTF-8 text ---")
            except Exception as e:
                results.append(f"--- ERROR reading '{path}': {e} ---")

        return "\n\n".join(results)

    except Exception as e:
        return f"ERROR: {e}"
