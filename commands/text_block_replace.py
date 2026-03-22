import os

COMMAND_NAME = "text_block_replace"
DESCRIPTION = "Replace one or more line-range blocks in a UTF-8 text file with safety validation."
USAGE_EXAMPLE = '{"action":"command","name":"text_block_replace","parameters":{"path":"notes.txt","blocks":[{"line_range":"10-15","replace_with":"new text","first_block_line":"start marker","last_block_line":"end marker"}]}}'


def _parse_line_range(value) -> tuple[int, int] | tuple[None, None]:
    if isinstance(value, str):
        parts = value.split("-", 1)
        if len(parts) != 2:
            return None, None
        try:
            start = int(parts[0].strip())
            end = int(parts[1].strip())
        except Exception:
            return None, None
        return start, end

    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return int(value[0]), int(value[1])
        except Exception:
            return None, None

    return None, None


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
        line_count = len(lines)
        if line_count == 0:
            return "ERROR: file is empty"

        replacements: list[tuple[int, int, str]] = []
        seen_ranges: set[tuple[int, int]] = set()

        for i, block in enumerate(blocks, start=1):
            if not isinstance(block, dict):
                return f"ERROR: blocks[{i}] must be an object"

            start, end = _parse_line_range(block.get("line_range"))
            if start is None or end is None:
                return f"ERROR: blocks[{i}].line_range must be like '10-15' or [10,15]"
            if start < 1 or end < start:
                return f"ERROR: blocks[{i}].line_range is invalid"
            if end > line_count:
                return f"ERROR: blocks[{i}].line_range exceeds file length ({line_count} lines)"

            range_key = (start - 1, end)
            if range_key in seen_ranges:
                return "ERROR: duplicate block range; aborting for safety"
            seen_ranges.add(range_key)

            first_block_line = block.get("first_block_line")
            last_block_line = block.get("last_block_line")
            replace_with = block.get("replace_with")

            if first_block_line is None:
                return f"ERROR: blocks[{i}].first_block_line is required"
            if last_block_line is None:
                return f"ERROR: blocks[{i}].last_block_line is required"
            if replace_with is None:
                return f"ERROR: blocks[{i}].replace_with is required"

            if not isinstance(first_block_line, str):
                first_block_line = str(first_block_line)
            if not isinstance(last_block_line, str):
                last_block_line = str(last_block_line)
            if not isinstance(replace_with, str):
                replace_with = str(replace_with)

            block_lines = lines[start - 1 : end]
            if not block_lines:
                return f"ERROR: blocks[{i}] resolved to empty block"

            actual_first = block_lines[0].rstrip("\r\n")
            actual_last = block_lines[-1].rstrip("\r\n")

            if actual_first != first_block_line:
                return f"ERROR: blocks[{i}] first line mismatch"
            if actual_last != last_block_line:
                return f"ERROR: blocks[{i}] last line mismatch"

            replacements.append((start - 1, end, replace_with))

        replacements.sort(key=lambda item: item[0])
        for idx in range(1, len(replacements)):
            prev_start, prev_end, _ = replacements[idx - 1]
            curr_start, curr_end, _ = replacements[idx]
            if curr_start < prev_end:
                return "ERROR: block ranges overlap; aborting for safety"

        updated_parts = []
        cursor = 0
        for start_idx, end_idx, replace_with in replacements:
            updated_parts.append("".join(lines[cursor:start_idx]))
            updated_parts.append(replace_with)
            cursor = end_idx
        updated_parts.append("".join(lines[cursor:]))
        updated = "".join(updated_parts)

        with open(target, "w", encoding="utf-8") as f:
            f.write(updated)

        return f"OK: replaced {len(replacements)} block(s) in {path}"
    except UnicodeDecodeError:
        return "ERROR: file is not valid UTF-8 text"
    except Exception as e:
        return f"ERROR: {e}"
