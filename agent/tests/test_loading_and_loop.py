from __future__ import annotations

import tempfile
from pathlib import Path

from agent import agent as core


class DummyClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)



def test_discover_and_filter_commands() -> None:
    modules = core.discover_command_modules()
    names = {getattr(m, "COMMAND_NAME") for m in modules}
    assert {"read_file", "write_file", "append_to_file", "linux_command", "run_agent", "ls"}.issubset(names)

    filtered = core.filter_commands_by_permissions(modules, ["ls", "read_file"])
    filtered_names = {getattr(m, "COMMAND_NAME") for m in filtered}
    assert filtered_names == {"ls", "read_file"}


def test_loop_detection_terminates(monkeypatch) -> None:
    monkeypatch.setattr(core, "MAX_STEPS", 10)
    monkeypatch.setattr(core, "MAX_RETRIES_PER_STEP", 1)

    def fake_call_llm(client, model, history):
        return '{"action":"command","name":"ls","parameters":{"path":"."}}'

    monkeypatch.setattr(core, "call_llm", fake_call_llm)

    class LSModule:
        COMMAND_NAME = "ls"

        @staticmethod
        def execute(parameters):
            return "ok"

    history = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    out = core.run_react_loop(DummyClient([]), {"model": "x"}, history, {"ls": LSModule})
    assert "loop detected" in out


def test_logging_jsonl_structure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "agent.log"
        core.init_logger(log_path)
        core.log_jsonl({"step": 1, "action": "ls", "parameters": {"path": "."}, "result": "ok", "error": None, "duration_ms": 5}, log_path)
        line = log_path.read_text(encoding="utf-8").strip()
        assert line
        import json

        obj = json.loads(line)
        assert "timestamp" in obj
        assert obj["step"] == 1
        assert obj["action"] == "ls"
        assert isinstance(obj["parameters"], dict)
