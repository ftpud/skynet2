import os

COMMAND_NAME = "text_block_replace"
DESCRIPTION = "Replace one or more anchor-based blocks in a UTF-8 text file with safety validation. Use 3-4 lines or function names for markers."
USAGE_EXAMPLE = '{"action":"command","name":"text_block_replace","parameters":{"path":"notes.txt","blocks":[{"first_block_lines":["start marker"],"last_block_lines":["end marker"],"replace_with":"new text"}]}}'


def _normalize_lines(value, field_name: str, block_index: int):
    if value is None:
        return None, f"ERROR: blocks[{block_index}].{field_name} is required"

    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list) and value:
        items = value
    else:
        return None, f"ERROR: blocks[{block_index}].{field_name} must be a non-empty string or list of strings"

    normalized = []
    for item in items:
        if not isinstance(item, str):
            item = str(item)
        # === HEURISTIC: collapse all whitespace (fixes AI spacing quirks) ===
        collapsed = ' '.join(item.strip().split())
        normalized.append(collapsed)

    if not any(normalized):
        return None, f"ERROR: blocks[{block_index}].{field_name} cannot be empty"

    return normalized, None


def _build_normalized_index(lines: list[str]) -> tuple[list[str], list[int]]:
    normalized_lines: list[str] = []
    line_indexes: list[int] = []

    for idx, line in enumerate(lines):
        # === HEURISTIC: same collapse as anchors ===
        normalized = ' '.join(line.rstrip("\r\n").strip().split())
        if not normalized:
            continue
        normalized_lines.append(normalized)
        line_indexes.append(idx)

    return normalized_lines, line_indexes


def _find_matches(lines: list[str], first_lines: list[str], last_lines: list[str]) -> list[tuple[int, int]]:
    first_len = len(first_lines)
    last_len = len(last_lines)
    matches: list[tuple[int, int]] = []
    normalized_lines, line_indexes = _build_normalized_index(lines)

    for start in range(len(normalized_lines)):
        if start + first_len > len(normalized_lines):
            break
        if normalized_lines[start : start + first_len] != first_lines:
            continue

        for end_start in range(start + first_len - 1, len(normalized_lines)):
            if end_start + last_len > len(normalized_lines):
                break
            if normalized_lines[end_start : end_start + last_len] == last_lines:
                actual_start = line_indexes[start]
                actual_end = line_indexes[end_start + last_len - 1] + 1
                matches.append((actual_start, actual_end))

    return matches


def execute(parameters: dict) -> str:
    try:
        if not isinstance(parameters, dict):
            return "ERROR: parameters must be an object"

        path = parameters.get("path")
        if not path or not isinstance(path, str):
            return "ERROR: 'path' is required"

        blocks = parameters.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            return "ERROR: 'blocks' must be a non-empty list"

        target = os.path.abspath(path)
        if os.path.isdir(target):
            return "ERROR: path is a directory"
        if not os.path.exists(target):
            return "ERROR: file not found"

        with open(target, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.splitlines(keepends=True)
        if not lines:
            return "ERROR: file is empty"

        # === NEW: detect original line ending so replacement never messes whitespace ===
        original_eol = '\r\n' if '\r\n' in content else '\n'

        validated_replacements: list[tuple[int, int, str]] = []

        for i, block in enumerate(blocks, start=1):
            if not isinstance(block, dict):
                return f"ERROR: blocks[{i}] must be an object"

            first_lines, err = _normalize_lines(block.get("first_block_lines", block.get("first_block_line")), "first_block_lines", i)
            if err:
                return err

            last_lines, err = _normalize_lines(block.get("last_block_lines", block.get("last_block_line")), "last_block_lines", i)
            if err:
                return err

            replace_with = block.get("replace_with")
            if replace_with is None:
                return f"ERROR: blocks[{i}].replace_with is required"
            if not isinstance(replace_with, str):
                replace_with = str(replace_with)

            # Normalize replace_with newlines to match file (prevents mixed EOL mess)
            replace_with = replace_with.replace('\r\n', '\n').replace('\r', '\n')
            if replace_with and not replace_with.endswith('\n'):
                replace_with += '\n'

            matches = _find_matches(lines, first_lines, last_lines)
            if not matches:
                return f"ERROR: blocks[{i}] anchor block not found"

            if len(matches) > 1:
                first_content = ["".join(lines[s:e]) for s, e in matches]
                if len(set(first_content)) != 1:
                    return f"ERROR: blocks[{i}] multiple different blocks matched same anchors; aborting for safety"

            start_idx, end_idx = matches[0]
            validated_replacements.append((start_idx, end_idx, replace_with))

        validated_replacements.sort(key=lambda item: item[0])
        for idx in range(1, len(validated_replacements)):
            _, prev_end, _ = validated_replacements[idx - 1]
            curr_start, _, _ = validated_replacements[idx]
            if curr_start < prev_end:
                return "ERROR: block ranges overlap; aborting for safety"

        updated_lines = list(lines)
        for start_idx, end_idx, replace_with in reversed(validated_replacements):
            # Build lines with original EOL
            if replace_with:
                replacement_lines = [line + original_eol for line in replace_with.splitlines()]
            else:
                replacement_lines = []
            updated_lines[start_idx:end_idx] = replacement_lines

        with open(target, "w", encoding="utf-8") as f:
            f.write("".join(updated_lines))

        return f"OK: replaced {len(validated_replacements)} block(s) in {path}"
    except UnicodeDecodeError:
        return "ERROR: file is not valid UTF-8 text"
    except Exception as e:
        return f"ERROR: {e}"