import os


COMMAND_NAME = "apply_patch2"
DESCRIPTION = "Apply a unified patch in Codex apply_patch format (*** Begin Patch ... *** End Patch) to files."
USAGE_EXAMPLE = '{"action":"command","name":"apply_patch2","parameters":{"patch":"*** Begin Patch\\n*** Update File: notes.txt\\n@@\\n-old\\n+new\\n*** End Patch\\n"}}'


def _parse_patch(patch_text: str):
    lines = patch_text.splitlines()
    if not lines or lines[0].strip() != "*** Begin Patch":
        raise ValueError("patch must start with '*** Begin Patch'")

    i = 1
    ops = []
    while i < len(lines):
        line = lines[i]
        if line.strip() == "*** End Patch":
            return ops

        if line.startswith("*** Update File: "):
            path = line[len("*** Update File: "):].strip()
            i += 1
            hunk_lines = []
            while i < len(lines):
                cur = lines[i]
                if cur.startswith("*** Update File: ") or cur.startswith("*** Add File: ") or cur.startswith("*** Delete File: ") or cur.strip() == "*** End Patch":
                    break
                hunk_lines.append(cur)
                i += 1
            ops.append(("update", path, hunk_lines))
            continue

        if line.startswith("*** Add File: "):
            path = line[len("*** Add File: "):].strip()
            i += 1
            add_lines = []
            while i < len(lines):
                cur = lines[i]
                if cur.startswith("*** Update File: ") or cur.startswith("*** Add File: ") or cur.startswith("*** Delete File: ") or cur.strip() == "*** End Patch":
                    break
                if not cur.startswith("+"):
                    raise ValueError(f"invalid add line for {path}: expected '+' prefix")
                add_lines.append(cur[1:])
                i += 1
            ops.append(("add", path, add_lines))
            continue

        if line.startswith("*** Delete File: "):
            path = line[len("*** Delete File: "):].strip()
            ops.append(("delete", path, None))
            i += 1
            continue

        raise ValueError(f"unexpected patch line: {line}")

    raise ValueError("patch missing '*** End Patch'")


def _apply_update(path: str, hunk_lines: list[str]):
    if not os.path.exists(path):
        raise ValueError(f"file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        original = f.read().splitlines()

    out = []
    idx = 0

    for raw in hunk_lines:
        if raw.startswith("@@"):
            continue
        if raw == "*** End of File":
            continue
        if not raw:
            raise ValueError("invalid empty hunk line")

        prefix = raw[0]
        text = raw[1:]

        if prefix == " ":
            if idx >= len(original) or original[idx] != text:
                raise ValueError(f"context mismatch in {path}: expected '{text}'")
            out.append(original[idx])
            idx += 1
        elif prefix == "-":
            if idx >= len(original) or original[idx] != text:
                raise ValueError(f"delete mismatch in {path}: expected '{text}'")
            idx += 1
        elif prefix == "+":
            out.append(text)
        else:
            raise ValueError(f"invalid hunk prefix '{prefix}' in {path}")

    out.extend(original[idx:])

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + ("\n" if out else ""))


def execute(parameters: dict):
    if not isinstance(parameters, dict):
        return "ERROR: parameters must be object"

    patch = parameters.get("patch")
    if not isinstance(patch, str) or not patch.strip():
        return "ERROR: patch missing"

    try:
        ops = _parse_patch(patch)
        applied = 0
        for op, path, payload in ops:
            if op == "update":
                _apply_update(path, payload or [])
            elif op == "add":
                parent = os.path.dirname(path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write("\n".join(payload or []) + ("\n" if payload else ""))
            elif op == "delete":
                if not os.path.exists(path):
                    raise ValueError(f"file not found: {path}")
                os.remove(path)
            applied += 1
        return f"OK: applied {applied} operation(s)"
    except Exception as e:
        return f"ERROR: {e}"
