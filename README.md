# Research Agent

A project-agnostic autonomous research loop for Claude Code. Provides intelligent literature search via a Claude agent, experiment tracking, and a protocol that Claude follows to iteratively improve ML experiments.

## Components

| File | Purpose |
|------|---------|
| `search_papers.py` | CLI entry point: builds prompt, calls search_agent.mjs |
| `search_agent.mjs` | Claude Code SDK agent: WebSearch, evaluates, ranks papers |
| `run_and_wait.sh` | Bash wrapper: runs experiment, writes `.done` marker on completion |
| `state.py` | CLI: persistent JSON state + auto-updates `progress.md` |
| `git_ops.py` | Git workflow: branch per iteration, structured commits, merge best to main |
| `protocol.md` | Research loop protocol template (append to your CLAUDE.md) |

## Requirements

- Python 3.10+ (uses `int | None` syntax)
- Node.js 18+ (for the Claude Agent SDK)
- `@anthropic-ai/claude-agent-sdk` npm package (install: `cd research_agent && npm install`)
- `ANTHROPIC_API_KEY` environment variable (get from https://console.anthropic.com/)

## How It Works

### 1. User creates `progress.md` with the goal

```markdown
# Research Goal

Improve heart segmentation 3D Dice above 0.92 using adapter architecture changes.

## Constraints
- Keep parameter count under 1M
- Must converge within 200 epochs
```

### 2. Agent initializes from it

```bash
python -m research_agent.state init --progress progress.md --metric test_3d_dice
```

### 3. Literature search via Claude agent

Paper search is done by a **Claude agent** via the `@anthropic-ai/claude-agent-sdk`. Requires `ANTHROPIC_API_KEY`. The agent:

- Reads `progress.md` and `state.json` to understand the project
- Plans 3-5 specific search queries targeting different angles of the topic
- Executes web searches and reads paper pages for details
- Evaluates each paper's relevance to the project (scored 1-5)
- Extracts a `key_idea` explaining what we can apply from each paper
- Writes structured JSON results

```bash
python research_agent/search_papers.py \
  "Householder orthogonal adapters for parameter-efficient fine-tuning" \
  results/search_iter1.json \
  --progress progress.md --state state.json
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
    "relevance": 5,
    "relevance_reason": "Why this paper matters for the project",
    "key_idea": "The main takeaway applicable to our work"
  }
]
```

### 4. Git tracks every change

Each iteration is a **git branch** with structured commits. Code changes are committed *before* the experiment runs (so nothing is lost), and results are committed after.

```bash
# Create branch for iteration 3
python -m research_agent.git_ops branch-start --iteration 3 --change "enable token-wise FiLM"

# After making code changes:
python -m research_agent.git_ops commit-code --iteration 3 \
  --hypothesis "Token-wise FiLM enables per-token adaptation" \
  --change "cond_scale_tokenwise=True" \
  --papers "FiLM 2018" "AdaptFormer 2022"

# Push to GitLab before experiment starts:
python -m research_agent.git_ops push

# ... experiment runs ...

# After results are in:
python -m research_agent.git_ops commit-results --iteration 3 --state state.json

# If it's the new best, merge to main:
python -m research_agent.git_ops merge-best --state state.json
python -m research_agent.git_ops push
```

The commit messages encode the full context:
```
iter/3: cond_scale_tokenwise=True

Hypothesis: Token-wise FiLM enables per-token adaptation
Change: cond_scale_tokenwise=True
Papers: FiLM 2018, AdaptFormer 2022
Checkpoint: checkpoints/exp_tokenfilm

Status: experiment pending
```

```
iter/3: results — test_3d_dice: 0.918 (+0.0130)

Results:
  test_3d_dice: 0.918 (+0.0130 vs baseline)
  test_3d_nsd: 0.951 (+0.0110 vs baseline)

Hypothesis: Token-wise FiLM enables per-token adaptation
Change: cond_scale_tokenwise=True
Feedback: significant gain, new best

*** NEW BEST ***
```

### 5. Agent runs experiment iterations

Each iteration: search literature, implement one change, run experiment, record results. Every state change auto-updates `progress.md`, so the user can check progress at any time.

### 5. progress.md gets auto-updated

After each iteration, `progress.md` looks like:

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

> **Current direction:** Trying token-wise FiLM

## Iteration Log

| # | Change | test_3d_dice | vs baseline | Feedback |
|---|--------|-------------|------------|----------|
| 1 | spd_rank 4->8 | 0.908 | +0.0032 | marginal gain |
| 2 | token-wise FiLM | 0.915 | +0.0102 | promising |
...
```

## Quick Start

### Search for papers

```bash
# One-time setup:
cd research_agent && npm install && cd ..

# Search:
python research_agent/search_papers.py \
  "parameter efficient fine-tuning medical segmentation SAM" \
  results/search.json \
  --progress progress.md --state state.json
```

### Initialize a research session

```bash
# From user's progress.md:
python -m research_agent.state init --progress progress.md --metric test_3d_dice

# Or with explicit goal:
python -m research_agent.state init --goal "improve dice above 0.92" --metric test_3d_dice
```

### Record baseline

```bash
python -m research_agent.state set-baseline \
  --checkpoint checkpoints/baseline \
  --metrics '{"test_3d_dice": 0.905, "test_3d_nsd": 0.940}'
```

### Run an experiment

```bash
bash research_agent/run_and_wait.sh scripts/my_experiment.sh checkpoints/exp1/
# Poll:
test -f checkpoints/exp1/.done && cat checkpoints/exp1/.done || echo RUNNING
```

### Record iteration

```bash
python -m research_agent.state add-iteration \
  --hypothesis "Higher SPD rank increases expressiveness" \
  --change "spd_rank 4 -> 8" \
  --checkpoint checkpoints/exp1 \
  --metric-name test_3d_dice --metric-value 0.912 \
  --feedback "small gain, try token-wise FiLM next"
```

### Update progress note

```bash
python -m research_agent.state update-progress --status "Waiting for experiment 3 to finish"
```

### Generate standalone report

```bash
python -m research_agent.state report
python -m research_agent.state report --output research_report.md
```

## Integration with a Project

### Step 1: Make the package importable

```bash
cp -r /data/humanBodyProject/new_proj/research_agent/ /path/to/your/project/
```

Or add the parent to PYTHONPATH:

```bash
export PYTHONPATH="/data/humanBodyProject/new_proj:$PYTHONPATH"
```

### Step 2: Create your progress.md

Write your research goal, constraints, and context. The agent only appends tracking below a sentinel line.

### Step 3: Append protocol to your CLAUDE.md

```bash
cat research_agent/protocol.md >> CLAUDE.md
```

Customize for your project (metric names, experiment scripts, etc.).

### Step 4: Start a research session

In a tmux session with Claude Code:

```
claude
> Start the research loop from progress.md
```

Claude reads your goal, initializes state, and begins the iteration cycle.

## State File

Stored in `state.json` (override with `RESEARCH_STATE_FILE` env var). `progress.md` location can be overridden with `RESEARCH_PROGRESS_FILE`.

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
