from __future__ import annotations

import json
from typing import Any


def extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    return None


def _remove_trailing_commas(text: str) -> str:
    result: list[str] = []
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            result.append(char)
            continue

        if char == ",":
            j = index + 1
            while j < len(text) and text[j].isspace():
                j += 1
            if j < len(text) and text[j] in "]}":
                continue

        result.append(char)
    return "".join(result)


def tolerant_json_loads(text: str) -> Any:
    candidates = [text]
    if "'" in text:
        candidates.append(text.replace("'", '"'))
    cleaned = _remove_trailing_commas(text)
    if cleaned not in candidates:
        candidates.append(cleaned)
    if "'" in cleaned:
        candidates.append(cleaned.replace("'", '"'))

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Unable to parse JSON: {last_error}")


def parse_first_json_object(text: str) -> Any:
    block = extract_first_json_object(text)
    if block is None:
        raise ValueError("No JSON object found")
    return tolerant_json_loads(block)


def validate_action_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Parsed JSON must be an object")
    action = payload.get("action")
    if action not in {"command", "final_answer"}:
        raise ValueError("Invalid or missing action field")
    if action == "command":
        if not isinstance(payload.get("name"), str) or not payload["name"].strip():
            raise ValueError("Command action requires a non-empty name")
        if not isinstance(payload.get("parameters"), dict):
            raise ValueError("Command action requires parameters as an object")
    else:
        if not isinstance(payload.get("content"), str):
            raise ValueError("final_answer action requires string content")
    return payload
