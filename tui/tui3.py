#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.tree import Tree
from rich import box

LOG_DIR = Path("./logs")
REFRESH_SECONDS = 2
LOCAL_TZ = datetime.now().astimezone().tzinfo
START_TIME = datetime.now().astimezone(LOCAL_TZ).replace(second=0, microsecond=0)
SELF_PATH = Path(__file__).resolve()


def parse_ts(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
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
    inp = tokens_dict.get("input")
    if inp is None:
        inp = tokens_dict.get("inbound")
    out = tokens_dict.get("output")
    if out is None:
        out = tokens_dict.get("outbound")
    total = tokens_dict.get("total")

    usage = record.get("usage") or record.get("response", {}).get("usage") or {}

    if inp is None:
        inp = usage.get("input_tokens")
    if inp is None:
        inp = usage.get("prompt_tokens")
    if inp is None:
        inp = 0

    if out is None:
        out = usage.get("output_tokens")
    if out is None:
        out = usage.get("completion_tokens")
    if out is None:
        out = 0

    try:
        inp = int(inp)
    except Exception:
        inp = 0

    try:
        out = int(out)
    except Exception:
        out = 0

    if total is not None:
        try:
            total = int(total)
        except Exception:
            total = inp + out
    else:
        total = usage.get("total_tokens")
        if total is None:
            total = inp + out
        try:
            total = int(total)
        except Exception:
            total = inp + out

    ts = (
        parse_ts(record.get("timestamp"))
        or parse_ts(record.get("created_at"))
        or parse_ts(record.get("time"))
        or parse_ts(record.get("ts"))
    )

    return ts, model, agent, inp, out, total


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


def load_data(log_dir: Path, now_local: datetime):
    end_local = now_local.replace(second=0, microsecond=0)
    if end_local < START_TIME:
        end_local = START_TIME

    total_minutes = int((end_local - START_TIME).total_seconds() // 60) + 1
    buckets_local = [START_TIME + timedelta(minutes=i) for i in range(total_minutes)]
    bucket_index = {b: i for i, b in enumerate(buckets_local)}

    per_model = defaultdict(lambda: [0] * total_minutes)
    per_model_input = defaultdict(int)
    per_model_output = defaultdict(int)
    per_model_total = defaultdict(int)
    sessions = []

    if not log_dir.exists():
        return buckets_local, per_model, per_model_input, per_model_output, per_model_total, sessions

    for path in sorted(log_dir.rglob("*.jsonl")):
        starts = []
        ends = []
        steps = []
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

                    ts, model, agent, inp, out, total = extract_usage(rec)
                    if total:
                        per_model_total[model] += total
                    if inp:
                        per_model_input[model] += inp
                    if out:
                        per_model_output[model] += out
                    if ts is not None:
                        ts_local = ts.astimezone(LOCAL_TZ)
                        if START_TIME <= ts_local < (end_local + timedelta(minutes=1)):
                            minute_local = ts_local.replace(second=0, microsecond=0)
                            idx = bucket_index.get(minute_local)
                            if idx is not None:
                                per_model[model][idx] += total

                    rtype = rec.get("type")
                    if rtype == "session_start":
                        starts.append(rec)
                    elif rtype == "session_end":
                        ends.append(rec)
                    elif rtype == "step":
                        steps.append(rec)
        except Exception:
            continue

        if starts:
            start = starts[0]
            end = ends[-1] if ends else None
            start_ts = parse_ts(start.get("timestamp"))
            end_ts = parse_ts(end.get("timestamp")) if end else None
            sessions.append({
                "file": path.name,
                "agent": start.get("agent", "unknown"),
                "model": start.get("model", "unknown"),
                "depth": int(start.get("depth", 0) or 0),
                "start_ts": start_ts,
                "end_ts": end_ts,
                "steps": steps,
                "last_ts": end_ts or (parse_ts(steps[-1].get("timestamp")) if steps else start_ts),
            })

    sessions.sort(
        key=lambda s: s.get("last_ts") or s.get("start_ts") or datetime.min.replace(tzinfo=LOCAL_TZ),
        reverse=True,
    )
    return buckets_local, per_model, per_model_input, per_model_output, per_model_total, sessions


def build_tree_panel(sessions):
    root = Tree("[bold]Current/last execution tree[/bold]")
    if not sessions:
        root.add("(no sessions)")
        return Panel(root, title="Work tree", box=box.SIMPLE)

    file_to_session = {s["file"]: s for s in sessions}

    roots = [s for s in sessions if int(s.get("depth", 0)) == 0]

    ordered_roots = sorted(
        roots,
        key=lambda s: s.get("last_ts") or s.get("start_ts") or datetime.min.replace(tzinfo=LOCAL_TZ),
        reverse=True,
    )

    def make_label(s):
        depth = int(s.get("depth", 0) or 0)
        status = "[green]done[/green]" if s.get("end_ts") else "[yellow]running[/yellow]"
        return f"{s['agent']} d={depth} {status}"

    def add_steps_and_subcalls(tree_node, sess, file_to_session, path_stack):
        sess_file = sess.get("file")
        if sess_file in path_stack:
            tree_node.add("[red]cycle detected[/red]")
            return

        next_stack = set(path_stack)
        next_stack.add(sess_file)

        for st in sess.get("steps", []):
            step_no = st.get("step", "?")
            action = st.get("action", "?")
            if action == "run_agent":
                params = st.get("parameters") or {}
                child_agent = params.get("agent", "?")
                step_label = f"step {step_no}: run_agent → {child_agent}"
                step_node = tree_node.add(step_label)

                result_str = str(st.get("result") or "")
                match = re.search(r"log file\s+→\s+([^\n]+)", result_str)
                child_sess = None
                if match:
                    child_path = match.group(1).strip()
                    child_file = Path(child_path).name
                    child_sess = file_to_session.get(child_file)

                if child_sess:
                    child_label = make_label(child_sess)
                    child_node = step_node.add(child_label)
                    add_steps_and_subcalls(child_node, child_sess, file_to_session, next_stack)
            else:
                tree_node.add(f"step {step_no}: {action}")

    if not ordered_roots:
        root.add("(no root sessions)")
    else:
        for root_sess in ordered_roots:
            label = make_label(root_sess)
            sess_node = root.add(label)
            add_steps_and_subcalls(sess_node, root_sess, file_to_session, set())

    return Panel(root, title="Work tree", box=box.SIMPLE)


def build_tokens_panel(sessions):
    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("Agent", no_wrap=True, style="cyan")
    table.add_column("Status", no_wrap=True)
    table.add_column("Steps", justify="right")

    if not sessions:
        table.add_row("(no data)", "", "0")
    else:
        ordered = sorted(
            sessions,
            key=lambda s: s.get("last_ts") or s.get("start_ts") or datetime.min.replace(tzinfo=LOCAL_TZ),
            reverse=True,
        )
        for s in ordered[:8]:
            status = "running" if s.get("end_ts") is None else "done"
            table.add_row(s["agent"], status, str(len(s.get("steps", []))))

    return Panel(table, title="Current/Recent execution", box=box.SIMPLE)


def build_chart_panel(per_model_input, per_model_output, per_model_total):
    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("Model", style="cyan", no_wrap=True)
    table.add_column("In", justify="right", style="green")
    table.add_column("Out", justify="right", style="yellow")
    table.add_column("Total", justify="right", style="magenta")

    models = set(per_model_total.keys()) | set(per_model_input.keys()) | set(per_model_output.keys())
    if not models:
        table.add_row("(no data)", "0", "0", "0")
    else:
        rows = []
        for model in models:
            inp = int(per_model_input.get(model, 0) or 0)
            out = int(per_model_output.get(model, 0) or 0)
            total = int(per_model_total.get(model, 0) or 0)
            if total <= 0:
                total = inp + out
            elif inp + out > total:
                total = inp + out
            rows.append((model, inp, out, total))
        for model, inp, out, total in sorted(rows, key=lambda r: r[3], reverse=True):
            table.add_row(model, f"{inp:,}", f"{out:,}", f"{total:,}")

    return Panel(table, title="Token totals by model", box=box.SIMPLE)


def build_model_totals_panel(per_model_input, per_model_output):
    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("Model", style="cyan", no_wrap=True)
    table.add_column("Input", justify="right", style="green")
    table.add_column("Output", justify="right", style="yellow")
    table.add_column("Total", justify="right", style="magenta")

    models = set(per_model_input.keys()) | set(per_model_output.keys())
    if not models:
        table.add_row("(no data)", "0", "0", "0")
    else:
        rows = []
        for model in models:
            inp = int(per_model_input.get(model, 0) or 0)
            out = int(per_model_output.get(model, 0) or 0)
            total = inp + out
            rows.append((model, inp, out, total))
        for model, inp, out, total in sorted(rows, key=lambda r: r[3], reverse=True):
            table.add_row(model, f"{inp:,}", f"{out:,}", f"{total:,}")

    return Panel(table, title="Token totals by model (input/output)", box=box.SIMPLE)


def build_total_usage_panel(buckets, per_model):
    total_vals = [0] * len(buckets)
    for vals in per_model.values():
        for i, v in enumerate(vals):
            total_vals[i] += v

    chart = spark(total_vals, width=80)
    total_tokens = sum(total_vals)

    minute_labels = [b.astimezone(LOCAL_TZ).strftime("%H:%M") for b in buckets]
    if len(minute_labels) > 8:
        shown = minute_labels[:4] + ["..."] + minute_labels[-4:]
    else:
        shown = minute_labels

    body = f"\nTotal tokens: {total_tokens:,}\n{chart}"
    subtitle = f"per-minute total tokens (all models) | {' '.join(shown)}"
    return Panel(body, title="Per-minute usage (all models)", subtitle=subtitle, box=box.SIMPLE)


def build_view():
    now_local = datetime.now().astimezone(LOCAL_TZ)
    buckets, per_model, per_model_input, per_model_output, per_model_total, sessions = load_data(LOG_DIR, now_local)

    layout = Layout()
    layout.split_column(
        Layout(build_tree_panel(sessions), ratio=3),
        Layout(build_tokens_panel(sessions), ratio=1),
        Layout(build_chart_panel(per_model_input, per_model_output, per_model_total), ratio=1),
        #Layout(build_model_totals_panel(per_model_input, per_model_output), ratio=2),
        Layout(build_total_usage_panel(buckets, per_model), ratio=1),
    )
    return layout


def _self_signature(path: Path):
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except Exception:
        return None


def _restart_self():
    os.execv(sys.executable, [sys.executable] + sys.argv)


def main():
    console = Console()
    sig = _self_signature(SELF_PATH)
    with Live(build_view(), console=console, refresh_per_second=4, screen=True) as live:
        import time
        while True:
            time.sleep(REFRESH_SECONDS)
            new_sig = _self_signature(SELF_PATH)
            if new_sig is not None and sig is not None and new_sig != sig:
                _restart_self()
            live.update(build_view())


if __name__ == "__main__":
    main()
