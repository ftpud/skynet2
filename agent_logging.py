import json
from datetime import datetime


def append_jsonl(log_path: str, entry: dict):
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)
            f.write("\n")
    except Exception:
        pass


def log_step(log_path: str, agent_name: str, provider: str, model: str, depth: int, step: int, action: str, parameters: dict, result: str, step_tokens_in: int = 0, step_tokens_out: int = 0):
    entry = {
        "type": "step",
        "step": step,
        "action": action,
        "parameters": parameters,
        "result": result[:500] + "…" if len(result) > 500 else result,
        "timestamp": datetime.now().isoformat(),
        "agent": agent_name,
        "provider": provider,
        "model": model,
        "depth": depth,
        "tokens": {
            "inbound": int(step_tokens_in or 0),
            "outbound": int(step_tokens_out or 0),
            "total": int(step_tokens_in or 0) + int(step_tokens_out or 0),
        },
    }
    append_jsonl(log_path, entry)


def log_session_start(log_path: str, agent_name: str, provider: str, model: str, depth: int):
    entry = {
        "type": "session_start",
        "agent": agent_name,
        "provider": provider,
        "model": model,
        "depth": depth,
        "timestamp": datetime.now().isoformat(),
    }
    append_jsonl(log_path, entry)


def log_session_end(log_path: str, agent_name: str, provider: str, model: str, session_tokens_in: int, session_tokens_out: int):
    total = session_tokens_in + session_tokens_out
    entry = {
        "type": "session_end",
        "agent": agent_name,
        "provider": provider,
        "model": model,
        "tokens": {
            "inbound": session_tokens_in,
            "outbound": session_tokens_out,
            "total": total,
        },
        "timestamp": datetime.now().isoformat(),
    }
    append_jsonl(log_path, entry)
