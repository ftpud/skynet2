import importlib.util
import os

import yaml


def load_commands(base_dir: str) -> tuple[dict, dict]:
    command_info: dict = {}
    command_handlers: dict = {}

    commands_dir = os.path.join(base_dir, "commands")
    os.makedirs(commands_dir, exist_ok=True)

    for filename in sorted(os.listdir(commands_dir)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue

        path = os.path.join(commands_dir, filename)
        module_name = f"commands.{filename[:-3]}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            name = getattr(module, "COMMAND_NAME", None)
            description = getattr(module, "DESCRIPTION", None)
            usage_example = getattr(module, "USAGE_EXAMPLE", None)
            handler = getattr(module, "execute", None)
            if not callable(handler):
                handler = getattr(module, "run", None)

            if not name or not isinstance(name, str):
                continue
            if not callable(handler):
                continue

            command_info[name] = {
                "description": description or "No description provided.",
                "usage_example": usage_example or "{}",
            }
            command_handlers[name] = handler
        except Exception:
            continue

    return command_info, command_handlers


def load_agents(base_dir: str) -> dict:
    agent_info: dict = {}

    agents_dir = os.path.join(base_dir, "agents")
    os.makedirs(agents_dir, exist_ok=True)

    for filename in sorted(os.listdir(agents_dir)):
        if not (filename.endswith(".yaml") or filename.endswith(".yml")):
            continue

        path = os.path.join(agents_dir, filename)
        try:
            with open(path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            name = os.path.splitext(filename)[0]
            description = cfg.get("description") or cfg.get("role") or "No description provided."
            agent_info[name] = {
                "description": description,
            }
        except Exception:
            continue

    return agent_info
