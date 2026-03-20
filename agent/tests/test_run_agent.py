from __future__ import annotations

import os

from agent.commands import run_agent


class Completed:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_run_agent_depth_limit(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_DEPTH", "3")
    monkeypatch.setenv("MAX_AGENT_DEPTH", "3")
    out = run_agent.execute({"config": "agent/config.yaml", "prompt": "x"})
    assert out.startswith("ERROR:")
    assert "depth" in out


def test_run_agent_children_limit(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_DEPTH", "0")
    monkeypatch.setenv("AGENT_CHILD_COUNT", "5")
    monkeypatch.setenv("MAX_CHILD_AGENTS", "5")
    out = run_agent.execute({"config": "agent/config.yaml", "prompt": "x"})
    assert out.startswith("ERROR:")
    assert "child" in out


def test_run_agent_extracts_final_answer(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_DEPTH", "0")
    monkeypatch.setenv("AGENT_CHILD_COUNT", "0")
    monkeypatch.setenv("MAX_AGENT_DEPTH", "3")
    monkeypatch.setenv("MAX_CHILD_AGENTS", "5")
    monkeypatch.setenv("CHILD_AGENT_TIMEOUT", "5")

    def fake_run(*args, **kwargs):
        return Completed(stdout="noise\nFINAL_ANSWER: done\n")

    monkeypatch.setattr(run_agent.subprocess, "run", fake_run)
    out = run_agent.execute({"config": "agent/config.yaml", "prompt": "x"})
    assert out == "FINAL_ANSWER: done"
