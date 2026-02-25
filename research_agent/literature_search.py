#!/usr/bin/env python3
"""Literature search via Claude Code worker in a tmux pane.

Launches `claude -p` in a separate tmux window to perform web searches
for relevant papers. Uses the user's Claude subscription (no API key needed).

Usage:
    python research_agent/literature_search.py "topic" output.json
    python research_agent/literature_search.py "topic" output.json --state state.json
    python research_agent/literature_search.py --auto output.json --state state.json

The --auto flag generates the search topic from the last iteration's
feedback in state.json.
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
DEFAULT_TIMEOUT = 300  # 5 minutes
WORKSPACE = Path(__file__).resolve().parent / "workspace"


def _project_tag(state_path: str | None) -> str:
    """Derive a short project tag from state.json's project_dir or fallback."""
    if state_path and Path(state_path).exists():
        try:
            state = json.loads(Path(state_path).read_text(encoding="utf-8"))
            pdir = state.get("project_dir", "")
            if pdir:
                return Path(pdir).name.lower().replace(" ", "-")[:20]
        except (json.JSONDecodeError, IOError):
            pass
    return "default"


# ── Prompt building ──────────────────────────────────────────────────

def _build_context(state_path: str | None) -> tuple[str, list[str]]:
    """Build project context + list of already-used papers from state.json."""
    if not state_path or not Path(state_path).exists():
        return "", []

    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return "", []

    parts = []
    seen_papers: list[str] = []

    if state.get("goal"):
        parts.append(f"Project goal: {state['goal']}")
    if state.get("primary_metric"):
        parts.append(f"Primary metric: {state['primary_metric']}")

    bl = state.get("baseline")
    if bl and bl.get("metrics"):
        parts.append(f"Baseline: {json.dumps(bl['metrics'])}")

    best = state.get("best")
    if best and best.get("metrics"):
        parts.append(f"Best so far (iter {best.get('iteration', '?')}): "
                      f"{json.dumps(best['metrics'])}")

    for it in state.get("iterations", []):
        for p in it.get("papers_referenced", []):
            seen_papers.append(p)

    for it in state.get("iterations", [])[-5:]:
        parts.append(f"Iter {it['id']}: {it.get('change_summary', '')} "
                      f"-> {json.dumps(it.get('metrics', {}))} "
                      f"| feedback: {it.get('feedback', '')}")

    return "\n".join(parts), seen_papers


def _auto_topic(state_path: str) -> str:
    """Generate search topic from last iteration's feedback."""
    if not Path(state_path).exists():
        print("Error: --auto requires --state with existing state.json",
              file=sys.stderr)
        sys.exit(1)

    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    iters = state.get("iterations", [])
    goal = state.get("goal", "")

    if not iters:
        return f"techniques for: {goal}"

    last = iters[-1]
    feedback = last.get("feedback", "")
    change = last.get("change_summary", "")

    topic_parts = []
    if feedback:
        topic_parts.append(f"Based on result: {feedback}")
    if change:
        topic_parts.append(f"Last change: {change}")
    topic_parts.append(f"Goal: {goal}")

    return ". ".join(topic_parts)


def _build_prompt(topic: str, context: str, seen_papers: list[str]) -> str:
    """Build the full prompt for the Claude worker."""
    parts = [
        "You are a research paper search agent. Search the web for academic "
        "papers relevant to this topic:\n",
        f"Topic: {topic}\n",
    ]

    if context:
        parts.append(f"Project context:\n{context}\n")

    if seen_papers:
        parts.append(
            "Papers already used in previous iterations (DO NOT return these):\n"
            + "\n".join(f"- {p}" for p in seen_papers) + "\n"
        )

    parts.append("""\
Instructions:
1. Use web search to find 3-8 highly relevant academic papers.
2. Search from multiple angles (3-5 different queries).
3. For each paper, evaluate relevance (1-5 scale). Only keep papers scoring 3+.
4. Return ONLY a valid JSON array. No markdown fences, no commentary.

Each element must have this structure:
{
  "title": "Paper Title",
  "authors": "First Author et al.",
  "year": 2024,
  "abstract": "First 2-3 sentences...",
  "url": "https://...",
  "arxiv_id": "2401.12345 or empty string",
  "relevance": 5,
  "relevance_reason": "Why this paper matters",
  "key_idea": "Main takeaway applicable to our work"
}

Sort by relevance desc, then year desc.
Quality over quantity. No hallucinated papers — only include papers you found.
Return ONLY the JSON array, nothing else.""")

    return "\n".join(parts)


# ── Worker execution ─────────────────────────────────────────────────

def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def _extract_json_array(text: str) -> list | None:
    """Extract JSON array from text, handling markdown fences and noise."""
    text = _strip_ansi(text).strip()

    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown fences or bare array
    for pattern in [r"```json\s*\n(.*?)\n```",
                    r"```\s*\n(.*?)\n```",
                    r"(\[[\s\S]*\])"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                continue
    return None


def _run_in_tmux(cmd: str, window_name: str) -> None:
    """Launch a bash command in a new detached tmux window."""
    subprocess.run(
        ["tmux", "new-window", "-d", "-n", window_name, "bash", "-c", cmd],
        check=True,
    )


def run_search(topic: str, output_path: str,
               state_path: str | None = None,
               timeout: int = DEFAULT_TIMEOUT) -> list | None:
    """Run paper search via a Claude Code worker in a tmux pane."""

    tag = _project_tag(state_path)
    context, seen_papers = _build_context(state_path)
    prompt = _build_prompt(topic, context, seen_papers)

    # Use workspace for temp files, output goes to user-specified path
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    prompt_file = WORKSPACE / f"{tag}_search.prompt"
    done_marker = WORKSPACE / f"{tag}_search.done"
    err_file = WORKSPACE / f"{tag}_search.err"
    worker_out = WORKSPACE / f"{tag}_search.output"

    # Clean previous run artifacts
    for f in [worker_out, done_marker, err_file]:
        f.unlink(missing_ok=True)

    prompt_file.write_text(prompt, encoding="utf-8")

    # Build the command for the tmux worker pane
    cmd = (
        f"claude -p --verbose --dangerously-skip-permissions "
        f"< {shlex.quote(str(prompt_file))} "
        f"> {shlex.quote(str(worker_out))} "
        f"2> {shlex.quote(str(err_file))}; "
        f"echo $? > {shlex.quote(str(done_marker))}"
    )

    print(f"Search topic: {topic}", file=sys.stderr)

    win_name = f"{tag}:search"
    if os.environ.get("TMUX"):
        _run_in_tmux(cmd, win_name)
        print(f"Worker launched in tmux window '{win_name}'", file=sys.stderr)
    else:
        # Fallback: run as detached subprocess (works outside tmux)
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
            print(f"Timeout after {timeout}s waiting for search worker",
                  file=sys.stderr)
            return None
        time.sleep(POLL_INTERVAL)
        if int(elapsed) % 30 < POLL_INTERVAL and elapsed > POLL_INTERVAL:
            print(f"  Searching... ({int(elapsed)}s)", file=sys.stderr)

    # Check exit code
    exit_code = done_marker.read_text(encoding="utf-8").strip()
    if exit_code != "0":
        err_text = err_file.read_text(encoding="utf-8") if err_file.exists() else "unknown"
        print(f"Worker exited with code {exit_code}: {err_text[:500]}",
              file=sys.stderr)
        # Still try to parse output — Claude may have produced partial results

    if not worker_out.exists() or worker_out.stat().st_size == 0:
        print("No output produced by worker", file=sys.stderr)
        return None

    raw = worker_out.read_text(encoding="utf-8")
    papers = _extract_json_array(raw)

    if papers is not None:
        # Write clean JSON to user-specified output path
        with open(out, "w", encoding="utf-8") as f:
            json.dump(papers, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Found {len(papers)} papers -> {output_path}", file=sys.stderr)
        return papers
    else:
        print("Could not parse JSON from worker output", file=sys.stderr)
        print(f"Raw (first 500 chars): {raw[:500]}", file=sys.stderr)
        return None


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Literature search: Paper search via Claude Code worker.",
        epilog="""\
Examples:
  python literature_search.py "orthogonal adapter fine-tuning" results/search.json
  python literature_search.py "PEFT medical segmentation" results/search.json --state state.json
  python literature_search.py --auto results/search.json --state state.json
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("topic", nargs="?", default=None,
                        help="Search topic (omit if using --auto)")
    parser.add_argument("output", help="Output JSON file path")
    parser.add_argument("--state", default=None,
                        help="Path to state.json for context + dedup")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-generate topic from last iteration")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Timeout in seconds (default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args()

    if args.auto:
        if not args.state:
            print("Error: --auto requires --state", file=sys.stderr)
            sys.exit(1)
        topic = _auto_topic(args.state)
        print(f"Auto-generated topic: {topic}", file=sys.stderr)
    elif args.topic:
        topic = args.topic
    else:
        print("Error: provide a topic or use --auto", file=sys.stderr)
        sys.exit(1)

    papers = run_search(topic, args.output, state_path=args.state,
                        timeout=args.timeout)

    if papers is not None:
        json.dump(papers, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
