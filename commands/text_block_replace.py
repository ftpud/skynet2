import ast
import os
import re
from difflib import SequenceMatcher
from typing import List, Optional


COMMAND_NAME = "text_block_replace"
DESCRIPTION = "Replace one anchor-based block in a UTF-8 text file with safety validation. Use 3-4 lines or function names for markers. Must not be empty."
USAGE_EXAMPLE = '{"action":"command","name":"text_block_replace","parameters":{"path":"notes.txt","first_block_lines":["start marker"],"last_block_lines":["end marker"],"replace_with":"new text"}}'


SIMILARITY_THRESHOLD = 0.72


def normalize_code(line: str) -> str:
    line = re.sub(r"(#.*$|//.*$)", "", line)
    line = re.sub(r"\s+", " ", line)
    line = re.sub(r"\s*([(),:{}=+\-*/<>])\s*", r"\1", line)
    return line.strip()


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def fuzzy_block_match(candidate: List[str], anchor: List[str]) -> float:
    score = 0.0
    for a, b in zip(candidate, anchor):
        score += similar(a, b)
    return score / len(anchor)


def extract_symbol_name(anchor_line: str) -> Optional[str]:
    match = re.search(r"(?:async\s+def|def|class)\s+(\w+)", anchor_line.strip())
    if match:
        return match.group(1)
    return None


def locate_python_symbol(lines: List[str], symbol_name: str):
    try:
        tree = ast.parse("".join(lines))
    except Exception:
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol_name:
            return node.lineno - 1, node.end_lineno
    return None


def find_anchor_positions(lines: List[str], anchor_lines: List[str]) -> List[int]:
    normalized_lines = [normalize_code(l) for l in lines]
    normalized_anchor = [normalize_code(l) for l in anchor_lines]
    anchor_len = len(normalized_anchor)

    if anchor_len == 0 or anchor_len > len(lines):
        return []

    exact_matches = []
    for i in range(len(lines) - anchor_len + 1):
        if normalized_lines[i:i + anchor_len] == normalized_anchor:
            exact_matches.append(i)
    if exact_matches:
        return exact_matches

    fuzzy_matches = []
    for i in range(len(lines) - anchor_len + 1):
        candidate = normalized_lines[i:i + anchor_len]
        if fuzzy_block_match(candidate, normalized_anchor) >= SIMILARITY_THRESHOLD:
            fuzzy_matches.append(i)
    return fuzzy_matches


def find_block(lines: List[str], first_lines: List[str], last_lines: List[str]):
    first_positions = find_anchor_positions(lines, first_lines)
    if not first_positions:
        return None

    first_len = len(first_lines)
    last_len = len(last_lines)

    for start in first_positions:
        search_from = start
        last_positions = find_anchor_positions(lines[search_from:], last_lines)
        for rel_last in last_positions:
            last_start = search_from + rel_last
            end = last_start + last_len
            if end < start + first_len:
                continue
            return start, end

    return None


def patch_file(path: str, block: dict):
    if not os.path.exists(path):
        return "ERROR: file not found"

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.splitlines(keepends=True)
    if not lines:
        return "ERROR: empty file"

    original_eol = "\r\n" if "\r\n" in content else "\n"

    first_lines = block.get("first_block_lines")
    last_lines = block.get("last_block_lines")
    replace_with = block.get("replace_with")

    if not first_lines or not last_lines:
        return "ERROR: block[0] missing anchors"

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
                return "ERROR: block[0] not found"
        else:
            return "ERROR: block[0] not found"

    if replace_with:
        replacement_lines = [l.rstrip("\r\n") + original_eol for l in replace_with.splitlines()]
    else:
        replacement_lines = []

    updated = list(lines)
    updated[start:end] = replacement_lines

    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(updated))

    return "OK: patched 1 block"


def execute(parameters: dict):
    if not isinstance(parameters, dict):
        return "ERROR: parameters must be object"

    path = parameters.get("path")
    first_block_lines = parameters.get("first_block_lines")
    last_block_lines = parameters.get("last_block_lines")
    replace_with = parameters.get("replace_with")

    if not isinstance(path, str):
        return "ERROR: path missing"

    if first_block_lines is None or last_block_lines is None:
        return "ERROR: first_block_lines/last_block_lines missing"

    if isinstance(first_block_lines, str):
        first_block_lines = [first_block_lines]
    if isinstance(last_block_lines, str):
        last_block_lines = [last_block_lines]

    if not isinstance(first_block_lines, list) or not isinstance(last_block_lines, list):
        return "ERROR: first_block_lines/last_block_lines must be string or array"

    block = {
        "first_block_lines": first_block_lines,
        "last_block_lines": last_block_lines,
        "replace_with": replace_with,
    }

    return patch_file(path, block)
