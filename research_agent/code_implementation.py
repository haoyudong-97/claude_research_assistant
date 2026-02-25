#!/usr/bin/env python3
"""Code implementation via Claude Code worker in a tmux pane.

Launches `claude -p` in a separate tmux window to implement code changes.
The worker Claude Code reads, edits, and creates files directly in the project.
Uses the user's Claude subscription (no API key needed).

Usage:
    # From paper results:
    python research_agent/code_implementation.py --papers results/search.json --project-dir .

    # From direct instruction:
    python research_agent/code_implementation.py --instruction "increase spd_rank to 8" --project-dir .

    # With specific files to focus on:
    python research_agent/code_implementation.py --papers results/search.json --project-dir . \
        --files models/sam/modeling/common.py cfg.py

Output:
    - Modified files in the project directory (done by the worker)
    - JSON summary to stdout: {"hypothesis": "...", "change_summary": "...", ...}
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

POLL_INTERVAL = 5  # seconds between completion checks
DEFAULT_TIMEOUT = 600  # 10 minutes
WORKSPACE = Path(__file__).resolve().parent / "workspace"


def _project_tag(project_dir: str) -> str:
    """Derive a short project tag from the project directory name."""
    return Path(project_dir).resolve().name.lower().replace(" ", "-")[:20]


# ── Prompt building ──────────────────────────────────────────────────

def _build_prompt(papers_path: str | None, instruction: str | None,
                  project_dir: str, focus_files: list[str] | None,
                  state_path: str | None) -> str:
    """Build the full prompt for the Claude Code implementation worker."""
    parts = []

    proj = Path(project_dir).resolve()
    parts.append(f"You are implementing a code change in the project at: {proj}")
    parts.append(f"Working directory: {proj}")
    parts.append("")

    # Papers context
    if papers_path and Path(papers_path).exists():
        try:
            papers = json.loads(Path(papers_path).read_text(encoding="utf-8"))
            top = sorted(papers, key=lambda p: p.get("relevance", 0),
                         reverse=True)[:3]
            parts.append("## Papers to implement from:\n")
            for p in top:
                parts.append(f"### {p['title']} ({p.get('year', '?')})")
                parts.append(f"Key idea: {p.get('key_idea', p.get('abstract', '')[:300])}")
                parts.append(f"Relevance: {p.get('relevance', '?')}/5")
                if p.get("relevance_reason"):
                    parts.append(f"Why: {p['relevance_reason']}")
                parts.append("")
        except (json.JSONDecodeError, IOError) as e:
            parts.append(f"(Could not read papers file: {e})\n")

    # Direct instruction
    if instruction:
        parts.append(f"## Instruction\n{instruction}\n")

    # Project context from state
    if state_path and Path(state_path).exists():
        try:
            state = json.loads(Path(state_path).read_text(encoding="utf-8"))
            parts.append("## Project context")
            parts.append(f"Goal: {state.get('goal', 'N/A')}")
            parts.append(f"Primary metric: {state.get('primary_metric', 'N/A')}")
            bl = state.get("baseline")
            if bl and bl.get("metrics"):
                parts.append(f"Baseline: {json.dumps(bl['metrics'])}")
            best = state.get("best")
            if best and best.get("metrics"):
                parts.append(f"Best (iter {best.get('iteration')}): "
                              f"{json.dumps(best['metrics'])}")
            iters = state.get("iterations", [])
            if iters:
                last = iters[-1]
                parts.append(f"Last change: {last.get('change_summary', 'N/A')} "
                              f"-> {json.dumps(last.get('metrics', {}))}")
                parts.append(f"Feedback: {last.get('feedback', 'N/A')}")
            parts.append("")
        except (json.JSONDecodeError, IOError):
            pass

    # Focus files
    if focus_files:
        parts.append("## Key files to examine and modify")
        for f in focus_files:
            parts.append(f"- {f}")
        parts.append("")

    # Task instructions
    parts.append("""\
## Task

1. Read the relevant code files FIRST to understand the current implementation.
2. Implement ONE focused change based on the papers/instruction above.
3. Make minimal, surgical edits — don't rewrite entire files or refactor unrelated code.
4. Verify your changes are syntactically correct.
5. After implementing, output EXACTLY this JSON block as the LAST thing you print:

```json
{
  "hypothesis": "What you expect this change to achieve",
  "change_summary": "Short description of what was changed",
  "files_modified": ["path/to/file1.py", "path/to/file2.py"],
  "papers_used": ["Paper Title 1", "Paper Title 2"]
}
```

IMPORTANT: The JSON block above MUST be the very last thing in your output.
Do NOT add any commentary after the JSON block.""")

    return "\n".join(parts)


# ── Worker execution ─────────────────────────────────────────────────

def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def _extract_summary(text: str) -> dict:
    """Extract the JSON summary from the worker's output."""
    text = _strip_ansi(text)

    # Look for the last JSON block in markdown fences
    matches = list(re.finditer(r"```json\s*\n(.*?)\n```", text, re.DOTALL))
    if matches:
        try:
            obj = json.loads(matches[-1].group(1))
            if isinstance(obj, dict) and "change_summary" in obj:
                return obj
        except json.JSONDecodeError:
            pass

    # Look for the last JSON object containing our expected keys
    matches = list(re.finditer(
        r'\{[^{}]*"(?:hypothesis|change_summary)"[^{}]*\}', text, re.DOTALL
    ))
    if matches:
        try:
            return json.loads(matches[-1].group(0))
        except json.JSONDecodeError:
            pass

    # Try multiline JSON object at the end of text
    match = re.search(r'(\{[\s\S]*"change_summary"[\s\S]*\})\s*$', text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: couldn't parse
    return {
        "hypothesis": "",
        "change_summary": "(could not parse summary from worker output)",
        "files_modified": [],
        "papers_used": [],
    }


def _run_in_tmux(cmd: str, window_name: str) -> None:
    """Launch a bash command in a new detached tmux window."""
    subprocess.run(
        ["tmux", "new-window", "-d", "-n", window_name, "bash", "-c", cmd],
        check=True,
    )


def run_implementation(papers_path: str | None, instruction: str | None,
                       project_dir: str, focus_files: list[str] | None,
                       state_path: str | None,
                       timeout: int = DEFAULT_TIMEOUT) -> dict | None:
    """Run code implementation via a Claude Code worker in a tmux pane."""

    tag = _project_tag(project_dir)
    prompt = _build_prompt(papers_path, instruction, project_dir,
                           focus_files, state_path)

    # Use workspace for all temp/output files (avoids /tmp space issues)
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    worker_out = WORKSPACE / f"{tag}_impl.output"
    prompt_file = WORKSPACE / f"{tag}_impl.prompt"
    done_marker = WORKSPACE / f"{tag}_impl.done"
    err_file = WORKSPACE / f"{tag}_impl.err"

    # Clean previous run artifacts
    for f in [worker_out, done_marker, err_file]:
        f.unlink(missing_ok=True)

    prompt_file.write_text(prompt, encoding="utf-8")

    # Build command: cd to project dir, run claude -p with file tools
    proj_abs = shlex.quote(str(Path(project_dir).resolve()))
    cmd = (
        f"cd {proj_abs} && "
        f"claude -p --verbose --dangerously-skip-permissions "
        f"< {shlex.quote(str(prompt_file))} "
        f"> {shlex.quote(str(worker_out))} "
        f"2> {shlex.quote(str(err_file))}; "
        f"echo $? > {shlex.quote(str(done_marker))}"
    )

    print(f"Implementing changes in {project_dir}...", file=sys.stderr)

    win_name = f"{tag}:impl"
    if os.environ.get("TMUX"):
        _run_in_tmux(cmd, win_name)
        print(f"Worker launched in tmux window '{win_name}'", file=sys.stderr)
    else:
        subprocess.Popen(
            ["bash", "-c", cmd],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("Worker launched as background process", file=sys.stderr)

    # Poll for completion
    start = time.time()
    while not done_marker.exists():
        elapsed = time.time() - start
        if elapsed > timeout:
            print(f"Timeout after {timeout}s waiting for implementation worker",
                  file=sys.stderr)
            return None
        time.sleep(POLL_INTERVAL)
        if int(elapsed) % 60 < POLL_INTERVAL and elapsed > POLL_INTERVAL:
            print(f"  Still implementing... ({int(elapsed)}s)", file=sys.stderr)

    # Check exit code
    exit_code = done_marker.read_text(encoding="utf-8").strip()
    if exit_code != "0":
        err_text = err_file.read_text(encoding="utf-8") if err_file.exists() else "unknown"
        print(f"Worker exited with code {exit_code}: {err_text[:500]}",
              file=sys.stderr)
        # Still try to parse — partial output may be useful

    if not worker_out.exists() or worker_out.stat().st_size == 0:
        print("No output produced by worker", file=sys.stderr)
        return None

    raw = worker_out.read_text(encoding="utf-8")
    summary = _extract_summary(raw)

    print(f"Done: {summary.get('change_summary', 'N/A')}", file=sys.stderr)
    return summary


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Code implementation via Claude Code worker.",
        epilog="""\
Examples:
  python code_implementation.py --papers results/search.json --project-dir .
  python code_implementation.py --instruction "increase spd_rank to 8" --project-dir .
  python code_implementation.py --papers results/search.json --project-dir . \\
      --files models/sam/modeling/common.py cfg.py
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--papers", default=None,
                        help="Path to papers JSON from literature_search")
    parser.add_argument("--instruction", default=None,
                        help="Direct instruction (alternative to papers)")
    parser.add_argument("--project-dir", default=".",
                        help="Project root directory (default: cwd)")
    parser.add_argument("--files", nargs="*", default=None,
                        help="Key files to focus on")
    parser.add_argument("--state", default=None,
                        help="Path to state.json for context")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Timeout in seconds (default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args()

    if not args.papers and not args.instruction:
        print("Error: provide --papers or --instruction", file=sys.stderr)
        sys.exit(1)

    result = run_implementation(
        args.papers, args.instruction, args.project_dir,
        args.files, args.state, timeout=args.timeout,
    )

    if result:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
