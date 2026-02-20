# Research Agent

A project-agnostic autonomous research loop for Claude Code. All tooling is **pure Python/bash** (no API keys, no Node.js). A live **tmux Claude Code session** orchestrates the loop and collects user feedback.

---

## Table of Contents

- [Overview](#overview)
- [Components](#components)
- [Requirements](#requirements)
- [Activation (Step-by-Step)](#activation-step-by-step)
- [Architecture](#architecture)
- [Iteration Protocol](#iteration-protocol)
- [CLI Reference](#cli-reference)
- [Monitoring Progress](#monitoring-progress)
- [Git Workflow](#git-workflow)
- [State File Schema](#state-file-schema)
- [Customization](#customization)

---

## Overview

You define a research goal. Claude Code autonomously searches literature, implements changes, runs experiments, and tracks everything via git. After each iteration, it presents results and **waits for your feedback** before continuing. You stay in control; the agent does the grunt work.

## Components

| File | Language | Purpose |
|------|----------|---------|
| `search_papers.py` | Python (stdlib) | Academic paper search via Semantic Scholar + arXiv APIs |
| `state.py` | Python (stdlib) | Persistent JSON state + auto-updates `progress.md` |
| `git_ops.py` | Python (stdlib) | Branch per iteration, structured commits, merge best to main |
| `run_and_wait.sh` | Bash | Experiment runner with `.done` completion marker |
| `protocol.md` | Markdown | Research loop protocol (append to your project's CLAUDE.md) |

## Requirements

- **Python 3.10+** (uses `int | None` syntax)
- **Claude Code CLI** (`npm install -g @anthropic-ai/claude-code`) with an active subscription
- **tmux** (for the live interactive session)
- **git** (for iteration tracking)
- No API keys needed — Semantic Scholar and arXiv APIs are free and unauthenticated

---

## Activation (Step-by-Step)

### Step 1: Make the package importable

Either copy into your project or add the parent directory to `PYTHONPATH`:

```bash
# Option A: Copy
cp -r /data/humanBodyProject/new_proj/research_agent/ /path/to/your/project/

# Option B: PYTHONPATH (add to your .bashrc / .zshrc for persistence)
export PYTHONPATH="/data/humanBodyProject/new_proj:$PYTHONPATH"
```

### Step 2: Append the protocol to your project's CLAUDE.md

This tells Claude Code how to run the research loop:

```bash
cd /path/to/your/project
cat research_agent/protocol.md >> CLAUDE.md
```

Edit the appended section to customize metric names, experiment scripts, and file paths for your project.

### Step 3: Create `progress.md` in your project directory

Write your research goal and constraints. The agent will never touch the content above the sentinel line — it only appends tracking data below.

```bash
cd /path/to/your/project
cat > progress.md << 'EOF'
# Research Goal

Improve heart segmentation 3D Dice above 0.92 using adapter architecture changes.

## Constraints
- Keep parameter count under 1M
- Must converge within 200 epochs
- Base architecture: xOD_with_NullspaceBias in models/sam/modeling/common.py
EOF
```

### Step 4: Start a tmux session and launch Claude Code

```bash
tmux new -s research
cd /path/to/your/project
conda activate your_env        # activate your ML environment
claude                         # start Claude Code interactively
```

### Step 5: Tell Claude to start the loop

Inside the Claude Code session, type:

```
Start the research loop from progress.md
```

Claude will:
1. Read your goal from `progress.md`
2. Initialize `state.json` (`python -m research_agent.state init --progress progress.md`)
3. Record your baseline results
4. Begin the iteration cycle: search → hypothesize → implement → experiment → analyze → **ask you for feedback**

### Step 6: Provide feedback when prompted

After each iteration, Claude presents a summary and waits. You can:
- **Steer direction:** "Focus on token-wise adaptation next"
- **Approve:** "Looks good, continue"
- **Reject:** "Revert this change, try increasing spd_rank instead"
- **Stop:** "Stop the loop, let me review"

### tmux Controls

| Action | Command |
|--------|---------|
| Detach (leave running) | `Ctrl-b d` |
| Reattach | `tmux attach -t research` |
| List sessions | `tmux ls` |
| Kill session | `tmux kill-session -t research` |

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  tmux session                                            │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Claude Code (interactive)                         │  │
│  │                                                    │  │
│  │  Orchestrates the loop:                            │  │
│  │  ┌──────────────────────────────────────────────┐  │  │
│  │  │ 1. Read state.json (recover context)         │  │  │
│  │  │ 2. python search_papers.py → JSON            │  │  │
│  │  │ 3. Evaluate papers, form hypothesis          │  │  │
│  │  │ 4. python git_ops.py branch-start            │  │  │
│  │  │ 5. Implement ONE change in code              │  │  │
│  │  │ 6. python git_ops.py commit-code + push      │  │  │
│  │  │ 7. bash run_and_wait.sh (background)         │  │  │
│  │  │ 8. Poll for .done marker                     │  │  │
│  │  │ 9. python state.py add-iteration             │  │  │
│  │  │ 10. python git_ops.py commit-results         │  │  │
│  │  │ 11. Present summary to user                  │  │  │
│  │  │ 12. *** WAIT FOR USER FEEDBACK ***           │  │  │
│  │  │ 13. Repeat                                   │  │  │
│  │  └──────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  User: watches live, provides feedback at step 12        │
│  Detach: Ctrl-b d  |  Reattach: tmux attach -t research  │
└──────────────────────────────────────────────────────────┘
```

**Python tools** handle all data operations (search, state, git). **Claude Code** handles intelligence (evaluation, hypothesis formation, code implementation, result analysis) and the interactive feedback loop.

---

## Iteration Protocol

Each iteration follows this sequence. Claude executes these steps autonomously, using the Python CLI tools via Bash.

### First-time setup

1. Read `progress.md` to understand the goal.
2. Initialize state:
   ```bash
   python -m research_agent.state init --progress progress.md --metric "test_3d_dice"
   ```
3. Record baseline:
   ```bash
   python -m research_agent.state set-baseline \
     --checkpoint checkpoints/baseline \
     --metrics '{"test_3d_dice": 0.905, "test_3d_nsd": 0.940}'
   ```

### Each iteration

| Step | Action | Tool |
|------|--------|------|
| 1 | Read state (recover context) | `python -m research_agent.state read` |
| 2 | Search literature | `python research_agent/search_papers.py "query" results/search_iterN.json` |
| 3 | Evaluate results, form hypothesis | Claude (reads JSON, uses WebSearch to supplement) |
| 4 | Create git branch | `python -m research_agent.git_ops branch-start --iteration N --change "..."` |
| 5 | Implement ONE change | Claude (edits code) |
| 6 | Commit code + push | `python -m research_agent.git_ops commit-code ...` then `push` |
| 7 | Launch experiment | `bash research_agent/run_and_wait.sh <script> <checkpoint_dir>` |
| 8 | Poll for completion | `test -f <checkpoint_dir>/.done && cat <checkpoint_dir>/.done \|\| echo RUNNING` |
| 9 | Analyze results | Claude (reads eval logs, compares to baseline/best) |
| 10 | Record iteration | `python -m research_agent.state add-iteration ...` |
| 11 | Commit results | `python -m research_agent.git_ops commit-results --iteration N --state state.json` |
| 12 | Merge if best | `python -m research_agent.git_ops merge-best --state state.json` |
| 13 | Present summary | Claude (shows results to user) |
| 14 | Wait for feedback | User responds in tmux session |

---

## CLI Reference

### search_papers.py — Literature Search

```bash
# Basic search
python research_agent/search_papers.py "query terms" output.json

# With options
python research_agent/search_papers.py "orthogonal adapters ViT" results.json \
  --limit 15 \
  --year-min 2023 \
  --related-to 2304.12620     # arXiv ID for recommendations
  --state state.json           # enrich with project context
```

**Output:** JSON array with `title`, `authors`, `year`, `abstract`, `url`, `arxiv_id`, `citations`, `source`.

### state.py — State Management

```bash
# Initialize from progress.md
python -m research_agent.state init --progress progress.md --metric test_3d_dice

# Initialize with explicit goal
python -m research_agent.state init --goal "improve dice above 0.92" --metric test_3d_dice

# Read full state
python -m research_agent.state read

# Read specific field
python -m research_agent.state read --field best

# Record baseline
python -m research_agent.state set-baseline \
  --checkpoint checkpoints/baseline \
  --metrics '{"test_3d_dice": 0.905, "test_3d_nsd": 0.940}'

# Record iteration
python -m research_agent.state add-iteration \
  --hypothesis "Higher SPD rank increases expressiveness" \
  --change "spd_rank 4 -> 8" \
  --checkpoint checkpoints/exp1 \
  --metric-name test_3d_dice --metric-value 0.912 \
  --metric-name test_3d_nsd --metric-value 0.945 \
  --papers "LoRA 2021" "OFT 2023" \
  --feedback "marginal gain, try token-wise FiLM next"

# Update progress note
python -m research_agent.state update-progress --status "Waiting for experiment 3"

# Generate markdown report
python -m research_agent.state report
python -m research_agent.state report --output research_report.md
```

**Environment variables:**
- `RESEARCH_STATE_FILE` — override state file path (default: `state.json`)
- `RESEARCH_PROGRESS_FILE` — override progress file path (default: `progress.md`)

### git_ops.py — Git Workflow

```bash
# Create iteration branch from main
python -m research_agent.git_ops branch-start --iteration 3 --change "enable token-wise FiLM"

# Commit code changes (before experiment)
python -m research_agent.git_ops commit-code --iteration 3 \
  --hypothesis "Token-wise FiLM enables per-token adaptation" \
  --change "cond_scale_tokenwise=True" \
  --papers "FiLM 2018" "AdaptFormer 2022" \
  --checkpoint "checkpoints/exp_tokenfilm"

# Commit results (after experiment)
python -m research_agent.git_ops commit-results --iteration 3 --state state.json

# Merge best iteration into main
python -m research_agent.git_ops merge-best --state state.json

# Push current branch / all branches
python -m research_agent.git_ops push
python -m research_agent.git_ops push-all

# View iteration history
python -m research_agent.git_ops log
```

### run_and_wait.sh — Experiment Runner

```bash
# Launch (typically in background from Claude):
bash research_agent/run_and_wait.sh scripts/my_experiment.sh checkpoints/my_exp/

# Creates:
#   checkpoints/my_exp/.status    — start time, script path, PID
#   checkpoints/my_exp/.done      — exit code, completion time (when finished)
#   checkpoints/my_exp/training.log — full stdout+stderr
```

**Polling pattern** (used by Claude):
```bash
test -f checkpoints/my_exp/.done && cat checkpoints/my_exp/.done || echo RUNNING
```

---

## Monitoring Progress

### From any terminal (outside the tmux session)

```bash
# Quick status — human-readable
cat progress.md

# Full machine-readable state
python -m research_agent.state read

# Just the best result
python -m research_agent.state read --field best

# Markdown report
python -m research_agent.state report

# Git log of all iterations
python -m research_agent.git_ops log

# Check if experiment is running
test -f checkpoints/my_exp/.done && cat checkpoints/my_exp/.done || echo RUNNING
```

### progress.md auto-updated format

```markdown
# Research Goal                          <-- your text, never touched

(your goal and constraints)

<!-- AGENT PROGRESS BELOW — auto-updated, do not edit below this line -->

## Status

| | |
|---|---|
| **Primary metric** | `test_3d_dice` |
| **Baseline** | 0.905 |
| **Best** | 0.921 (iter 3) |
| **Iterations** | 5 |

> **Current direction:** Trying token-wise FiLM

## Iteration Log

| # | Change | test_3d_dice | vs baseline | Feedback |
|---|--------|-------------|------------|----------|
| 1 | spd_rank 4->8 | 0.908 | +0.0032 | marginal gain |
| 2 | token-wise FiLM | 0.915 | +0.0102 | promising |
| 3 | FiLM + bias scale | 0.921 | +0.0162 | new best |

## Recent Iterations (detail)

### Iteration 3 — 2026-02-20 14:30:00
- **Hypothesis:** Combining token-wise FiLM with larger bias scale
- **Change:** cond_scale_tokenwise=True, bias_max_scale=0.1
- **Papers:** FiLM 2018, AdaptFormer 2022
- **Checkpoint:** `checkpoints/exp_film_bias`
- **Metrics:** {"test_3d_dice": 0.921, "test_3d_nsd": 0.955}
- **Feedback:** new best, significant improvement
```

---

## Git Workflow

Every iteration is a **git branch** with structured commits. `main` always reflects the best-performing configuration.

### Branch structure

```
main                          ← best configuration
├── iter/1-spd-rank-increase  ← each iteration is a branch
├── iter/2-tokenwise-film     ← 2 commits per branch: code + results
└── iter/3-film-bias-scale
```

### Commit message format

**Code commit** (before experiment):
```
iter/3: cond_scale_tokenwise=True, bias_max_scale=0.1

Hypothesis: Combining token-wise FiLM with larger bias scale
Change: cond_scale_tokenwise=True, bias_max_scale=0.1
Papers: FiLM 2018, AdaptFormer 2022
Checkpoint: checkpoints/exp_film_bias

Status: experiment pending
```

**Results commit** (after experiment):
```
iter/3: results — test_3d_dice: 0.921 (+0.0162)

Results:
  test_3d_dice: 0.921 (+0.0162 vs baseline)
  test_3d_nsd: 0.955 (+0.0150 vs baseline)

Hypothesis: Combining token-wise FiLM with larger bias scale
Change: cond_scale_tokenwise=True, bias_max_scale=0.1
Feedback: new best, significant improvement

*** NEW BEST ***
```

### Commands reference

| Command | When | What |
|---------|------|------|
| `branch-start` | Before coding | Creates `iter/N-slug` from main |
| `commit-code` | After coding, before experiment | Structured commit with hypothesis |
| `commit-results` | After experiment | Commit with metrics + delta |
| `merge-best` | When new best found | Merges best branch into main |
| `push` | After any commit | Pushes current branch |
| `push-all` | Periodically | Pushes main + all iter branches |
| `log` | Anytime | Shows all iteration commits |

---

## State File Schema

`state.json` — persistent across context compression and session restarts.

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
    "metrics": {"test_3d_dice": 0.921, "test_3d_nsd": 0.955},
    "experiment": "cond_scale_tokenwise=True, bias_max_scale=0.1"
  },
  "iterations": [
    {
      "id": 1,
      "timestamp": "2026-02-20 10:30:00",
      "hypothesis": "Increasing SPD rank adds expressiveness",
      "change_summary": "spd_rank 4 -> 8",
      "papers_referenced": ["LoRA 2021", "OFT 2023"],
      "checkpoint": "checkpoints/exp_spd_rank8",
      "metrics": {"test_3d_dice": 0.908, "test_3d_nsd": 0.943},
      "feedback": "marginal gain, try token-wise FiLM next"
    }
  ]
}
```

---

## Customization

### Different primary metric

```bash
python -m research_agent.state init --progress progress.md --metric val_loss
```

### Different experiment runner

Edit `run_and_wait.sh` or write your own — just ensure it creates a `<dir>/.done` file on completion.

### GitLab remote

Set up a remote for git tracking:

```bash
cd /path/to/your/project
git remote add origin https://gitlab.example.com/user/repo.git
```

The `git_ops.py push` commands will use whatever remote is configured.

### Override file locations

```bash
export RESEARCH_STATE_FILE=my_state.json
export RESEARCH_PROGRESS_FILE=my_progress.md
```

---

## Rules (for Claude)

These are enforced by `protocol.md` when appended to your CLAUDE.md:

1. **ONE change per iteration** — isolate variables for clean comparison
2. **NEVER overwrite checkpoints** — each iteration gets a unique directory
3. **ALWAYS commit before experiments** — code must be in git before long jobs start
4. **Re-read state.json** at the start of every iteration to recover context
5. **Primary metric drives decisions** — always report secondary metrics too
6. **Cite papers** — note references when a technique comes from literature
7. **Never edit the user's goal** in `progress.md`
8. **Push after every commit** — keep the remote in sync
9. **Wait for user feedback** — never start the next iteration without user input
