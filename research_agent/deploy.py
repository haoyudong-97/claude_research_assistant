#!/usr/bin/env python3
"""GPU-aware experiment deployment (local + remote).

Supports pre-flight GPU checks, remote deployment via SSH + screen,
code sync, and result collection.

Usage:
    python -m research_agent.deploy preflight [--host HOST]
    python -m research_agent.deploy launch <script> <output_dir> [--host HOST] [--gpu GPU_ID]
    python -m research_agent.deploy status [--host HOST] [--output-dir DIR]
    python -m research_agent.deploy collect <output_dir> [--host HOST] [--local-dir DIR]

Environment variables:
    DEPLOY_HOST          Remote GPU host (default: local)
    DEPLOY_USER          SSH username (default: $USER)
    DEPLOY_REMOTE_DIR    Remote working directory (default: ~/research)
    DEPLOY_GPU_MEM_MIN   Minimum free GPU memory in MB (default: 4000)
    DEPLOY_SCREEN_PREFIX Screen session name prefix (default: exp)
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


# ── Config ────────────────────────────────────────────────────────────

def _get_config(args) -> dict:
    """Resolve config from CLI args > env vars > defaults."""
    return {
        "host": getattr(args, "host", None) or os.environ.get("DEPLOY_HOST", ""),
        "user": getattr(args, "user", None) or os.environ.get("DEPLOY_USER", os.environ.get("USER", "")),
        "remote_dir": getattr(args, "remote_dir", None) or os.environ.get("DEPLOY_REMOTE_DIR", "~/research"),
        "gpu_mem_min": int(getattr(args, "gpu_mem_min", None) or os.environ.get("DEPLOY_GPU_MEM_MIN", "4000")),
        "screen_prefix": os.environ.get("DEPLOY_SCREEN_PREFIX", "exp"),
    }


def _is_remote(cfg: dict) -> bool:
    return bool(cfg["host"])


def _ssh_target(cfg: dict) -> str:
    if cfg["user"]:
        return f"{cfg['user']}@{cfg['host']}"
    return cfg["host"]


# ── Shell helpers ─────────────────────────────────────────────────────

def _run_local(cmd: list[str], check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check, timeout=timeout)


def _run_remote(cfg: dict, cmd: str, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
    ssh_cmd = ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", _ssh_target(cfg), cmd]
    return subprocess.run(ssh_cmd, capture_output=True, text=True, check=check, timeout=timeout)


def _run_shell(cmd: str, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check, timeout=timeout)


def _project_root() -> str:
    try:
        r = _run_local(["git", "rev-parse", "--show-toplevel"], check=False)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return os.getcwd()


# ── GPU parsing ───────────────────────────────────────────────────────

def _parse_nvidia_smi(output: str) -> list[dict]:
    """Parse nvidia-smi CSV output into GPU dicts."""
    gpus = []
    for i, line in enumerate(output.strip().splitlines()):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        # nvidia-smi --query-gpu=name,memory.free,memory.total,utilization.gpu --format=csv,noheader
        name = parts[0]
        try:
            mem_free = int(re.sub(r"[^\d]", "", parts[1]))
            mem_total = int(re.sub(r"[^\d]", "", parts[2]))
            util = int(re.sub(r"[^\d]", "", parts[3]))
        except (ValueError, IndexError):
            continue
        gpus.append({
            "id": i,
            "name": name,
            "memory_free_mb": mem_free,
            "memory_total_mb": mem_total,
            "utilization_pct": util,
        })
    return gpus


NVIDIA_SMI_CMD = "nvidia-smi --query-gpu=name,memory.free,memory.total,utilization.gpu --format=csv,noheader"


# ── Commands ──────────────────────────────────────────────────────────

def cmd_preflight(args) -> None:
    """Check GPU availability (local or remote)."""
    cfg = _get_config(args)

    try:
        if _is_remote(cfg):
            r = _run_remote(cfg, NVIDIA_SMI_CMD, check=False, timeout=15)
        else:
            r = _run_local(NVIDIA_SMI_CMD.split(), check=False, timeout=15)
    except subprocess.TimeoutExpired:
        print(json.dumps({"available": False, "error": "timeout", "gpus": []}))
        sys.exit(1)

    if r.returncode != 0:
        error = r.stderr.strip() or "nvidia-smi failed"
        print(json.dumps({"available": False, "error": error, "gpus": []}))
        sys.exit(1)

    gpus = _parse_nvidia_smi(r.stdout)
    available = any(g["memory_free_mb"] >= cfg["gpu_mem_min"] for g in gpus)

    result = {
        "available": available,
        "gpus": gpus,
        "host": cfg["host"] or "local",
        "gpu_mem_min_mb": cfg["gpu_mem_min"],
    }
    print(json.dumps(result, indent=2))
    if not available:
        sys.exit(1)


def cmd_launch(args) -> None:
    """Launch an experiment (local or remote)."""
    cfg = _get_config(args)
    script = args.script
    output_dir = args.output_dir

    if _is_remote(cfg):
        _launch_remote(cfg, script, output_dir, gpu_id=args.gpu)
    else:
        _launch_local(cfg, script, output_dir, gpu_id=args.gpu)


def _pick_gpu(cfg: dict, requested_gpu: str | None) -> str | None:
    """Pick a GPU: use requested, or auto-select the one with most free memory."""
    if requested_gpu is not None:
        return requested_gpu

    try:
        if _is_remote(cfg):
            r = _run_remote(cfg, NVIDIA_SMI_CMD, check=False, timeout=15)
        else:
            r = _run_local(NVIDIA_SMI_CMD.split(), check=False, timeout=15)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if r.returncode != 0:
        return None

    gpus = _parse_nvidia_smi(r.stdout)
    free = [g for g in gpus if g["memory_free_mb"] >= cfg["gpu_mem_min"]]
    if not free:
        return None

    best = max(free, key=lambda g: g["memory_free_mb"])
    return str(best["id"])


def _launch_local(cfg: dict, script: str, output_dir: str, gpu_id: str | None = None) -> None:
    """Launch experiment locally via run_and_wait.sh."""
    # Find run_and_wait.sh relative to this file
    runner = Path(__file__).resolve().parent / "run_and_wait.sh"
    if not runner.exists():
        print(json.dumps({"error": f"run_and_wait.sh not found at {runner}"}))
        sys.exit(1)

    gpu = _pick_gpu(cfg, gpu_id)

    env_prefix = f"CUDA_VISIBLE_DEVICES={gpu} " if gpu is not None else ""
    cmd = f"{env_prefix}bash {shlex.quote(str(runner))} {shlex.quote(script)} {shlex.quote(output_dir)}"

    proc = subprocess.Popen(
        ["bash", "-c", cmd],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    result = {
        "mode": "local",
        "script": script,
        "output_dir": output_dir,
        "pid": proc.pid,
    }
    if gpu is not None:
        result["gpu_id"] = gpu
    print(json.dumps(result, indent=2))


def _launch_remote(cfg: dict, script: str, output_dir: str, gpu_id: str | None = None) -> None:
    """Launch experiment on remote via SSH + screen."""
    target = _ssh_target(cfg)
    remote_dir = cfg["remote_dir"]
    project_root = _project_root()

    # Sync code to remote
    rsync_cmd = [
        "rsync", "-az", "--delete",
        "--exclude", ".git",
        "--exclude", "checkpoints",
        "--exclude", "__pycache__",
        "--exclude", "*.pyc",
        "--exclude", "results/",
        "--exclude", "workspace/",
        f"{project_root}/",
        f"{target}:{remote_dir}/",
    ]
    print(f"Syncing code to {target}:{remote_dir}/ ...", file=sys.stderr)
    try:
        r = _run_local(rsync_cmd, check=False, timeout=120)
        if r.returncode != 0:
            print(json.dumps({"error": f"rsync failed: {r.stderr.strip()}"}))
            sys.exit(1)
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "rsync timed out"}))
        sys.exit(1)

    gpu = _pick_gpu(cfg, gpu_id)

    # Build screen session name
    dir_slug = re.sub(r"[^a-zA-Z0-9]", "_", Path(output_dir).name)[:30]
    screen_name = f"{cfg['screen_prefix']}_{dir_slug}"

    # Build remote command
    env_prefix = f"CUDA_VISIBLE_DEVICES={gpu} " if gpu is not None else ""
    remote_cmd = (
        f"cd {shlex.quote(remote_dir)} && "
        f"{env_prefix}bash research_agent/run_and_wait.sh "
        f"{shlex.quote(script)} {shlex.quote(output_dir)}"
    )
    screen_cmd = f"screen -dmS {screen_name} bash -c {shlex.quote(remote_cmd)}"

    try:
        r = _run_remote(cfg, screen_cmd, check=False, timeout=15)
        if r.returncode != 0:
            print(json.dumps({"error": f"screen launch failed: {r.stderr.strip()}"}))
            sys.exit(1)
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "SSH timeout launching screen"}))
        sys.exit(1)

    result = {
        "mode": "remote",
        "host": cfg["host"],
        "screen": screen_name,
        "remote_dir": remote_dir,
        "script": script,
        "output_dir": output_dir,
    }
    if gpu is not None:
        result["gpu_id"] = gpu
    print(json.dumps(result, indent=2))


def cmd_status(args) -> None:
    """Check status of running experiments."""
    cfg = _get_config(args)
    output_dir = getattr(args, "output_dir", None)

    if output_dir:
        # Check specific experiment
        _check_one(cfg, output_dir)
    elif _is_remote(cfg):
        # List remote screen sessions
        _list_remote_screens(cfg)
    else:
        # Local: check common checkpoint patterns
        _list_local_experiments()


def _check_one(cfg: dict, output_dir: str) -> None:
    """Check status of a single experiment by output_dir."""
    done_path = f"{output_dir}/.done"
    status_path = f"{output_dir}/.status"

    if _is_remote(cfg):
        remote_dir = cfg["remote_dir"]
        done_cmd = f"cat {remote_dir}/{done_path} 2>/dev/null || echo __NOTFOUND__"
        status_cmd = f"cat {remote_dir}/{status_path} 2>/dev/null || echo __NOTFOUND__"
        try:
            r_done = _run_remote(cfg, done_cmd, check=False, timeout=10)
            r_status = _run_remote(cfg, status_cmd, check=False, timeout=10)
        except subprocess.TimeoutExpired:
            print(json.dumps({"output_dir": output_dir, "status": "unknown", "error": "timeout"}))
            return
        done_text = r_done.stdout.strip()
        status_text = r_status.stdout.strip()
    else:
        done_file = Path(done_path)
        status_file = Path(status_path)
        done_text = done_file.read_text().strip() if done_file.exists() else "__NOTFOUND__"
        status_text = status_file.read_text().strip() if status_file.exists() else "__NOTFOUND__"

    if done_text == "__NOTFOUND__":
        if status_text == "__NOTFOUND__":
            result = {"output_dir": output_dir, "status": "not_found"}
        else:
            result = {"output_dir": output_dir, "status": "running"}
            _parse_kv(status_text, result)
    else:
        result = {"output_dir": output_dir}
        _parse_kv(done_text, result)
        exit_code = result.get("EXIT_CODE", result.get("exit_code", ""))
        result["status"] = "completed" if str(exit_code) == "0" else "failed"

    print(json.dumps(result, indent=2))


def _parse_kv(text: str, target: dict) -> None:
    """Parse KEY=VALUE lines into a dict."""
    for line in text.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            target[k.strip().lower()] = v.strip()


def _list_remote_screens(cfg: dict) -> None:
    """List screen sessions on remote host."""
    prefix = cfg["screen_prefix"]
    try:
        r = _run_remote(cfg, "screen -ls", check=False, timeout=10)
    except subprocess.TimeoutExpired:
        print(json.dumps({"experiments": [], "error": "timeout"}))
        return

    sessions = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if f".{prefix}_" in line or f".{prefix}" in line:
            # Extract session name
            m = re.match(r"(\d+)\.(\S+)\s+\((\w+)\)", line)
            if m:
                sessions.append({
                    "pid": m.group(1),
                    "name": m.group(2),
                    "state": m.group(3).lower(),
                })
    print(json.dumps({"host": cfg["host"], "experiments": sessions}, indent=2))


def _list_local_experiments() -> None:
    """List local experiments by scanning for .status files."""
    experiments = []
    seen_dirs: set[str] = set()
    # Scan common patterns
    for pattern_dir in [Path("checkpoints"), Path(".")]:
        if not pattern_dir.exists():
            continue
        for status_file in sorted(pattern_dir.glob("**/.status")):
            out_dir = str(status_file.parent.resolve())
            if out_dir in seen_dirs:
                continue
            seen_dirs.add(out_dir)
            done_file = status_file.parent / ".done"
            entry = {"output_dir": str(status_file.parent)}
            _parse_kv(status_file.read_text(), entry)
            if done_file.exists():
                _parse_kv(done_file.read_text(), entry)
                exit_code = entry.get("exit_code", "")
                entry["status"] = "completed" if str(exit_code) == "0" else "failed"
            else:
                entry["status"] = "running"
            experiments.append(entry)
    print(json.dumps({"experiments": experiments}, indent=2))


def cmd_collect(args) -> None:
    """Collect results from a remote experiment."""
    cfg = _get_config(args)
    output_dir = args.output_dir
    local_dir = args.local_dir or output_dir

    if not _is_remote(cfg):
        # Local: nothing to collect, just verify
        done = Path(output_dir) / ".done"
        if done.exists():
            print(json.dumps({"collected": True, "local_dir": output_dir, "mode": "local"}))
        else:
            print(json.dumps({"collected": False, "status": "still running", "mode": "local"}))
        return

    target = _ssh_target(cfg)
    remote_dir = cfg["remote_dir"]
    remote_path = f"{target}:{remote_dir}/{output_dir}/"
    local_path = Path(local_dir)
    local_path.mkdir(parents=True, exist_ok=True)

    rsync_cmd = [
        "rsync", "-az",
        remote_path,
        f"{local_path}/",
    ]

    try:
        r = _run_local(rsync_cmd, check=False, timeout=120)
        if r.returncode != 0:
            print(json.dumps({"collected": False, "error": f"rsync failed: {r.stderr.strip()}"}))
            sys.exit(1)
    except subprocess.TimeoutExpired:
        print(json.dumps({"collected": False, "error": "rsync timed out"}))
        sys.exit(1)

    # List collected files
    files = [str(p.relative_to(local_path)) for p in local_path.rglob("*") if p.is_file()]
    print(json.dumps({
        "collected": True,
        "local_dir": str(local_path),
        "files": files[:50],
        "mode": "remote",
    }, indent=2))


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="research_agent.deploy",
        description="GPU-aware experiment deployment (local + remote)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Shared remote args
    def add_remote_args(p):
        p.add_argument("--host", default=None, help="Remote GPU host (default: local)")
        p.add_argument("--user", default=None, help="SSH username")
        p.add_argument("--remote-dir", default=None, help="Remote working directory")
        p.add_argument("--gpu-mem-min", type=int, default=None, help="Min free GPU memory in MB")

    # preflight
    p_pf = sub.add_parser("preflight", help="Check GPU availability")
    add_remote_args(p_pf)
    p_pf.set_defaults(func=cmd_preflight)

    # launch
    p_launch = sub.add_parser("launch", help="Launch experiment")
    p_launch.add_argument("script", help="Experiment script to run")
    p_launch.add_argument("output_dir", help="Output/checkpoint directory")
    p_launch.add_argument("--gpu", default=None, help="GPU ID (default: auto-select)")
    add_remote_args(p_launch)
    p_launch.set_defaults(func=cmd_launch)

    # status
    p_status = sub.add_parser("status", help="Check experiment status")
    p_status.add_argument("--output-dir", default=None, help="Specific experiment dir to check")
    add_remote_args(p_status)
    p_status.set_defaults(func=cmd_status)

    # collect
    p_collect = sub.add_parser("collect", help="Collect results from remote")
    p_collect.add_argument("output_dir", help="Remote output directory to collect")
    p_collect.add_argument("--local-dir", default=None, help="Local destination (default: same path)")
    add_remote_args(p_collect)
    p_collect.set_defaults(func=cmd_collect)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
