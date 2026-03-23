import argparse
import os
import sys

import yaml


def parse_args():
    parser = argparse.ArgumentParser(description="Lightweight ReAct JSON agent")
    parser.add_argument("--agent", required=True, help="agent config name (agents/<name>.yaml)")
    parser.add_argument("--prompt", required=True, help="initial user prompt / task")
    parser.add_argument("--model", default=None, help="override model name")
    parser.add_argument("--provider", default=None, choices=["openai", "claude"], help="LLM provider override")
    parser.add_argument("--provider-override", default=None, choices=["openai", "claude"], help="force provider for all agents (overrides CLI and config)")
    parser.add_argument("--depth", type=int, default=0, help="current hierarchy depth (internal)")
    parser.add_argument("--log-path", default=None, help="internal: exact log file path (for child agents)")
    parser.add_argument("--verbose-log-path", default=None, help="internal: shared verbose output log path (for child agents)")
    parser.add_argument("--verbose-log", action="store_true", help="duplicate verbose output to a shared log file")
    parser.add_argument("-v", "--verbose", action="store_true", help="show detailed progress")
    parser.add_argument("--startup-observe", action="append", default=[], help="command to run at startup and inject as Observation (repeatable)")
    parser.add_argument("--process-all-json-blocks", action="store_true", help="process all valid JSON action blocks from a model response instead of only the first")
    return parser.parse_args()


def load_runtime_config(args, script_dir: str):
    config_path = os.path.join(script_dir, "agents", f"{args.agent}.yaml")
    if not os.path.isfile(config_path):
        print(f"Error: config not found → {config_path}")
        sys.exit(1)

    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading config: {e}")
        sys.exit(1)

    model = args.model or config.get("model")
    if not model:
        print("Error: model must be set in config or via --model")
        sys.exit(1)

    provider = (args.provider_override or args.provider or config.get("provider") or "openai").lower()
    if provider not in {"openai", "claude"}:
        print("Error: provider must be 'openai' or 'claude'")
        sys.exit(1)

    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable is required for provider=openai")
        sys.exit(1)
    if provider == "claude" and not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable is required for provider=claude")
        sys.exit(1)

    return config, model, provider
