# Research Agent — Usage Guide

## Prerequisites

| Requirement | Check command |
|---|---|
| Python 3.10+ | `python3 --version` |
| Claude Code CLI | `claude --version` |
| tmux | `tmux -V` |
| git | `git --version` |

No pip dependencies needed — everything uses Python stdlib.

---

## Quick Start

### 1. Edit your research goal

Open `progress.md` and replace the placeholder with your actual goal:

```markdown
# Research Goal

Improve liver tumor segmentation Dice above 0.90 using architecture modifications.

## Constraints
- Training must complete within 24 hours
- Keep GPU memory under 24GB
```

### 2. Start a tmux session

```bash
tmux new -s research
cd /data/yanglab2/labmembers2/hanxuegu/Project_proposal
claude
```

### 3. Tell Claude to start

```
Start the research loop from progress.md
```

Or for hands-off mode:

```
Start the research loop from progress.md, run autonomously
```

---

## Project Structure

```
Project_proposal/
├── CLAUDE.md                    # Protocol instructions for Claude (auto-loaded)
├── progress.md                  # Your goal + auto-updated tracking dashboard
├── state.json                   # Machine-readable state (created at runtime)
└── research_agent/
    ├── idea_discovery.py        # Fetch recent papers, digest trends, propose ideas
    ├── literature_search.py     # Paper search via Claude worker in tmux
    ├── code_implementation.py   # Code changes via Claude worker in tmux
    ├── search_papers.py         # Fallback paper search (Semantic Scholar + arXiv APIs)
    ├── state.py                 # State management + progress.md auto-updates
    ├── git_ops.py               # Git branching, commits, merges per iteration
    ├── run_and_wait.sh          # Experiment runner with completion markers
    └── protocol.md              # Source protocol (copied to CLAUDE.md)
```

---

## CLI Commands

### Idea Discovery (fetch recent papers + propose research ideas)

```bash
# Fetch recent papers in your field and generate research ideas
python research_agent/idea_discovery.py --categories cs.CV,eess.IV --days 3

# With project context (reads your goal from state/progress)
python research_agent/idea_discovery.py --categories cs.CV --days 7 \
  --state state.json --progress progress.md

# Use shorthand aliases instead of arXiv category codes
python research_agent/idea_discovery.py --categories medical-imaging --days 3

# Also pull trending papers from Semantic Scholar
python research_agent/idea_discovery.py --categories cs.CV --days 3 \
  --s2-query "medical image segmentation"

# Just fetch papers, skip idea generation
python research_agent/idea_discovery.py --categories cs.CV --days 3 --fetch-only
```

**Category aliases:** `medical-imaging`, `computer-vision`, `machine-learning`, `ai`, `nlp`, `robotics`

**Outputs:**
- `results/ideas.json` — trend digest + 3-5 ranked research ideas
- `results/recent_papers.json` — all fetched papers

**Workflow:** Run this → review proposed ideas → pick one → the chosen idea feeds into the literature search + code implementation loop.

### Literature Search (paper search via Claude worker)

```bash
# Search a specific topic
python research_agent/literature_search.py "topic" results/search.json

# With project context (deduplicates previously used papers)
python research_agent/literature_search.py "topic" results/search.json --state state.json

# Auto-generate topic from last iteration
python research_agent/literature_search.py --auto results/search.json --state state.json

# Custom timeout (default: 300s)
python research_agent/literature_search.py "topic" results/search.json --timeout 600
```

### Code Implementation (code changes via Claude worker)

```bash
# Implement based on paper search results
python research_agent/code_implementation.py --papers results/search.json --project-dir .

# Implement a specific instruction
python research_agent/code_implementation.py --instruction "increase learning rate to 1e-3" --project-dir .

# With context and specific files to focus on
python research_agent/code_implementation.py --papers results/search.json --project-dir . \
  --state state.json --files models/encoder.py config.py

# Custom timeout (default: 600s)
python research_agent/code_implementation.py --instruction "..." --project-dir . --timeout 900
```

### Fallback Paper Search (no Claude needed)

```bash
python research_agent/search_papers.py "query terms" results/search.json
python research_agent/search_papers.py "query" results/search.json --limit 10 --year-min 2023
python research_agent/search_papers.py "query" results/search.json --related-to 2304.12620
```

### State Management

```bash
# Initialize a new session
python -m research_agent.state init --progress progress.md --metric test_dice

# Read current state
python -m research_agent.state read
python -m research_agent.state read --field best

# Record baseline
python -m research_agent.state set-baseline --checkpoint "checkpoints/baseline" \
  --metrics '{"test_dice": 0.85}'

# Record an iteration
python -m research_agent.state add-iteration \
  --hypothesis "Larger kernel improves receptive field" \
  --change "kernel_size 3->5" \
  --checkpoint "checkpoints/exp1" \
  --metric-name test_dice --metric-value 0.87 \
  --feedback "moderate gain"

# Export a summary report
python -m research_agent.state report
python -m research_agent.state report --output report.md
```

### Git Operations

```bash
# Create iteration branch
python -m research_agent.git_ops branch-start --iteration 1 --change "larger kernel"

# Commit code (before running experiment)
python -m research_agent.git_ops commit-code --iteration 1 \
  --hypothesis "Larger kernel improves receptive field" \
  --change "kernel_size 3->5"

# Commit results (after experiment completes)
python -m research_agent.git_ops commit-results --iteration 1 --state state.json

# Merge best iteration to main
python -m research_agent.git_ops merge-best --state state.json

# Push to remote
python -m research_agent.git_ops push

# View iteration history
python -m research_agent.git_ops log
```

### Experiment Runner

```bash
# Launch experiment in background
bash research_agent/run_and_wait.sh scripts/train.sh checkpoints/exp1/

# Check if done
test -f checkpoints/exp1/.done && cat checkpoints/exp1/.done || echo RUNNING
```

---

## How It Works

### Idea Discovery Flow (before the loop)

```
1. Fetch recent papers             (arXiv RSS + Semantic Scholar)
2. Claude digests trends           (identifies patterns, hot topics)
3. Propose 3-5 research ideas      (with hypothesis, approach, difficulty)
4. User picks an idea              (or modifies one)
5. → Enter the iteration loop with the chosen idea
```

### Iteration Flow

```
1. Read state.json + progress.md  (recover context)
2. (Optional) Literature search    (find relevant papers)
3. Create git branch               (isolate this iteration)
4. Code implementation             (make the code change)
5. Review changes                  (git diff)
6. Commit code                     (before experiment)
7. Run experiment                  (background)
8. Poll for completion             (wait for .done marker)
9. Analyze results                 (compare to baseline/best)
10. Record iteration               (update state + progress.md)
11. Commit results                 (after experiment)
12. Merge if best                  (keep main = best config)
13. Summarize to user              (present findings)
```

### Modes

- **Interactive** (default): Claude pauses after each iteration for your feedback.
  - Steer: "Focus on attention mechanisms next"
  - Approve: "Looks good, continue"
  - Reject: "Revert this, try something else"
- **Autonomous**: Claude decides what to try next based on results.
  - Switch: "Continue autonomously" / "Wait for my feedback"

### tmux Controls

| Action | Command |
|---|---|
| Detach (keep running) | `Ctrl-b d` |
| Reattach | `tmux attach -t research` |
| List sessions | `tmux ls` |
| See worker windows | `Ctrl-b w` |

---

## Monitoring

```bash
# Live dashboard (human-readable)
cat progress.md

# Full state (machine-readable)
python -m research_agent.state read

# Best result so far
python -m research_agent.state read --field best

# Git history of iterations
python -m research_agent.git_ops log
```

---

## Customization

```bash
# Use a different primary metric
python -m research_agent.state init --progress progress.md --metric val_loss

# Override file locations
export RESEARCH_STATE_FILE=my_state.json
export RESEARCH_PROGRESS_FILE=my_progress.md
```

To push iterations to a remote:
```bash
git remote add origin https://github.com/you/your-project.git
```
