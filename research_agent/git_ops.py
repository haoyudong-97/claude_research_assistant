#!/usr/bin/env python3
"""Git operations for the research loop.

Each iteration gets a branch with structured commits that track the
hypothesis, code change, and results. Best iterations merge to main.

Usage (via Bash — called from the project repo, not the research_agent dir):
    python -m research_agent.git_ops branch-start \
        --iteration 3 --change "enable token-wise FiLM"

    python -m research_agent.git_ops commit-code \
        --iteration 3 --hypothesis "Token-wise FiLM enables per-token adaptation" \
        --change "cond_scale_tokenwise=True" --papers "FiLM 2018" "AdaptFormer 2022"

    python -m research_agent.git_ops commit-results \
        --iteration 3 --state state.json

    python -m research_agent.git_ops merge-best --state state.json

    python -m research_agent.git_ops push
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a git command."""
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def _current_branch() -> str:
    r = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return r.stdout.strip()


def _has_changes() -> bool:
    """Check if there are staged or unstaged changes."""
    r = _run(["git", "status", "--porcelain"], check=False)
    return bool(r.stdout.strip())


def _slugify(text: str, max_len: int = 40) -> str:
    """Convert text to a git-branch-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_len].rstrip("-")


def _load_state(state_path: str) -> dict:
    p = Path(state_path)
    if not p.exists():
        print(f"Error: state file not found: {state_path}", file=sys.stderr)
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _get_iteration(state: dict, iteration_id: int) -> dict | None:
    for it in state.get("iterations", []):
        if it["id"] == iteration_id:
            return it
    return None


def _branch_name(iteration_id: int, change: str) -> str:
    slug = _slugify(change)
    return f"iter/{iteration_id}-{slug}" if slug else f"iter/{iteration_id}"


def _find_iter_branch(iteration_id: int) -> str | None:
    """Find the actual branch name for an iteration by searching git."""
    # Try exact prefix match: iter/{id}-*
    r = _run(["git", "branch", "--list", f"iter/{iteration_id}-*"], check=False)
    branches = [b.strip().lstrip("* ") for b in r.stdout.strip().splitlines() if b.strip()]
    if len(branches) == 1:
        return branches[0]
    # Also try bare iter/{id} (no slug)
    r2 = _run(["git", "rev-parse", "--verify", f"iter/{iteration_id}"], check=False)
    if r2.returncode == 0:
        return f"iter/{iteration_id}"
    # Multiple matches — return first
    if branches:
        return branches[0]
    return None


# ── Commands ───────────────────────────────────────────────────────────

def cmd_branch_start(args) -> None:
    """Create a new branch for this iteration from main."""
    branch = _branch_name(args.iteration, args.change or "")

    # Ensure we're on main
    current = _current_branch()
    if current != "main":
        print(f"Switching from {current} to main first", file=sys.stderr)
        _run(["git", "checkout", "main"])

    # Pull latest if remote exists
    r = _run(["git", "remote"], check=False)
    if r.stdout.strip():
        _run(["git", "pull", "--ff-only"], check=False)

    _run(["git", "checkout", "-b", branch])
    print(f"Created branch: {branch}")


def cmd_commit_code(args) -> None:
    """Commit code changes with a structured message (before experiment runs).

    Stages all modified/new files. The commit message documents the
    hypothesis and planned change, so `git log` tells the full story.
    """
    if not _has_changes():
        print("No changes to commit.", file=sys.stderr)
        sys.exit(1)

    # Build commit message
    lines = [
        f"iter/{args.iteration}: {args.change or 'code change'}",
        "",
        f"Hypothesis: {args.hypothesis or 'N/A'}",
        f"Change: {args.change or 'N/A'}",
    ]
    if args.papers:
        lines.append(f"Papers: {', '.join(args.papers)}")
    if args.checkpoint:
        lines.append(f"Checkpoint: {args.checkpoint}")
    lines.append("")
    lines.append("Status: experiment pending")

    msg = "\n".join(lines)

    # Stage and commit
    _run(["git", "add", "-A"])
    _run(["git", "commit", "-m", msg])
    print(f"Committed: iter/{args.iteration}: {args.change}")


def cmd_commit_results(args) -> None:
    """Commit results after experiment completes.

    Reads metrics from state.json for the specified iteration and creates
    a results commit. This may include updated state.json, progress.md,
    and any analysis files.
    """
    state = _load_state(args.state)
    it = _get_iteration(state, args.iteration)
    if not it:
        print(f"Error: iteration {args.iteration} not found in state", file=sys.stderr)
        sys.exit(1)

    primary = state.get("primary_metric", "")
    bl = state.get("baseline")
    bl_val = None
    if bl and bl.get("metrics"):
        bl_val = bl["metrics"].get(primary)

    # Build results commit message
    m_val = it.get("metrics", {}).get(primary)
    title_metric = ""
    if m_val is not None:
        title_metric = f" — {primary}: {m_val}"
        if bl_val is not None:
            delta = float(m_val) - float(bl_val)
            sign = "+" if delta >= 0 else ""
            title_metric += f" ({sign}{delta:.4f})"

    lines = [
        f"iter/{args.iteration}: results{title_metric}",
        "",
    ]

    # All metrics
    if it.get("metrics"):
        lines.append("Results:")
        for k, v in it["metrics"].items():
            delta_str = ""
            if bl_val is not None and bl and bl.get("metrics") and k in bl["metrics"]:
                d = float(v) - float(bl["metrics"][k])
                sign = "+" if d >= 0 else ""
                delta_str = f" ({sign}{d:.4f} vs baseline)"
            lines.append(f"  {k}: {v}{delta_str}")
        lines.append("")

    if it.get("hypothesis"):
        lines.append(f"Hypothesis: {it['hypothesis']}")
    if it.get("change_summary"):
        lines.append(f"Change: {it['change_summary']}")
    if it.get("feedback"):
        lines.append(f"Feedback: {it['feedback']}")
    if it.get("checkpoint"):
        lines.append(f"Checkpoint: {it['checkpoint']}")

    # Note if this is the new best
    best = state.get("best")
    if best and best.get("iteration") == args.iteration:
        lines.append("")
        lines.append("*** NEW BEST ***")

    msg = "\n".join(lines)

    # Stage and commit (allow empty if only state.json changed and it's gitignored)
    _run(["git", "add", "-A"])
    r = _run(["git", "diff", "--cached", "--quiet"], check=False)
    if r.returncode != 0:
        _run(["git", "commit", "-m", msg])
        print(f"Committed results for iteration {args.iteration}")
    else:
        # No staged changes (state.json is gitignored), commit with --allow-empty
        _run(["git", "commit", "--allow-empty", "-m", msg])
        print(f"Committed results (empty, state files gitignored) for iteration {args.iteration}")


def cmd_merge_best(args) -> None:
    """Merge the best iteration branch into main."""
    state = _load_state(args.state)
    best = state.get("best")
    if not best:
        print("No best iteration recorded yet.", file=sys.stderr)
        sys.exit(1)

    best_it = _get_iteration(state, best["iteration"])
    if not best_it:
        print(f"Error: best iteration {best['iteration']} not found", file=sys.stderr)
        sys.exit(1)

    # Find the actual branch (may differ from reconstructed name)
    branch = _find_iter_branch(best_it["id"])
    if not branch:
        fallback = _branch_name(best_it["id"], best_it.get("change_summary", ""))
        print(f"Branch for iteration {best_it['id']} not found "
              f"(tried iter/{best_it['id']}-* and {fallback}). Skipping merge.",
              file=sys.stderr)
        sys.exit(1)

    current = _current_branch()
    if current != "main":
        _run(["git", "checkout", "main"])

    primary = state.get("primary_metric", "")
    m_val = best.get("metrics", {}).get(primary, "N/A")

    merge_msg = (
        f"Merge iter/{best_it['id']}: {best_it.get('change_summary', 'best result')}\n\n"
        f"Best {primary}: {m_val}\n"
        f"Iteration: {best_it['id']}\n"
        f"Hypothesis: {best_it.get('hypothesis', 'N/A')}"
    )

    _run(["git", "merge", branch, "-m", merge_msg])
    print(f"Merged {branch} into main ({primary}: {m_val})")


def _has_remote() -> bool:
    """Check if a remote is configured."""
    r = _run(["git", "remote"], check=False)
    return bool(r.stdout.strip())


def cmd_push(args) -> None:
    """Push current branch to remote (skips if no remote configured)."""
    if not _has_remote():
        print("No remote configured, skipping push.")
        return
    branch = _current_branch()
    _run(["git", "push", "-u", "origin", branch])
    print(f"Pushed {branch}")


def cmd_push_all(args) -> None:
    """Push main and all iter/* branches to remote (skips if no remote configured)."""
    if not _has_remote():
        print("No remote configured, skipping push.")
        return

    # Push main
    _run(["git", "push", "-u", "origin", "main"], check=False)

    # Push all iter branches
    r = _run(["git", "branch", "--list", "iter/*"], check=False)
    for line in r.stdout.strip().splitlines():
        branch = line.strip().lstrip("* ")
        if branch:
            _run(["git", "push", "-u", "origin", branch], check=False)
            print(f"Pushed {branch}")


def cmd_log(args) -> None:
    """Show iteration history from git log (structured commits only)."""
    r = _run(["git", "log", "--all", "--oneline", "--grep=^iter/", "--perl-regexp"])
    print(r.stdout)


def main():
    parser = argparse.ArgumentParser(
        prog="research_agent.git_ops",
        description="Git operations for the research loop",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # branch-start
    p_bs = sub.add_parser("branch-start", help="Create iteration branch from main")
    p_bs.add_argument("--iteration", type=int, required=True, help="Iteration number")
    p_bs.add_argument("--change", default="", help="Short change description (for branch name)")
    p_bs.set_defaults(func=cmd_branch_start)

    # commit-code
    p_cc = sub.add_parser("commit-code", help="Commit code changes (before experiment)")
    p_cc.add_argument("--iteration", type=int, required=True, help="Iteration number")
    p_cc.add_argument("--hypothesis", help="What you expect")
    p_cc.add_argument("--change", help="What was changed")
    p_cc.add_argument("--papers", nargs="*", default=[], help="Referenced papers")
    p_cc.add_argument("--checkpoint", help="Planned checkpoint dir")
    p_cc.set_defaults(func=cmd_commit_code)

    # commit-results
    p_cr = sub.add_parser("commit-results", help="Commit results (after experiment)")
    p_cr.add_argument("--iteration", type=int, required=True, help="Iteration number")
    p_cr.add_argument("--state", default="state.json", help="State file path")
    p_cr.set_defaults(func=cmd_commit_results)

    # merge-best
    p_mb = sub.add_parser("merge-best", help="Merge best iteration branch into main")
    p_mb.add_argument("--state", default="state.json", help="State file path")
    p_mb.set_defaults(func=cmd_merge_best)

    # push
    p_push = sub.add_parser("push", help="Push current branch to remote")
    p_push.set_defaults(func=cmd_push)

    # push-all
    p_pa = sub.add_parser("push-all", help="Push main + all iter branches")
    p_pa.set_defaults(func=cmd_push_all)

    # log
    p_log = sub.add_parser("log", help="Show iteration commits from git log")
    p_log.set_defaults(func=cmd_log)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
