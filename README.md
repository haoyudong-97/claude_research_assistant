# Research Agent

A project-agnostic autonomous research loop for Claude Code. All tooling is Python-based. A **live tmux Claude Code session** orchestrates the loop and collects your feedback.

## Components

| File | Purpose |
|------|---------|
| `search_papers.py` | Academic paper search via Semantic Scholar + arXiv APIs (pure Python) |
| `run_and_wait.sh` | Bash wrapper: runs experiment, writes `.done` marker on completion |
| `state.py` | CLI: persistent JSON state + auto-updates `progress.md` |
| `git_ops.py` | Git workflow: branch per iteration, structured commits, merge best to main |
| `protocol.md` | Research loop protocol template (append to your CLAUDE.md) |

## Requirements

- Python 3.10+
- Claude Code CLI (for the live tmux session)
- tmux
- No API keys needed (Semantic Scholar + arXiv are free)

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
│  │  │ 2. python search_papers.py → JSON results    │  │  │
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
│  User watches, provides feedback at step 12              │
│  Detach: Ctrl-b d  |  Reattach: tmux attach -t research  │
└──────────────────────────────────────────────────────────┘
```

**Everything except the interactive Claude session is Python/bash:**
- Paper search: `search_papers.py` (Semantic Scholar + arXiv APIs, stdlib only)
- State tracking: `state.py` (JSON + markdown)
- Git workflow: `git_ops.py` (subprocess calls to git)
- Experiment runner: `run_and_wait.sh` (bash)

**Claude Code's role:** Orchestrate the loop, read/evaluate search results, implement code changes, analyze experiment results, present summaries, and collect user feedback.

## How It Works

### 1. User creates `progress.md` with the goal

```markdown
# Research Goal

Improve heart segmentation 3D Dice above 0.92 using adapter architecture changes.

## Constraints
- Keep parameter count under 1M
- Must converge within 200 epochs
```

### 2. Start in tmux

```bash
tmux new -s research
claude
> Start the research loop from progress.md
```

### 3. Paper search (Python, no auth)

```bash
python research_agent/search_papers.py \
  "Householder orthogonal adapters parameter-efficient fine-tuning" \
  results/search_iter1.json \
  --limit 10 --year-min 2023

# Get recommendations based on a known paper:
python research_agent/search_papers.py \
  "nullspace projection PEFT" \
  results/search_iter1_related.json \
  --related-to 2304.12620
```

Output format:
```json
[
  {
    "title": "Paper Title",
    "authors": "First Author et al.",
    "year": 2024,
    "abstract": "First 2-3 sentences...",
    "url": "https://...",
    "arxiv_id": "2401.12345",
    "citations": 42,
    "source": "semantic_scholar"
  }
]
```

Claude then reads these results in the tmux session, evaluates relevance to the project, and uses them to form hypotheses.

### 4. Git tracks every change

Each iteration is a **git branch** with structured commits.

```bash
# Create branch for iteration 3
python -m research_agent.git_ops branch-start --iteration 3 --change "enable token-wise FiLM"

# Commit code before experiment:
python -m research_agent.git_ops commit-code --iteration 3 \
  --hypothesis "Token-wise FiLM enables per-token adaptation" \
  --change "cond_scale_tokenwise=True" \
  --papers "FiLM 2018" "AdaptFormer 2022"

# Push, run experiment, then commit results:
python -m research_agent.git_ops push
python -m research_agent.git_ops commit-results --iteration 3 --state state.json

# If new best, merge to main:
python -m research_agent.git_ops merge-best --state state.json
python -m research_agent.git_ops push
```

### 5. progress.md gets auto-updated

```markdown
# Research Goal                          <-- user-written, never touched
(user's goal text)

<!-- AGENT PROGRESS BELOW — auto-updated, do not edit below this line -->

## Status                                <-- agent-managed section
| | |
|---|---|
| **Primary metric** | `test_3d_dice` |
| **Baseline** | 0.905 |
| **Best** | 0.921 (iter 3) |
| **Iterations** | 5 |

## Iteration Log
| # | Change | test_3d_dice | vs baseline | Feedback |
|---|--------|-------------|------------|----------|
| 1 | spd_rank 4->8 | 0.908 | +0.0032 | marginal gain |
| 2 | token-wise FiLM | 0.915 | +0.0102 | promising |
```

## Quick Start

```bash
# 1. Create progress.md with your research goal
cat > progress.md << 'EOF'
# Research Goal
Improve heart segmentation 3D Dice above 0.92.
EOF

# 2. Start tmux + Claude Code
tmux new -s research
claude
# > Start the research loop from progress.md
```

### Manual CLI usage

```bash
# Initialize state:
python -m research_agent.state init --progress progress.md --metric test_3d_dice

# Search papers:
python research_agent/search_papers.py "adapter PEFT medical segmentation" results/search.json

# Record baseline:
python -m research_agent.state set-baseline \
  --checkpoint checkpoints/baseline \
  --metrics '{"test_3d_dice": 0.905, "test_3d_nsd": 0.940}'

# Run experiment:
bash research_agent/run_and_wait.sh scripts/my_experiment.sh checkpoints/exp1/

# Record iteration:
python -m research_agent.state add-iteration \
  --hypothesis "Higher SPD rank increases expressiveness" \
  --change "spd_rank 4 -> 8" \
  --checkpoint checkpoints/exp1 \
  --metric-name test_3d_dice --metric-value 0.912 \
  --feedback "small gain, try token-wise FiLM next"

# Generate report:
python -m research_agent.state report
```

## Integration with a Project

1. **Copy into your project** (or add parent to PYTHONPATH):
   ```bash
   cp -r /data/humanBodyProject/new_proj/research_agent/ /path/to/project/
   ```

2. **Create `progress.md`** with your research goal.

3. **Append protocol to CLAUDE.md**:
   ```bash
   cat research_agent/protocol.md >> CLAUDE.md
   ```

4. **Start a session**:
   ```bash
   tmux new -s research
   claude
   > Start the research loop from progress.md
   ```

## State File

Stored in `state.json` (override with `RESEARCH_STATE_FILE` env var).

```json
{
  "goal": "...",
  "project_dir": "...",
  "created_at": "2026-02-20 10:00:00",
  "primary_metric": "test_3d_dice",
  "baseline": {"checkpoint": "...", "metrics": {...}},
  "best": {"iteration": 3, "metrics": {...}, "experiment": "..."},
  "iterations": [...]
}
```
