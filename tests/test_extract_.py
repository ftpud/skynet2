from agent_utils import extract_all_json_actions, extract_json


def test_extract_json_returns_first_action_only():
    text = "\n".join([
        '{"action":"command","name":"read_file","parameters":{"path":"a.txt"}}',
        '{"action":"command","name":"read_file","parameters":{"path":"b.txt"}}',
        '{"action":"final_answer","content":"done"}',
    ])

    result = extract_json(text)

    assert result == {"action": "command", "name": "read_file", "parameters": {"path": "a.txt"}}


def test_extract_all_json_actions_returns_all_blocks_in_order():
    text = "\n".join([
        '{"action":"command","name":"read_file","parameters":{"path":"a.txt"}}',
        '{"action":"command","name":"read_file","parameters":{"path":"b.txt"}}',
        '{"action":"final_answer","content":"done"}',
    ])

    result = extract_all_json_actions(text)

    assert result == [
        {"action": "command", "name": "read_file", "parameters": {"path": "a.txt"}},
        {"action": "command", "name": "read_file", "parameters": {"path": "b.txt"}},
        {"action": "final_answer", "content": "done"},
    ]


def test_extract_all_json_actions_ignores_non_action_json():
    text = """
{"note":"ignore me"}
{"action":"command","name":"read_file","parameters":{"path":"a.txt"}}
"""

    result = extract_all_json_actions(text)

    assert result == [
        {"action": "command", "name": "read_file", "parameters": {"path": "a.txt"}},
    ]
