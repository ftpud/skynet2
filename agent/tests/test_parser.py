from __future__ import annotations

from agent.utils.parser import parse_first_json_object, validate_action_payload


def test_parse_first_json_object_balanced_with_prefix_suffix() -> None:
    text = 'noise before {"action":"final_answer","content":"ok"} trailing'
    parsed = parse_first_json_object(text)
    assert parsed["action"] == "final_answer"
    assert parsed["content"] == "ok"


def test_parse_first_json_object_trailing_comma_recovery() -> None:
    text = '{"action":"command","name":"ls","parameters":{},}'
    parsed = parse_first_json_object(text)
    assert parsed["action"] == "command"
    assert parsed["name"] == "ls"


def test_parse_first_json_object_single_quote_recovery() -> None:
    text = "{'action':'command','name':'read_file','parameters':{'path':'x'}}"
    parsed = parse_first_json_object(text)
    assert parsed["action"] == "command"
    assert parsed["name"] == "read_file"
    assert parsed["parameters"]["path"] == "x"


def test_validate_action_payload_rejects_invalid_shapes() -> None:
    try:
        validate_action_payload({"action": "command", "name": "ls"})
        assert False, "expected ValueError"
    except ValueError:
        pass

    try:
        validate_action_payload({"action": "final_answer", "content": 1})
        assert False, "expected ValueError"
    except ValueError:
        pass
