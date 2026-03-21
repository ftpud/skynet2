import os

COMMAND_NAME = "replace_in_multiple_files"
DESCRIPTION = "Replace a unique text block in multiple UTF-8 text files."
USAGE_EXAMPLE = '{"action":"command","name":"replace_in_multiple_files","parameters":{"replacements":[{"path":"file1.txt","old_text":"old1","new_text":"new1"},{"path":"file2.txt","old_text":"old2","new_text":"new2"}]}}'


def execute(parameters: dict) -> str:
    try:
        if not isinstance(parameters, dict):
            return "ERROR: parameters must be an object"

        replacements = parameters.get("replacements")
        if replacements is None:
            return "ERROR: 'replacements' is required"
        if not isinstance(replacements, list):
            return "ERROR: 'replacements' must be an array"
        if len(replacements) == 0:
            return "ERROR: 'replacements' must not be empty"

        results = []

        for idx, item in enumerate(replacements):
            if not isinstance(item, dict):
                results.append(f"[{idx}] ERROR: each replacement must be an object")
                continue

            path = item.get("path")
            if not path or not isinstance(path, str):
                results.append(f"[{idx}] ERROR: 'path' is required")
                continue

            old_text = item.get("old_text")
            if old_text is None:
                results.append(f"[{idx}] ERROR: 'old_text' is required")
                continue
            if not isinstance(old_text, str):
                old_text = str(old_text)

            new_text = item.get("new_text")
            if new_text is None:
                results.append(f"[{idx}] ERROR: 'new_text' is required")
                continue
            if not isinstance(new_text, str):
                new_text = str(new_text)

            try:
                target = os.path.abspath(path)
                if os.path.isdir(target):
                    results.append(f"[{idx}] ERROR: path is a directory ({path})")
                    continue
                if not os.path.exists(target):
                    results.append(f"[{idx}] ERROR: file not found ({path})")
                    continue

                with open(target, "r", encoding="utf-8") as f:
                    content = f.read()

                count = content.count(old_text)
                if count == 0:
                    results.append(f"[{idx}] ERROR: old_text not found in {path}")
                    continue
                if count > 1:
                    results.append(f"[{idx}] ERROR: old_text must match exactly once in {path}")
                    continue

                updated = content.replace(old_text, new_text, 1)

                with open(target, "w", encoding="utf-8") as f:
                    f.write(updated)

                results.append(f"[{idx}] OK: replaced text block in {path}")

            except UnicodeDecodeError:
                results.append(f"[{idx}] ERROR: file is not valid UTF-8 text ({path})")
            except Exception as e:
                results.append(f"[{idx}] ERROR: {e} ({path})")

        return "\n".join(results)

    except Exception as e:
        return f"ERROR: {e}"
