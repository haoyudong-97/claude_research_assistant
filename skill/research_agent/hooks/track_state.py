#!/usr/bin/env python3
"""Pre/PostToolUse hook: track research state + warn about untracked experiments.

Two responsibilities:
1. PostToolUse: Auto-update state.json when research_agent tools run
   (deploy launch/status/preflight, git commit/checkout)
2. PreToolUse: Warn when an experiment-like command is run outside the
   /idea-iter framework, redirecting the user to use the skill instead.

Stdin:  Hook JSON (Claude Code hook contract)
Stdout: Hook response JSON (additionalContext for the model)
Exit:   0 = success, 1 = error (non-blocking)
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


STATE_FILE = Path(os.environ.get("RESEARCH_STATE_FILE", "state.json"))

TRAIN_PATTERNS = [
    r"python\s+.*train", r"python\s+-m\s+\S*train", r"python\s+.*experiment",
    r"python\s+.*run[_\s]", r"python\s+.*main\.py", r"bash\s+.*train",
    r"bash\s+.*run", r"bash\s+.*experiment", r"bash\s+.*launch", r"sh\s+.*train",
    r"sbatch\s+", r"srun\s+", r"nohup\s+.*train", r"nohup\s+.*python",
    r"screen\s+-.*train", r"tmux\s+.*train", r"torchrun\s+", r"accelerate\s+launch",
    r"deepspeed\s+", r"python\s+-m\s+torch\.distributed", r"run_and_wait\.sh",
    r"nnUNetv2_train", r"nnUNetv2_predict", r"nnUNetv2_evaluate",
]
TRAIN_RE = re.compile("|".join(TRAIN_PATTERNS), re.IGNORECASE)

FRAMEWORK_PATTERNS = [
    r"research_agent\.deploy\s+launch", r"research_agent\.deploy\s+preflight",
    r"research_agent\.deploy\s+status", r"research_agent\.deploy\s+collect",
    r"research_agent\.state\s+", r"research_agent\.git_ops\s+",
    r"research_agent\.search_papers", r"research_agent\.idea_discovery",
]
FRAMEWORK_RE = re.compile("|".join(FRAMEWORK_PATTERNS), re.IGNORECASE)


def _load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return None


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _find_by_status(state: dict, status: str) -> list[dict]:
    return [it for it in state.get("iterations", []) if it.get("status") == status]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _is_training_command(command: str) -> bool:
    return bool(TRAIN_RE.search(command))


def _is_framework_command(command: str) -> bool:
    return bool(FRAMEWORK_RE.search(command))


# ── PostToolUse handlers ─────────────────────────────────────────────

def handle_deploy_launch(command: str, output: str, state: dict) -> str | None:
    try:
        launch_info = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return None
    coding = _find_by_status(state, "coding")
    if not coding:
        return None
    it = coding[-1]
    it["status"] = "running"
    it["timestamp"] = _now()
    checkpoint = launch_info.get("output_dir", "")
    if checkpoint:
        it["checkpoint"] = checkpoint
    md = it.setdefault("metadata", {})
    md["command"] = command[:200]
    for key in ("gpu_id", "pid", "screen"):
        if launch_info.get(key):
            md[key] = launch_info[key]
    if launch_info.get("mode"):
        md["deploy_mode"] = launch_info["mode"]
    if launch_info.get("host"):
        md["deploy_host"] = launch_info["host"]
    _save_state(state)
    return f"Iteration {it['id']} marked as running. Checkpoint: {checkpoint}. GPU: {launch_info.get('gpu_id', 'auto')}."


def handle_deploy_status(command: str, output: str, state: dict) -> str | None:
    try:
        status_info = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return None
    notes = []
    if status_info.get("status") in ("completed", "failed"):
        output_dir = status_info.get("output_dir", "")
        for it in _find_by_status(state, "running"):
            if it.get("checkpoint") and output_dir and it["checkpoint"] in output_dir:
                if status_info["status"] == "failed":
                    it["status"] = "failed"
                    it["timestamp"] = _now()
                    it["feedback"] = f"Exit code: {status_info.get('exit_code', 'unknown')}"
                    notes.append(f"Iter {it['id']}: FAILED")
                else:
                    notes.append(f"Iter {it['id']}: finished (exit 0), metrics pending")
    for exp in status_info.get("experiments", []):
        if exp.get("status") == "failed":
            output_dir = exp.get("output_dir", "")
            for it in _find_by_status(state, "running"):
                if it.get("checkpoint") and output_dir and it["checkpoint"] in output_dir:
                    it["status"] = "failed"
                    it["timestamp"] = _now()
                    it["feedback"] = f"Exit code: {exp.get('exit_code', 'unknown')}"
                    notes.append(f"Iter {it['id']}: FAILED")
    if notes:
        _save_state(state)
        return "Auto-updated: " + "; ".join(notes)
    return None


def handle_deploy_preflight(command: str, output: str, state: dict) -> str | None:
    try:
        info = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return None
    gpus = info.get("gpus", [])
    if not gpus:
        return None
    state.setdefault("metadata", {})["last_gpu_check"] = {
        "timestamp": _now(), "host": info.get("host", "local"),
        "available": info.get("available", False),
        "gpus": [{"id": g["id"], "name": g.get("name", ""), "free_mb": g.get("memory_free_mb", 0)} for g in gpus],
    }
    _save_state(state)
    return None


def handle_git_commit(command: str, output: str, state: dict) -> str | None:
    m = re.search(r"\[[\w/\-.]+ ([a-f0-9]{7,})\]", output)
    if not m:
        return None
    commit_hash = m.group(1)
    active = _find_by_status(state, "coding") or _find_by_status(state, "running")
    if not active:
        return None
    it = active[-1]
    it.setdefault("metadata", {})["last_commit"] = commit_hash
    it["timestamp"] = _now()
    _save_state(state)
    return f"Recorded commit {commit_hash} for iteration {it['id']}."


def handle_git_checkout(command: str, output: str, state: dict) -> str | None:
    m = re.search(r"iter/(\d+)", command)
    if m:
        state.setdefault("metadata", {})["active_branch_iter"] = int(m.group(1))
        _save_state(state)
    return None


# ── PreToolUse: warn about untracked experiments ──────────────────────

def handle_pre_untracked(command: str) -> dict:
    desc = re.sub(r"^(?:CUDA_VISIBLE_DEVICES=\S+\s+|nohup\s+|bash\s+)", "", command).strip()[:80]
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "additionalContext": (
                f"WARNING: This experiment (`{desc}`) is being launched outside the "
                f"research tracking framework. It will NOT be recorded in state.json "
                f"and its results will not appear in /check-experiments.\n\n"
                f"To track this experiment, use one of:\n"
                f"  /idea-iter <your idea>        — full pipeline with paper search\n"
                f"  /implement <what to change>        — implement + tracked launch\n"
                f"  python -m research_agent.deploy launch <script> <output_dir>\n\n"
                f"Proceeding anyway since you may have a reason for a direct launch."
            ),
        }
    }


def handle_pre_framework_launch(command: str, state: dict | None) -> dict:
    if state is None:
        return {}
    running = _find_by_status(state, "running")
    coding = _find_by_status(state, "coding")
    warnings = []
    if not coding:
        warnings.append("No iteration in 'coding' status — this launch may not be tracked properly.")
    if len(running) >= 3:
        warnings.append(f"{len(running)} experiments already running. GPU contention likely.")
    for it in running:
        prev_cmd = it.get("metadata", {}).get("command", "")
        if prev_cmd and prev_cmd == command[:200]:
            warnings.append(f"Duplicate: same command already running as iteration {it['id']}.")
    if warnings:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                       "additionalContext": "Warnings: " + " ".join(warnings)}}
    return {}


# ── Main dispatch ─────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print("{}")
        sys.exit(0)
    try:
        hook = json.loads(raw)
    except json.JSONDecodeError:
        print("{}")
        sys.exit(0)

    event = hook.get("hook_event_name", "")
    tool_name = hook.get("tool_name", "")
    tool_input = hook.get("tool_input", {})
    tool_response = hook.get("tool_response", {})
    command = tool_input.get("command", "") if tool_name == "Bash" else ""

    if isinstance(tool_response, dict):
        output = tool_response.get("stdout", "")
    elif isinstance(tool_response, str):
        output = tool_response
    else:
        output = str(tool_response) if tool_response else ""

    if event == "PreToolUse" and tool_name == "Bash":
        if "research_agent.deploy launch" in command:
            state = _load_state()
            print(json.dumps(handle_pre_framework_launch(command, state)))
            sys.exit(0)
        if _is_training_command(command) and not _is_framework_command(command):
            print(json.dumps(handle_pre_untracked(command)))
            sys.exit(0)
        print("{}")
        sys.exit(0)

    if event != "PostToolUse":
        print("{}")
        sys.exit(0)

    state = _load_state()
    if state is None:
        print("{}")
        sys.exit(0)

    context = None
    if tool_name == "Bash":
        if "research_agent.deploy launch" in command:
            context = handle_deploy_launch(command, output, state)
        elif "research_agent.deploy status" in command:
            context = handle_deploy_status(command, output, state)
        elif "research_agent.deploy preflight" in command:
            context = handle_deploy_preflight(command, output, state)
        elif re.search(r"git\s+commit", command):
            context = handle_git_commit(command, output, state)
        elif re.search(r"git\s+checkout", command):
            context = handle_git_checkout(command, output, state)

    if context:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                  "additionalContext": f"[state tracking] {context}"}}))
    else:
        print("{}")
    sys.exit(0)


if __name__ == "__main__":
    main()
