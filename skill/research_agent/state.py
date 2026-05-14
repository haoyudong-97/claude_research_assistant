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
    python -m research_agent.state start-iteration --hypothesis "..." --change "..."
    python -m research_agent.state launch-iteration --id 3 --checkpoint "checkpoints/exp3"
    python -m research_agent.state complete-iteration --id 3 --metric-name test_3d_dice --metric-value 0.91
    python -m research_agent.state fail-iteration --id 3 --feedback "OOM error"
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
PROGRESS_SENTINEL = "<!-- AGENT PROGRESS BELOW — auto-updated, do not edit below this line -->"  # legacy, no longer used

# Valid status values and allowed transitions
VALID_STATUSES = {"coding", "running", "completed", "failed"}
TERMINAL_STATUSES = {"completed", "failed"}
VALID_TRANSITIONS = {
    "coding": {"running", "failed"},
    "running": {"completed", "failed"},
}


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
    """Legacy: read goal from progress.md. Kept for backward compat."""
    p = Path(progress_file) if progress_file else _progress_path()
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8")
    if PROGRESS_SENTINEL in text:
        return text.split(PROGRESS_SENTINEL)[0].strip()
    # Take first non-empty line as goal
    for line in text.splitlines():
        line = line.strip().lstrip("# ")
        if line:
            return line
    return ""


def _iter_status(it: dict) -> str:
    """Get iteration status with backward compat for old entries without status."""
    return it.get("status", "completed")


def _status_counts(iters: list[dict]) -> dict[str, int]:
    """Count iterations by status."""
    counts: dict[str, int] = {}
    for it in iters:
        s = _iter_status(it)
        counts[s] = counts.get(s, 0) + 1
    return counts


def _format_status_summary(counts: dict[str, int]) -> str:
    """Format iteration counts for the status table, e.g. '3 completed, 2 active, 1 failed'."""
    parts = []
    completed = counts.get("completed", 0)
    active = counts.get("coding", 0) + counts.get("running", 0)
    failed = counts.get("failed", 0)
    if completed:
        parts.append(f"{completed} completed")
    if active:
        parts.append(f"{active} active")
    if failed:
        parts.append(f"{failed} failed")
    return ", ".join(parts) if parts else "0"


def _hours_ago(timestamp_str: str) -> str:
    """Compute hours since a timestamp string, e.g. '2.1h ago'."""
    try:
        ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - ts
        hours = delta.total_seconds() / 3600
        if hours < 0.1:
            return "just now"
        return f"{hours:.1f}h ago"
    except (ValueError, TypeError):
        return "unknown"


def _find_iteration(state: dict, iteration_id: int) -> dict | None:
    """Find an iteration by ID."""
    for it in state.get("iterations", []):
        if it["id"] == iteration_id:
            return it
    return None


def _validate_transition(current_status: str, new_status: str) -> str | None:
    """Validate a status transition. Returns error message or None if valid."""
    if current_status in TERMINAL_STATUSES:
        return f"Cannot transition from terminal status '{current_status}'"
    allowed = VALID_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        return f"Invalid transition: '{current_status}' -> '{new_status}'. Allowed: {sorted(allowed)}"
    return None


def _update_best(state: dict, iteration: dict) -> bool:
    """Update best tracking if the iteration's primary metric improved.

    Returns True if a new best was set.
    """
    primary = state.get("primary_metric", "")
    metrics = iteration.get("metrics", {})
    if not primary or primary not in metrics:
        return False

    current_val = metrics[primary]
    prev_best_val = None
    if state.get("best") and state["best"].get("metrics"):
        prev_best_val = state["best"]["metrics"].get(primary)

    if prev_best_val is None or current_val > prev_best_val:
        state["best"] = {
            "iteration": iteration["id"],
            "metrics": metrics,
            "experiment": iteration.get("change_summary", f"iteration_{iteration['id']}"),
        }
        return True
    return False


def _status_label(status: str) -> str:
    """Return a display label for non-completed statuses in the iteration log."""
    if status == "running":
        return "running..."
    elif status == "coding":
        return "coding..."
    elif status == "failed":
        return "FAILED"
    return ""


def _write_progress(state: dict, status_note: str = "") -> None:
    """Rewrite progress.md entirely from state.json.

    This file serves as the research memory — read it before every new
    iteration to understand what has been tried, what worked, what failed,
    and what to try next. It is structured for decision-making, not just
    record-keeping.
    """
    p = _progress_path()

    lines = []
    iters = state.get("iterations", [])
    counts = _status_counts(iters)
    primary = state.get("primary_metric", "")
    bl = state.get("baseline")
    best = state.get("best")

    bl_val = bl["metrics"].get(primary, "N/A") if bl and bl.get("metrics") else "N/A"
    best_val = "N/A"
    best_iter = ""
    if best and best.get("metrics"):
        best_val = best["metrics"].get(primary, "N/A")
        best_iter = f" (iter {best.get('iteration', '?')})"

    lines.append(f"# {state.get('goal', 'Research Progress')}")
    lines.append("")

    # ── Quick Reference (read this first) ─────────────────────────
    lines.append("## Quick Reference")
    lines.append("")
    lines.append(f"- **Goal:** {state.get('goal', 'N/A')}")
    lines.append(f"- **Metric:** `{primary}` — baseline: {bl_val}, best: {best_val}{best_iter}")
    lines.append(f"- **Iterations:** {_format_status_summary(counts)}")
    lines.append("")

    # ── What Worked / What Didn't ─────────────────────────────────
    completed = [it for it in iters if _iter_status(it) == "completed"]
    failed = [it for it in iters if _iter_status(it) == "failed"]

    if completed:
        # Sort by metric value descending
        def _metric_val(it):
            try:
                return float(it.get("metrics", {}).get(primary, 0))
            except (ValueError, TypeError):
                return 0
        ranked = sorted(completed, key=_metric_val, reverse=True)

        # Identify improvements vs regressions relative to baseline
        improved = []
        regressed = []
        for it in ranked:
            m = it.get("metrics", {}).get(primary)
            if m is not None and bl_val != "N/A":
                try:
                    delta = float(m) - float(bl_val)
                    entry = (it, delta)
                    if delta > 0:
                        improved.append(entry)
                    else:
                        regressed.append(entry)
                except (ValueError, TypeError):
                    pass

        lines.append("## What Worked")
        lines.append("")
        if improved:
            for it, delta in improved:
                lines.append(f"- **Iter {it['id']}** (+{delta:.4f}): {it.get('change_summary', 'N/A')}")
                if it.get("feedback"):
                    lines.append(f"  - Insight: {it['feedback']}")
        else:
            lines.append("- Nothing has improved over baseline yet.")
        lines.append("")

        lines.append("## What Didn't Work")
        lines.append("")
        if regressed:
            for it, delta in regressed:
                lines.append(f"- **Iter {it['id']}** ({delta:+.4f}): {it.get('change_summary', 'N/A')}")
                if it.get("feedback"):
                    lines.append(f"  - Insight: {it['feedback']}")
        else:
            lines.append("- No regressions recorded.")
        lines.append("")

    if failed:
        lines.append("## Failed Experiments")
        lines.append("")
        for it in failed:
            lines.append(f"- **Iter {it['id']}**: {it.get('change_summary', 'N/A')}")
            lines.append(f"  - Error: {it.get('feedback', 'unknown')}")
        lines.append("")

    # ── Patterns & Insights ───────────────────────────────────────
    # Auto-generate patterns from completed iterations
    if len(completed) >= 3:
        lines.append("## Patterns")
        lines.append("")
        lines.append("<!-- Auto-generated from iteration results. "
                      "Read these before proposing a new idea. -->")
        lines.append("")

        # Streak detection
        if len(completed) >= 3:
            recent_3 = sorted(completed, key=lambda x: x["id"])[-3:]
            recent_deltas = []
            for it in recent_3:
                m = it.get("metrics", {}).get(primary)
                if m is not None and bl_val != "N/A":
                    try:
                        recent_deltas.append(float(m) - float(bl_val))
                    except (ValueError, TypeError):
                        pass
            if len(recent_deltas) == 3:
                if all(abs(d - recent_deltas[0]) < 0.01 for d in recent_deltas):
                    lines.append("- **PLATEAU detected:** last 3 iterations within 0.01 of each other. "
                                 "Consider a fundamentally different approach or fresh paper search.")
                elif all(d > recent_deltas[i] for i, d in enumerate(recent_deltas[1:], 0)):
                    lines.append("- **Improving trend:** last 3 iterations show consistent gains. "
                                 "Consider pushing this direction further.")
                elif all(d < 0 for d in recent_deltas):
                    lines.append("- **All recent iterations regressed.** "
                                 "Revisit assumptions or try a completely different approach.")
        lines.append("")

    # ── Do Not Repeat ─────────────────────────────────────────────
    all_changes = [it.get("change_summary", "") for it in iters if it.get("change_summary")]
    if all_changes:
        lines.append("## Do Not Repeat")
        lines.append("")
        lines.append("These ideas have already been tried. Do not propose them again:")
        lines.append("")
        for it in iters:
            chg = it.get("change_summary", "")
            if not chg:
                continue
            status = _iter_status(it)
            m = it.get("metrics", {}).get(primary)
            if status == "completed" and m is not None:
                lines.append(f"- ~~{chg}~~ → {primary}: {m}")
            elif status == "failed":
                lines.append(f"- ~~{chg}~~ → FAILED")
            else:
                lines.append(f"- {chg} [{status}]")
        lines.append("")

    # ── Active Experiments ────────────────────────────────────────
    active_iters = [it for it in iters if _iter_status(it) in ("coding", "running")]
    if active_iters:
        lines.append("## Active Experiments")
        lines.append("")
        for it in active_iters:
            status = _iter_status(it)
            label = "coding" if status == "coding" else "training"
            ts = it.get("created_at", it.get("timestamp", ""))
            age = _hours_ago(ts) if ts else "unknown"
            change = it.get("change_summary", "N/A")
            checkpoint = it.get("checkpoint", "")
            ckpt_str = f" (`{checkpoint}`)" if checkpoint else ""
            lines.append(f"- **Iter {it['id']}** [{label}] ({age}) — {change}{ckpt_str}")
        lines.append("")

    # ── Full Iteration Log ────────────────────────────────────────
    if iters:
        lines.append("## Iteration Log")
        lines.append("")
        header = f"| # | Change | {primary} | vs baseline | Learnings |"
        sep = "|---|--------|---|------------|-----------|"
        lines.append(header)
        lines.append(sep)

        for it in iters:
            status = _iter_status(it)
            m_val = it.get("metrics", {}).get(primary, None)

            label = _status_label(status)
            if status == "completed":
                m_str = f"{m_val}" if m_val is not None else "N/A"
            else:
                m_str = label

            delta_str = ""
            if m_val is not None and bl_val != "N/A" and status == "completed":
                try:
                    delta = float(m_val) - float(bl_val)
                    sign = "+" if delta >= 0 else ""
                    delta_str = f"{sign}{delta:.4f}"
                except (ValueError, TypeError):
                    delta_str = "N/A"
            else:
                delta_str = label if status != "completed" else "N/A"

            chg = it.get("change_summary", "")[:60]
            fb = it.get("feedback", "")[:80]
            lines.append(f"| {it['id']} | {chg} | {m_str} | {delta_str} | {fb} |")
        lines.append("")

    # ── Detailed Notes ────────────────────────────────────────────
    if iters:
        lines.append("## Iteration Details")
        lines.append("")
        for it in reversed(iters):
            status = _iter_status(it)
            status_suffix = f" [{status}]" if status != "completed" else ""
            lines.append(f"### Iter {it['id']}{status_suffix} — {it.get('change_summary', 'N/A')}")
            lines.append("")

            # Method
            lines.append("**Method:**")
            method_parts = []
            if it.get("hypothesis"):
                method_parts.append(it["hypothesis"])
            if it.get("change_summary") and it["change_summary"] != it.get("hypothesis", ""):
                method_parts.append(f"Implementation: {it['change_summary']}")
            if it.get("papers_referenced"):
                method_parts.append(f"Based on: {', '.join(it['papers_referenced'])}")
            lines.append(" ".join(method_parts) if method_parts else "N/A")
            lines.append("")

            # Results
            if status == "completed" and it.get("metrics"):
                lines.append("**Results:**")
                for k, v in it["metrics"].items():
                    delta_str = ""
                    if bl and bl.get("metrics") and k in bl["metrics"]:
                        try:
                            d = float(v) - float(bl["metrics"][k])
                            sign = "+" if d >= 0 else ""
                            delta_str = f" ({sign}{d:.4f} vs baseline)"
                        except (ValueError, TypeError):
                            pass
                    lines.append(f"- {k}: **{v}**{delta_str}")
                lines.append("")
            elif status == "failed":
                lines.append(f"**Result:** FAILED — {it.get('feedback', 'unknown error')}")
                lines.append("")
            elif status in ("coding", "running"):
                lines.append(f"**Result:** {_status_label(status)}")
                lines.append("")

            # Learnings
            if it.get("feedback") and status in ("completed", "failed"):
                lines.append("**Learnings:**")
                lines.append(it["feedback"])
                lines.append("")

            lines.append(f"*{it.get('timestamp', '')}* | Checkpoint: `{it.get('checkpoint', 'N/A')}`")
            lines.append("")
            lines.append("---")
            lines.append("")

    lines.append(f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("")

    # Write file
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines), encoding="utf-8")


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
        # Virtual field: next_id returns the next iteration number
        if args.field == "next_id":
            print(len(state.get("iterations", [])) + 1)
            return
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
    """Record a completed iteration (backward-compatible shortcut).

    Creates an iteration and immediately marks it as completed.
    Equivalent to start-iteration + complete-iteration in one step.
    """
    state = _load()
    if not state:
        print('{"error": "No state file found. Run init first."}')
        sys.exit(1)

    iteration_id = len(state["iterations"]) + 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
        "status": "completed",
        "created_at": now,
        "timestamp": now,
        "hypothesis": args.hypothesis or "",
        "change_summary": args.change or "",
        "papers_referenced": args.papers or [],
        "checkpoint": args.checkpoint or "",
        "metrics": metrics,
        "feedback": args.feedback or "",
    }
    state["iterations"].append(iteration)

    _update_best(state, iteration)

    _save(state)
    _write_progress(state, status_note=args.feedback or "")
    print(json.dumps(iteration, indent=2))


def cmd_start_iteration(args) -> None:
    """Create a new iteration in 'coding' status."""
    state = _load()
    if not state:
        print('{"error": "No state file found. Run init first."}')
        sys.exit(1)

    iteration_id = len(state["iterations"]) + 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    iteration = {
        "id": iteration_id,
        "status": "coding",
        "created_at": now,
        "timestamp": now,
        "hypothesis": args.hypothesis or "",
        "change_summary": args.change or "",
        "papers_referenced": args.papers or [],
        "checkpoint": "",
        "metrics": {},
        "feedback": "",
    }
    state["iterations"].append(iteration)

    _save(state)
    _write_progress(state)
    print(json.dumps(iteration, indent=2))


def cmd_launch_iteration(args) -> None:
    """Transition an iteration from 'coding' to 'running'."""
    state = _load()
    if not state:
        print('{"error": "No state file found. Run init first."}')
        sys.exit(1)

    it = _find_iteration(state, args.id)
    if it is None:
        print(f'{{"error": "Iteration {args.id} not found"}}')
        sys.exit(1)

    current = _iter_status(it)
    err = _validate_transition(current, "running")
    if err:
        print(f'{{"error": "{err}"}}')
        sys.exit(1)

    it["status"] = "running"
    it["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if args.checkpoint:
        it["checkpoint"] = args.checkpoint

    _save(state)
    _write_progress(state)
    print(json.dumps(it, indent=2))


def cmd_complete_iteration(args) -> None:
    """Transition an iteration from 'running' to 'completed' with metrics."""
    state = _load()
    if not state:
        print('{"error": "No state file found. Run init first."}')
        sys.exit(1)

    it = _find_iteration(state, args.id)
    if it is None:
        print(f'{{"error": "Iteration {args.id} not found"}}')
        sys.exit(1)

    current = _iter_status(it)
    err = _validate_transition(current, "completed")
    if err:
        print(f'{{"error": "{err}"}}')
        sys.exit(1)

    # Build metrics
    metrics = {}
    if args.metric_name and args.metric_value:
        for name, value in zip(args.metric_name, args.metric_value):
            metrics[name] = float(value)
    if args.extra_metrics:
        metrics.update(json.loads(args.extra_metrics))

    it["status"] = "completed"
    it["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    it["metrics"] = metrics
    if args.feedback:
        it["feedback"] = args.feedback
    if args.checkpoint:
        it["checkpoint"] = args.checkpoint

    _update_best(state, it)

    _save(state)
    _write_progress(state, status_note=args.feedback or "")
    print(json.dumps(it, indent=2))


def cmd_fail_iteration(args) -> None:
    """Transition an iteration from 'coding' or 'running' to 'failed'."""
    state = _load()
    if not state:
        print('{"error": "No state file found. Run init first."}')
        sys.exit(1)

    it = _find_iteration(state, args.id)
    if it is None:
        print(f'{{"error": "Iteration {args.id} not found"}}')
        sys.exit(1)

    current = _iter_status(it)
    err = _validate_transition(current, "failed")
    if err:
        print(f'{{"error": "{err}"}}')
        sys.exit(1)

    it["status"] = "failed"
    it["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if args.feedback:
        it["feedback"] = args.feedback

    _save(state)
    _write_progress(state)
    print(json.dumps(it, indent=2))


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
    lines.append("# Research Report")
    lines.append("")
    lines.append(f"**Goal:** {state.get('goal', 'N/A')}")
    lines.append(f"**Started:** {state.get('created_at', 'N/A')}")
    lines.append(f"**Primary metric:** `{state.get('primary_metric', 'N/A')}`")

    iters = state.get("iterations", [])
    counts = _status_counts(iters)
    lines.append(f"**Iterations:** {_format_status_summary(counts)}")
    lines.append("")

    # Baseline
    bl = state.get("baseline")
    if bl:
        lines.append("## Baseline")
        lines.append(f"- Checkpoint: `{bl.get('checkpoint', 'N/A')}`")
        for k, v in bl.get("metrics", {}).items():
            lines.append(f"- {k}: **{v}**")
        lines.append("")

    # Best
    best = state.get("best")
    if best:
        lines.append("## Best Result")
        lines.append(f"- Iteration: {best.get('iteration', 'N/A')}")
        lines.append(f"- Experiment: {best.get('experiment', 'N/A')}")
        for k, v in best.get("metrics", {}).items():
            lines.append(f"- {k}: **{v}**")
        lines.append("")

    # Iteration table
    if iters:
        lines.append("## Iterations")
        lines.append("")
        primary = state.get("primary_metric", "")
        lines.append(f"| # | Status | Hypothesis | Change | {primary} | Feedback |")
        lines.append(f"|---|--------|-----------|--------|{'---' if primary else '---'}|----------|")
        for it in iters:
            status = _iter_status(it)
            m_val = it.get("metrics", {}).get(primary, "N/A") if status == "completed" else _status_label(status)
            hyp = it.get("hypothesis", "")[:60]
            chg = it.get("change_summary", "")[:40]
            fb = it.get("feedback", "")[:40]
            lines.append(f"| {it['id']} | {status} | {hyp} | {chg} | {m_val} | {fb} |")
        lines.append("")

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
    p_init.add_argument("--metric", default=None, help="Primary metric name")
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

    # add-iteration (backward-compatible: creates + completes atomically)
    p_it = sub.add_parser("add-iteration", help="Record a completed iteration (shortcut)")
    p_it.add_argument("--hypothesis", help="What you expected")
    p_it.add_argument("--change", help="Summary of what was changed")
    p_it.add_argument("--checkpoint", help="Checkpoint directory path")
    p_it.add_argument("--metric-name", action="append", help="Metric name (repeatable)")
    p_it.add_argument("--metric-value", action="append", help="Metric value (repeatable)")
    p_it.add_argument("--extra-metrics", default=None, help="JSON dict of additional metrics")
    p_it.add_argument("--papers", nargs="*", default=[], help="Referenced papers")
    p_it.add_argument("--feedback", help="User/agent feedback")
    p_it.set_defaults(func=cmd_add_iteration)

    # start-iteration (new: creates entry in 'coding' status)
    p_start = sub.add_parser("start-iteration", help="Create a new iteration (status: coding)")
    p_start.add_argument("--hypothesis", help="What you expect")
    p_start.add_argument("--change", help="Summary of planned change")
    p_start.add_argument("--papers", nargs="*", default=[], help="Referenced papers")
    p_start.set_defaults(func=cmd_start_iteration)

    # launch-iteration (new: coding -> running)
    p_launch = sub.add_parser("launch-iteration", help="Mark iteration as running")
    p_launch.add_argument("--id", type=int, required=True, help="Iteration ID")
    p_launch.add_argument("--checkpoint", help="Checkpoint directory path")
    p_launch.set_defaults(func=cmd_launch_iteration)

    # complete-iteration (new: running -> completed)
    p_complete = sub.add_parser("complete-iteration", help="Mark iteration as completed with metrics")
    p_complete.add_argument("--id", type=int, required=True, help="Iteration ID")
    p_complete.add_argument("--metric-name", action="append", help="Metric name (repeatable)")
    p_complete.add_argument("--metric-value", action="append", help="Metric value (repeatable)")
    p_complete.add_argument("--extra-metrics", default=None, help="JSON dict of additional metrics")
    p_complete.add_argument("--feedback", help="User/agent feedback")
    p_complete.add_argument("--checkpoint", help="Override checkpoint directory path")
    p_complete.set_defaults(func=cmd_complete_iteration)

    # fail-iteration (new: coding/running -> failed)
    p_fail = sub.add_parser("fail-iteration", help="Mark iteration as failed")
    p_fail.add_argument("--id", type=int, required=True, help="Iteration ID")
    p_fail.add_argument("--feedback", help="Reason for failure")
    p_fail.set_defaults(func=cmd_fail_iteration)

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
