#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich import box

LOG_DIR = Path("./logs")
WINDOW_HOURS = 12
REFRESH_SECONDS = 2
LOCAL_TZ = datetime.now().astimezone().tzinfo


def parse_ts(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # assume epoch seconds
        try:
            return datetime.fromtimestamp(value).astimezone()
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.astimezone()
            else:
                dt = dt.astimezone()
            return dt
        except Exception:
            return None
    return None


def extract_usage(record):
    model = (
        record.get("model")
        or record.get("response", {}).get("model")
        or record.get("meta", {}).get("model")
        or "unknown"
    )

    agent = (
        record.get("agent")
        or record.get("agent_name")
        or record.get("meta", {}).get("agent")
        or record.get("meta", {}).get("agent_name")
        or record.get("response", {}).get("agent")
        or "unknown"
    )

    tokens_dict = record.get("tokens") or {}
    total = tokens_dict.get("total")
    if total is not None:
        try:
            total = int(total)
        except Exception:
            total = 0
    else:
        usage = record.get("usage") or record.get("response", {}).get("usage") or {}
        total = usage.get("total_tokens")
        if total is None:
            inp = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
            out = usage.get("output_tokens") or usage.get("completion_tokens") or 0
            total = inp + out
        try:
            total = int(total)
        except Exception:
            total = 0

    ts = (
        parse_ts(record.get("timestamp"))
        or parse_ts(record.get("created_at"))
        or parse_ts(record.get("time"))
        or parse_ts(record.get("ts"))
    )

    return ts, model, agent, total


def load_aggregates(log_dir: Path, now_local: datetime):
    end_local = now_local.replace(minute=0, second=0, microsecond=0)
    start_local = end_local - timedelta(hours=WINDOW_HOURS - 1)

    buckets_local = [start_local + timedelta(hours=i) for i in range(WINDOW_HOURS)]
    bucket_index = {b: i for i, b in enumerate(buckets_local)}

    per_model = defaultdict(lambda: [0] * WINDOW_HOURS)
    per_agent = defaultdict(lambda: [0] * WINDOW_HOURS)

    if not log_dir.exists():
        return buckets_local, per_model, per_agent

    log_files = sorted(log_dir.rglob("*.jsonl")) + sorted(log_dir.rglob("*.log"))
    for path in log_files:
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue

                    ts, model, agent, total = extract_usage(rec)
                    if ts is None:
                        continue
                    ts_local = ts.astimezone(LOCAL_TZ)

                    if ts_local < start_local or ts_local >= (end_local + timedelta(hours=1)):
                        continue

                    hour_local = ts_local.replace(minute=0, second=0, microsecond=0)
                    idx = bucket_index.get(hour_local)
                    if idx is None:
                        continue
                    per_model[model][idx] += total
                    per_agent[agent][idx] += total
        except Exception:
            continue

    return buckets_local, per_model, per_agent


def spark(values, width=24):
    bars = "▁▂▃▄▅▆▇█"
    if not values:
        return ""
    vmax = max(values) if max(values) > 0 else 1
    if len(values) <= width:
        sampled = values
    else:
        step = len(values) / width
        sampled = []
        for i in range(width):
            a = int(i * step)
            b = int((i + 1) * step)
            chunk = values[a:max(a + 1, b)]
            sampled.append(sum(chunk))
    out = []
    for v in sampled:
        idx = int((v / vmax) * (len(bars) - 1))
        out.append(bars[idx])
    return "".join(out)


def build_view():
    now_local = datetime.now().astimezone(LOCAL_TZ)
    buckets, per_model, per_agent = load_aggregates(LOG_DIR, now_local)

    subtitle = f"Local now: {now_local.strftime('%Y-%m-%d %H:%M:%S %Z')} | logs: {LOG_DIR.resolve()}"

    model_table = Table(box=box.SIMPLE_HEAVY)
    model_table.add_column("Model", style="cyan", no_wrap=True)
    model_table.add_column("Total", justify="right", style="magenta")
    model_table.add_column("Hourly bars", style="green")

    if not per_model:
        model_table.add_row("(no data)", "0", "")
    else:
        for model, vals in sorted(per_model.items(), key=lambda kv: sum(kv[1]), reverse=True):
            model_table.add_row(
                model,
                f"{sum(vals):,}",
                spark(vals, width=36),
            )

    agent_table = Table(box=box.SIMPLE_HEAVY)
    agent_table.add_column("Agent", style="cyan", no_wrap=True)
    agent_table.add_column("Total", justify="right", style="magenta")
    agent_table.add_column("Hourly bars", style="green")

    if not per_agent:
        agent_table.add_row("(no data)", "0", "")
    else:
        for agent, vals in sorted(per_agent.items(), key=lambda kv: sum(kv[1]), reverse=True):
            agent_table.add_row(
                agent,
                f"{sum(vals):,}",
                spark(vals, width=36),
            )

    hours = " ".join([b.astimezone(LOCAL_TZ).strftime("%H") for b in buckets])
    footer = Text(f"Hours ({now_local.strftime('%Z')}): {hours}")

    layout = Layout()
    layout.split_column(
        Layout(Panel(model_table, title=f"Token usage per model per hour (last {WINDOW_HOURS}h)", subtitle=subtitle), ratio=4),
        Layout(Panel(agent_table, title=f"Token usage per agent per hour (last {WINDOW_HOURS}h)", subtitle=subtitle), ratio=4),
        Layout(Panel(footer), ratio=1),
    )
    return layout


def main():
    console = Console()
    with Live(build_view(), console=console, refresh_per_second=4, screen=True) as live:
        import time

        while True:
            time.sleep(REFRESH_SECONDS)
            live.update(build_view())


if __name__ == "__main__":
    main()
