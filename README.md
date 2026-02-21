# Research Agent

A project-agnostic autonomous research loop for Claude Code. The **orchestrator** Claude Code session runs in tmux and controls two **worker** Claude Code sessions (paper search + code implementation) that run in separate tmux windows. No API key needed — uses your Claude subscription.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Components](#components)
- [Requirements](#requirements)
- [Activation (Step-by-Step)](#activation-step-by-step)
- [Iteration Protocol](#iteration-protocol)
- [CLI Reference](#cli-reference)
- [Monitoring Progress](#monitoring-progress)
- [Git Workflow](#git-workflow)
- [State File Schema](#state-file-schema)
- [Customization](#customization)

---

## Overview

You define a research goal. Claude Code autonomously searches literature, implements changes, runs experiments, and tracks everything via git. After each iteration, it presents results and **waits for your feedback** (or auto-continues in autonomous mode). You stay in control; the agent does the grunt work.

## Architecture

```
tmux session "research"
┌─────────────────────────────────────────────────────────┐
│  window 0: Claude Code (ORCHESTRATOR)                    │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Controls the loop:                                  │ │
│  │  1. Read state.json (recover context)               │ │
│  │  2. Launch Function A → papers (tmux "search")      │ │
│  │  3. Launch Function B → code change (tmux "impl")   │ │
│  │  4. Review changes, git branch + commit             │ │
│  │  5. Launch experiment (background)                  │ │
│  │  6. Poll for completion                             │ │
│  │  7. Analyze, record, commit results                 │ │
│  │  8. Merge best to main                              │ │
│  │  9. Summarize to user                               │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  window "search": claude -p (Function A worker)          │
│  window "implement": claude -p (Function B worker)       │
│                                                          │
│  User: watches, provides feedback, Ctrl-b d to detach    │
└─────────────────────────────────────────────────────────┘
```

**Key insight:** Workers run in separate tmux windows (not nested inside the orchestrator), so `claude -p` works without nesting issues. The Python scripts handle tmux window creation, prompt piping, and output polling automatically.

## Components

| File | Purpose |
|------|---------|
| `function_a.py` | **Function A**: Paper search — spawns `claude -p` worker in tmux, uses WebSearch |
| `function_b.py` | **Function B**: Code implementation — spawns `claude -p` worker in tmux, edits files |
| `search_papers.py` | Fallback paper search via Semantic Scholar + arXiv APIs (no Claude needed) |
| `state.py` | Persistent JSON state + auto-updates `progress.md` |
| `git_ops.py` | Branch per iteration, structured commits, merge best to main |
| `run_and_wait.sh` | Experiment runner with `.done` completion marker |
| `protocol.md` | Research loop protocol (append to your project's CLAUDE.md) |

## Requirements

- **Python 3.10+**
- **Claude Code CLI** (`claude`) with an active subscription
- **tmux** (for orchestrator + worker windows)
- **git** (for iteration tracking)

No API key needed. Workers use `claude -p` (pipe mode) which authenticates via your Claude subscription.

---

## Activation (Step-by-Step)

### Step 1: Make the package importable

```bash
# Option A: Copy into your project
cp -r /data/humanBodyProject/new_proj/research_agent/ /path/to/your/project/

# Option B: PYTHONPATH (add to .bashrc for persistence)
export PYTHONPATH="/data/humanBodyProject/new_proj:$PYTHONPATH"
```

### Step 2: Append the protocol to your project's CLAUDE.md

```bash
cd /path/to/your/project
cat research_agent/protocol.md >> CLAUDE.md
```

Edit the appended section to customize metric names, experiment scripts, and file paths.

### Step 3: Create `progress.md` in your project directory

```bash
cat > progress.md << 'EOF'
# Research Goal

Improve heart segmentation 3D Dice above 0.92 using adapter architecture changes.

## Constraints
- Keep parameter count under 1M
- Must converge within 200 epochs
EOF
```

### Step 4: Start tmux and launch Claude Code

```bash
tmux new -s research
cd /path/to/your/project
conda activate your_env
claude
```

### Step 5: Tell Claude to start the loop

```
# Interactive mode (default):
Start the research loop from progress.md

# Autonomous mode:
Start the research loop from progress.md, run autonomously
```

### Step 6: Provide feedback or monitor

**Interactive mode** — Claude presents a summary after each iteration. You can:
- Steer: "Focus on token-wise adaptation next"
- Approve: "Looks good, continue"
- Reject: "Revert this, try increasing spd_rank instead"
- Go autonomous: "Continue autonomously"

**Autonomous mode** — Claude continues without waiting. Interrupt anytime:
- Type to give new instructions
- "Wait for my feedback from now on" to switch to interactive

### tmux Controls

| Action | Command |
|--------|---------|
| Detach (leave running) | `Ctrl-b d` |
| Reattach | `tmux attach -t research` |
| List sessions | `tmux ls` |
| See worker windows | `Ctrl-b w` (window list) |

---

## Iteration Protocol

| Step | Action | Tool |
|------|--------|------|
| 1 | Read state (recover context) | `python -m research_agent.state read` |
| 2 | *(Optional)* Function A — find papers | `python research_agent/function_a.py ...` |
| 3 | Create git branch | `python -m research_agent.git_ops branch-start ...` |
| 4 | Function B — implement change | `python research_agent/function_b.py ...` |
| 5 | Review changes | `git diff` |
| 6 | Commit code + push | `python -m research_agent.git_ops commit-code ...` + `push` |
| 7 | Launch experiment | `bash research_agent/run_and_wait.sh <script> <dir>` |
| 8 | Poll for completion | `test -f <dir>/.done && cat <dir>/.done \|\| echo RUNNING` |
| 9 | Analyze results | Read eval logs, compare to baseline/best |
| 10 | Record iteration | `python -m research_agent.state add-iteration ...` |
| 11 | Commit results + push | `python -m research_agent.git_ops commit-results ...` + `push` |
| 12 | Merge if best | `python -m research_agent.git_ops merge-best ...` + `push` |
| 13 | Summarize to user | Present results and proposed next steps |
| 14 | Next iteration | Wait for feedback OR auto-decide |

**When to search papers (Function A):**
- Exploring a new technique
- Previous iterations plateaued, need fresh ideas
- User asks about literature

**When to skip search:**
- User gave a specific instruction
- Next step is obvious from previous results

---

## CLI Reference

### function_a.py — Paper Search (tmux worker)

```bash
# Search with explicit topic
python research_agent/function_a.py "orthogonal adapter fine-tuning" results/search.json

# With project context (auto-deduplicates)
python research_agent/function_a.py "PEFT medical segmentation" results/search.json --state state.json

# Auto-generate topic from last iteration
python research_agent/function_a.py --auto results/search.json --state state.json

# Custom timeout (default: 300s)
python research_agent/function_a.py "topic" results/search.json --timeout 600
```

**How it works:** Writes a prompt file, launches `claude -p` in tmux window "search", polls for output, parses JSON array of papers.

### function_b.py — Code Implementation (tmux worker)

```bash
# From paper results
python research_agent/function_b.py --papers results/search.json --project-dir .

# From direct instruction
python research_agent/function_b.py --instruction "increase spd_rank to 8" --project-dir .

# With context and file focus
python research_agent/function_b.py --papers results/search.json --project-dir . \
  --state state.json --files models/sam/modeling/common.py cfg.py

# Custom timeout (default: 600s)
python research_agent/function_b.py --instruction "..." --project-dir . --timeout 900
```

**How it works:** Writes a prompt file, launches `claude -p` in tmux window "implement" (from the project directory), polls for output, parses change summary JSON.

**Output:** JSON to stdout: `{hypothesis, change_summary, files_modified, papers_used}`

### search_papers.py — Fallback Search (no Claude needed)

```bash
python research_agent/search_papers.py "query" --limit 10 --year-min 2023
```

Uses Semantic Scholar + arXiv APIs directly. No relevance scoring.

### state.py — State Management

```bash
python -m research_agent.state init --progress progress.md --metric test_3d_dice
python -m research_agent.state read
python -m research_agent.state read --field best
python -m research_agent.state set-baseline --checkpoint "..." --metrics '{"test_3d_dice": 0.905}'
python -m research_agent.state add-iteration \
  --hypothesis "..." --change "..." --checkpoint "..." \
  --metric-name test_3d_dice --metric-value 0.912 \
  --feedback "..."
python -m research_agent.state report
```

### git_ops.py — Git Workflow

```bash
python -m research_agent.git_ops branch-start --iteration 3 --change "enable tokenwise film"
python -m research_agent.git_ops commit-code --iteration 3 --hypothesis "..." --change "..."
python -m research_agent.git_ops commit-results --iteration 3 --state state.json
python -m research_agent.git_ops merge-best --state state.json
python -m research_agent.git_ops push
python -m research_agent.git_ops log
```

### run_and_wait.sh — Experiment Runner

```bash
bash research_agent/run_and_wait.sh scripts/my_exp.sh checkpoints/my_exp/
# Poll: test -f checkpoints/my_exp/.done && cat checkpoints/my_exp/.done || echo RUNNING
```

---

## Monitoring Progress

```bash
# Human-readable status
cat progress.md

# Machine-readable state
python -m research_agent.state read

# Best result only
python -m research_agent.state read --field best

# Git iteration history
python -m research_agent.git_ops log

# Check experiment status
test -f checkpoints/my_exp/.done && cat checkpoints/my_exp/.done || echo RUNNING
```

---

## Git Workflow

```
main                          ← best configuration (merged after each new best)
├── iter/1-spd-rank-increase  ← 2 commits: code + results
├── iter/2-tokenwise-film
└── iter/3-film-bias-scale
```

Each iteration: `branch-start` → `commit-code` → experiment → `commit-results` → (if best) `merge-best`

---

## State File Schema

`state.json` — persists across context compression and session restarts.

```json
{
  "goal": "Improve heart segmentation 3D Dice above 0.92",
  "project_dir": "/path/to/project",
  "created_at": "2026-02-20 10:00:00",
  "primary_metric": "test_3d_dice",
  "baseline": {
    "checkpoint": "checkpoints/baseline",
    "metrics": {"test_3d_dice": 0.905, "test_3d_nsd": 0.940}
  },
  "best": {
    "iteration": 3,
    "metrics": {"test_3d_dice": 0.921},
    "experiment": "tokenwise film + bias scale"
  },
  "iterations": [
    {
      "id": 1, "timestamp": "2026-02-20 10:30:00",
      "hypothesis": "Increasing SPD rank adds expressiveness",
      "change_summary": "spd_rank 4->8",
      "papers_referenced": ["LoRA 2021"],
      "checkpoint": "checkpoints/exp1",
      "metrics": {"test_3d_dice": 0.908},
      "feedback": "marginal gain"
    }
  ]
}
```

---

## Customization

```bash
# Different metric
python -m research_agent.state init --progress progress.md --metric val_loss

# Override file locations
export RESEARCH_STATE_FILE=my_state.json
export RESEARCH_PROGRESS_FILE=my_progress.md
```

For git tracking, configure a remote: `git remote add origin https://...`

---

## Rules (for Claude)

1. **ONE change per iteration** — isolate variables
2. **NEVER overwrite checkpoints** — unique directory per iteration
3. **Create branch + commit BEFORE experiments** — code must be in git first
4. **Re-read state.json** every iteration — recover context after compression
5. **Review Function B's changes** — always `git diff` before committing
6. **Push after every commit** — keep remote in sync
7. **Never edit the user's goal** in `progress.md`
8. **Cite papers** when techniques come from literature
9. **Present clear summaries** — user is watching in tmux
