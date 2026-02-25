#!/usr/bin/env python3
"""Persistent research state manager.

Maintains a JSON state file that survives context compression and session
restarts. Claude interacts with it via CLI commands.

Usage (via Bash):
    python -m research_agent.state init --progress progress.md
    python -m research_agent.state init --goal "improve dice above 0.92"
    python -m research_agent.state read
    python -m research_agent.state read --field best
    python -m research_agent.state set-baseline --checkpoint "path" --metrics '{"test_3d_dice": 0.90}'
    python -m research_agent.state add-iteration \
        --hypothesis "Increasing SPD rank" \
        --change "spd_rank 4->8" \
        --checkpoint "checkpoints/exp1" \
        --metric-name test_3d_dice --metric-value 0.91 \
        --feedback "marginal gain"
    python -m research_agent.state update-progress --status "Trying token-wise FiLM"
    python -m research_agent.state report
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_STATE_FILE = "state.json"
DEFAULT_PROGRESS_FILE = "progress.md"
PROGRESS_SENTINEL = "<!-- AGENT PROGRESS BELOW — auto-updated, do not edit below this line -->"


def _state_path() -> Path:
    """Resolve state file path. Uses STATE_FILE env var or default."""
    return Path(os.environ.get("RESEARCH_STATE_FILE", DEFAULT_STATE_FILE))


def _load() -> dict:
    """Load state from disk. Returns empty dict if file doesn't exist."""
    p = _state_path()
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save(state: dict) -> None:
    """Save state to disk with pretty formatting."""
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _progress_path() -> Path:
    """Resolve progress.md path. Uses RESEARCH_PROGRESS_FILE env var or default."""
    return Path(os.environ.get("RESEARCH_PROGRESS_FILE", DEFAULT_PROGRESS_FILE))


def _read_progress_goal(progress_file: str | None) -> str:
    """Read the user's goal section from progress.md (everything above the sentinel)."""
    p = Path(progress_file) if progress_file else _progress_path()
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8")
    # Everything above the sentinel is the user's goal
    if PROGRESS_SENTINEL in text:
        return text.split(PROGRESS_SENTINEL)[0].strip()
    return text.strip()


def _write_progress(state: dict, status_note: str = "") -> None:
    """Rewrite progress.md: preserve user goal above sentinel, write tracking below."""
    p = _progress_path()

    # Read existing content to preserve user's goal section
    user_section = ""
    if p.exists():
        text = p.read_text(encoding="utf-8")
        if PROGRESS_SENTINEL in text:
            user_section = text.split(PROGRESS_SENTINEL)[0].rstrip()
        else:
            user_section = text.rstrip()
    else:
        user_section = f"# Research Goal\n\n{state.get('goal', 'N/A')}"

    # Build tracking section
    lines = []
    lines.append("")
    lines.append(PROGRESS_SENTINEL)
    lines.append("")

    # Status bar
    n_iters = len(state.get("iterations", []))
    primary = state.get("primary_metric", "")
    bl = state.get("baseline")
    best = state.get("best")

    bl_val = bl["metrics"].get(primary, "N/A") if bl and bl.get("metrics") else "N/A"
    best_val = "N/A"
    best_iter = ""
    if best and best.get("metrics"):
        best_val = best["metrics"].get(primary, "N/A")
        best_iter = f" (iter {best.get('iteration', '?')})"

    lines.append(f"## Status")
    lines.append("")
    lines.append(f"| | |")
    lines.append(f"|---|---|")
    lines.append(f"| **Primary metric** | `{primary}` |")
    lines.append(f"| **Baseline** | {bl_val} |")
    lines.append(f"| **Best** | {best_val}{best_iter} |")
    lines.append(f"| **Iterations** | {n_iters} |")
    lines.append(f"| **Started** | {state.get('created_at', 'N/A')} |")
    lines.append("")

    if status_note:
        lines.append(f"> **Current direction:** {status_note}")
        lines.append("")

    # Baseline details
    if bl:
        lines.append(f"## Baseline")
        lines.append(f"- Checkpoint: `{bl.get('checkpoint', 'N/A')}`")
        for k, v in bl.get("metrics", {}).items():
            lines.append(f"- {k}: **{v}**")
        lines.append("")

    # Iteration log
    iters = state.get("iterations", [])
    if iters:
        lines.append(f"## Iteration Log")
        lines.append("")

        # Compute delta vs baseline for primary metric
        header = f"| # | Change | {primary} | vs baseline | Feedback |"
        sep = f"|---|--------|{'---'}|------------|----------|"
        lines.append(header)
        lines.append(sep)

        for it in iters:
            m_val = it.get("metrics", {}).get(primary, None)
            m_str = f"{m_val}" if m_val is not None else "N/A"

            delta_str = ""
            if m_val is not None and bl_val != "N/A":
                try:
                    delta = float(m_val) - float(bl_val)
                    sign = "+" if delta >= 0 else ""
                    delta_str = f"{sign}{delta:.4f}"
                except (ValueError, TypeError):
                    delta_str = "N/A"
            else:
                delta_str = "N/A"

            chg = it.get("change_summary", "")[:50]
            fb = it.get("feedback", "")[:50]
            lines.append(f"| {it['id']} | {chg} | {m_str} | {delta_str} | {fb} |")
        lines.append("")

    # Detailed iteration notes (most recent 3)
    recent = iters[-3:] if len(iters) > 3 else iters
    if recent:
        lines.append("## Recent Iterations (detail)")
        lines.append("")
        for it in reversed(recent):
            lines.append(f"### Iteration {it['id']} — {it.get('timestamp', '')}")
            lines.append(f"- **Hypothesis:** {it.get('hypothesis', 'N/A')}")
            lines.append(f"- **Change:** {it.get('change_summary', 'N/A')}")
            if it.get("papers_referenced"):
                lines.append(f"- **Papers:** {', '.join(it['papers_referenced'])}")
            lines.append(f"- **Checkpoint:** `{it.get('checkpoint', 'N/A')}`")
            lines.append(f"- **Metrics:** {json.dumps(it.get('metrics', {}))}")
            lines.append(f"- **Feedback:** {it.get('feedback', 'N/A')}")
            lines.append("")

    lines.append(f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("")

    # Write combined file
    output = user_section + "\n" + "\n".join(lines)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(output, encoding="utf-8")


def cmd_init(args) -> None:
    """Initialize a new research session.

    If --progress is given, reads the goal from the user's progress.md file.
    Otherwise uses --goal.
    """
    goal = args.goal or ""

    # Read goal from progress.md if specified
    if args.progress:
        goal_from_file = _read_progress_goal(args.progress)
        if goal_from_file:
            goal = goal_from_file
        elif not goal:
            print('{"error": "No goal found in progress.md and no --goal given."}')
            sys.exit(1)

    if not goal:
        print('{"error": "Provide --goal or --progress with a progress.md file."}')
        sys.exit(1)

    state = {
        "goal": goal,
        "project_dir": args.project_dir or os.getcwd(),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "primary_metric": args.metric or "test_3d_dice",
        "baseline": None,
        "best": None,
        "iterations": [],
    }
    _save(state)
    _write_progress(state)
    print(json.dumps(state, indent=2))


def cmd_read(args) -> None:
    """Print current state (full or specific field)."""
    state = _load()
    if not state:
        print('{"error": "No state file found. Run init first."}')
        sys.exit(1)
    if args.field:
        val = state.get(args.field)
        if val is None:
            print(f'{{"error": "Field \'{args.field}\' not found"}}')
            sys.exit(1)
        print(json.dumps(val, indent=2) if isinstance(val, (dict, list)) else str(val))
    else:
        print(json.dumps(state, indent=2))


def cmd_set_baseline(args) -> None:
    """Record baseline metrics."""
    state = _load()
    if not state:
        print('{"error": "No state file found. Run init first."}')
        sys.exit(1)

    metrics = json.loads(args.metrics) if args.metrics else {}
    state["baseline"] = {
        "checkpoint": args.checkpoint,
        "metrics": metrics,
    }
    _save(state)
    _write_progress(state)
    print(json.dumps(state["baseline"], indent=2))


def cmd_add_iteration(args) -> None:
    """Record a completed iteration."""
    state = _load()
    if not state:
        print('{"error": "No state file found. Run init first."}')
        sys.exit(1)

    iteration_id = len(state["iterations"]) + 1

    # Build metrics dict from repeated --metric-name / --metric-value pairs
    metrics = {}
    if args.metric_name and args.metric_value:
        for name, value in zip(args.metric_name, args.metric_value):
            metrics[name] = float(value)

    # Parse extra metrics JSON if provided
    if args.extra_metrics:
        metrics.update(json.loads(args.extra_metrics))

    iteration = {
        "id": iteration_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hypothesis": args.hypothesis or "",
        "change_summary": args.change or "",
        "papers_referenced": args.papers or [],
        "checkpoint": args.checkpoint or "",
        "metrics": metrics,
        "feedback": args.feedback or "",
    }
    state["iterations"].append(iteration)

    # Update best if primary metric improved
    primary = state.get("primary_metric", "")
    if primary and primary in metrics:
        current_val = metrics[primary]
        prev_best_val = None
        if state.get("best") and state["best"].get("metrics"):
            prev_best_val = state["best"]["metrics"].get(primary)

        if prev_best_val is None or current_val > prev_best_val:
            state["best"] = {
                "iteration": iteration_id,
                "metrics": metrics,
                "experiment": args.change or f"iteration_{iteration_id}",
            }

    _save(state)
    _write_progress(state, status_note=args.feedback or "")
    print(json.dumps(iteration, indent=2))


def cmd_update_progress(args) -> None:
    """Manually update progress.md with current state and optional status note."""
    state = _load()
    if not state:
        print('{"error": "No state file found. Run init first."}')
        sys.exit(1)

    _write_progress(state, status_note=args.status or "")
    p = _progress_path()
    print(f"Updated {p}")


def cmd_report(args) -> None:
    """Export a markdown summary report."""
    state = _load()
    if not state:
        print("No state file found. Run init first.")
        sys.exit(1)

    lines = []
    lines.append(f"# Research Report")
    lines.append(f"")
    lines.append(f"**Goal:** {state.get('goal', 'N/A')}")
    lines.append(f"**Started:** {state.get('created_at', 'N/A')}")
    lines.append(f"**Primary metric:** `{state.get('primary_metric', 'N/A')}`")
    lines.append(f"**Iterations completed:** {len(state.get('iterations', []))}")
    lines.append(f"")

    # Baseline
    bl = state.get("baseline")
    if bl:
        lines.append(f"## Baseline")
        lines.append(f"- Checkpoint: `{bl.get('checkpoint', 'N/A')}`")
        for k, v in bl.get("metrics", {}).items():
            lines.append(f"- {k}: **{v}**")
        lines.append(f"")

    # Best
    best = state.get("best")
    if best:
        lines.append(f"## Best Result")
        lines.append(f"- Iteration: {best.get('iteration', 'N/A')}")
        lines.append(f"- Experiment: {best.get('experiment', 'N/A')}")
        for k, v in best.get("metrics", {}).items():
            lines.append(f"- {k}: **{v}**")
        lines.append(f"")

    # Iteration table
    iters = state.get("iterations", [])
    if iters:
        lines.append(f"## Iterations")
        lines.append(f"")
        primary = state.get("primary_metric", "")
        lines.append(f"| # | Hypothesis | Change | {primary} | Feedback |")
        lines.append(f"|---|-----------|--------|{'---' if primary else '---'}|----------|")
        for it in iters:
            m_val = it.get("metrics", {}).get(primary, "N/A")
            hyp = it.get("hypothesis", "")[:60]
            chg = it.get("change_summary", "")[:40]
            fb = it.get("feedback", "")[:40]
            lines.append(f"| {it['id']} | {hyp} | {chg} | {m_val} | {fb} |")
        lines.append(f"")

    report = "\n".join(lines)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report written to {args.output}")
    else:
        print(report)


def main():
    parser = argparse.ArgumentParser(prog="research_agent.state",
                                     description="Research session state manager")
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Initialize a new research session")
    p_init.add_argument("--goal", default=None, help="Research goal (or read from --progress)")
    p_init.add_argument("--progress", default=None, help="Path to user's progress.md with goal")
    p_init.add_argument("--project-dir", default=None, help="Project root (default: cwd)")
    p_init.add_argument("--metric", default="test_3d_dice", help="Primary metric name")
    p_init.set_defaults(func=cmd_init)

    # read
    p_read = sub.add_parser("read", help="Print current state")
    p_read.add_argument("--field", default=None, help="Specific field to read")
    p_read.set_defaults(func=cmd_read)

    # set-baseline
    p_bl = sub.add_parser("set-baseline", help="Record baseline metrics")
    p_bl.add_argument("--checkpoint", required=True, help="Baseline checkpoint path")
    p_bl.add_argument("--metrics", default=None, help="JSON dict of metrics")
    p_bl.set_defaults(func=cmd_set_baseline)

    # add-iteration
    p_it = sub.add_parser("add-iteration", help="Record a completed iteration")
    p_it.add_argument("--hypothesis", help="What you expected")
    p_it.add_argument("--change", help="Summary of what was changed")
    p_it.add_argument("--checkpoint", help="Checkpoint directory path")
    p_it.add_argument("--metric-name", action="append", help="Metric name (repeatable)")
    p_it.add_argument("--metric-value", action="append", help="Metric value (repeatable)")
    p_it.add_argument("--extra-metrics", default=None, help="JSON dict of additional metrics")
    p_it.add_argument("--papers", nargs="*", default=[], help="Referenced papers")
    p_it.add_argument("--feedback", help="User/agent feedback")
    p_it.set_defaults(func=cmd_add_iteration)

    # update-progress
    p_prog = sub.add_parser("update-progress", help="Update progress.md with current state")
    p_prog.add_argument("--status", default=None, help="Current direction / status note")
    p_prog.set_defaults(func=cmd_update_progress)

    # report
    p_rpt = sub.add_parser("report", help="Export markdown summary")
    p_rpt.add_argument("--output", default=None, help="Output file (default: stdout)")
    p_rpt.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
