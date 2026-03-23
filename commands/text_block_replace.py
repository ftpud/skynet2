import os
import re
import ast
from difflib import SequenceMatcher
from typing import List, Tuple


COMMAND_NAME = "text_block_replace"
DESCRIPTION = "Replace one or more anchor-based blocks in a UTF-8 text file with safety validation. Use 3-4 lines or function names for markers. Must not be empty."
USAGE_EXAMPLE = '{"action":"command","name":"text_block_replace","parameters":{"path":"notes.txt","blocks":[{"first_block_lines":["start marker"],"last_block_lines":["end marker"],"replace_with":"new text"}]}}'


SIMILARITY_THRESHOLD = 0.72
WINDOW_SIZE = 30


# =========================
# NORMALIZATION
# =========================


def normalize_code(line: str) -> str:
    """
    Normalize whitespace + punctuation spacing + strip comments.
    Works across Python / Swift / JS / Dart / Kotlin style syntax.
    """

    line = re.sub(r"(#.*$|//.*$)", "", line)
    line = re.sub(r"\s+", " ", line)
    line = re.sub(r"\s*([(),:{}=+\-*/<>])\s*", r"\1", line)

    return line.strip()


# =========================
# FUZZY MATCHING
# =========================


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def fuzzy_block_match(candidate: List[str], anchor: List[str]) -> float:
    """
    Per-line fuzzy similarity instead of concatenated comparison.
    Prevents structural false matches.
    """

    score = 0.0

    for a, b in zip(candidate, anchor):
        score += similar(a, b)

    return score / len(anchor)


# =========================
# INDENTATION BLOCK EXPANSION
# =========================


def expand_block(lines: List[str], start: int) -> Tuple[int, int]:
    """
    Expand block downward until indentation boundary.
    Useful when anchor sits inside function body.
    """

    indent = len(lines[start]) - len(lines[start].lstrip())

    end = start + 1

    while end < len(lines):

        line = lines[end]

        if not line.strip():
            end += 1
            continue

        current_indent = len(line) - len(line.lstrip())

        if current_indent <= indent:
            break

        end += 1

    return start, end


# =========================
# AST SYMBOL LOCATOR
# =========================


def extract_symbol_name(anchor_line: str) -> Optional[str]:
    """
    Extract function/class name safely from anchor.
    Supports async def / decorators / class.
    """

    anchor_line = anchor_line.strip()

    match = re.search(
        r"(?:async\s+def|def|class)\s+(\w+)",
        anchor_line
    )

    if match:
        return match.group(1)

    return None



def locate_python_symbol(lines: List[str], symbol_name: str):
    """
    Locate Python function/class via AST.
    """

    try:
        tree = ast.parse("".join(lines))
    except Exception:
        return None

    for node in ast.walk(tree):

        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):

            if node.name == symbol_name:
                return node.lineno - 1, node.end_lineno

    return None


# =========================
# ANCHOR SEARCH
# =========================


def find_anchor(lines: List[str], anchor_lines: List[str]):
    """
    Multi-stage anchor search:

    1 exact normalized match
    2 per-line fuzzy similarity match
    """

    normalized_lines = [normalize_code(l) for l in lines]
    normalized_anchor = [normalize_code(l) for l in anchor_lines]

    anchor_len = len(normalized_anchor)

    # PASS 1 exact normalized

    for i in range(len(lines) - anchor_len + 1):

        if normalized_lines[i:i + anchor_len] == normalized_anchor:
            return i

    # PASS 2 fuzzy match

    for i in range(len(lines) - anchor_len + 1):

        candidate = normalized_lines[i:i + anchor_len]

        if fuzzy_block_match(candidate, normalized_anchor) >= SIMILARITY_THRESHOLD:
            return i

    return None


# =========================
# BLOCK MATCHER
# =========================


def find_block(lines, first_lines, last_lines):
    """
    Locate replaceable block using anchors safely.
    """

    start = find_anchor(lines, first_lines)

    if start is None:
        return None

    search_start = start + 1 #len(first_lines)

    end_anchor = find_anchor(lines[search_start:], last_lines)

    if end_anchor is None:
        return None

    end = search_start + end_anchor + len(last_lines)

    return start, end


# =========================
# MAIN PATCH FUNCTION
# =========================


def patch_file(path: str, blocks: list):

    if not os.path.exists(path):
        return "ERROR: file not found"

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.splitlines(keepends=True)

    if not lines:
        return "ERROR: empty file"

    original_eol = '\r\n' if '\r\n' in content else '\n'

    replacements = []

    for block_index, block in enumerate(blocks):

        first_lines = block.get("first_block_lines")
        last_lines = block.get("last_block_lines")
        replace_with = block.get("replace_with")

        if not first_lines or not last_lines:
            return f"ERROR: block[{block_index}] missing anchors"

        if isinstance(first_lines, str):
            first_lines = [first_lines]

        if isinstance(last_lines, str):
            last_lines = [last_lines]

        match = find_block(lines, first_lines, last_lines)

        if match:

            start, end = match

        else:

            symbol_name = extract_symbol_name(first_lines[0])

            if symbol_name:

                ast_match = locate_python_symbol(lines, symbol_name)

                if ast_match:
                    start, end = ast_match
                else:
                    return f"ERROR: block[{block_index}] not found"

            else:
                return f"ERROR: block[{block_index}] not found"

        if replace_with:

            replacement_lines = [
                l.rstrip("\r\n") + original_eol
                for l in replace_with.splitlines()
            ]

        else:
            replacement_lines = []

        replacements.append((start, end, replacement_lines))

    replacements.sort()

    for i in range(len(replacements) - 1):

        if replacements[i][1] > replacements[i + 1][0]:
            return "ERROR: overlapping patch blocks"

    updated = list(lines)

    for start, end, repl in reversed(replacements):
        updated[start:end] = repl

    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(updated))

    return f"OK: patched {len(replacements)} block(s)"


# =========================
# COMMAND ENTRYPOINT
# =========================


def execute(parameters: dict):

    if not isinstance(parameters, dict):
        return "ERROR: parameters must be object"

    path = parameters.get("path")
    blocks = parameters.get("blocks")

    if not isinstance(path, str):
        return "ERROR: path missing"

    if not isinstance(blocks, list):
        return "ERROR: blocks missing"

    return patch_file(path, blocks)