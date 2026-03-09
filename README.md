# Research Agent

> Once people said "Talk is cheap. Show me the code." But now in the era of vibe coding, I think the reverse might be true: your ability to create a new idea is far more important than being able to implement it.
>
> With this idea in mind, this project is created to accelerate the idea-to-real-code step.

A project-agnostic autonomous research loop for Claude Code. Give one idea, get a results summary.

```
/auto-research <your idea here>
```

You can start from different levels of specificity:

```bash
# Just a direction — agent finds papers and decides the approach
/auto-research improve boundary segmentation accuracy

# A rough idea — agent searches for supporting papers, then implements
/auto-research try attention gates in the decoder skip connections

# A specific paper — agent reads it and implements the key technique
/combine-findings https://arxiv.org/abs/2401.12345

# An exact change — agent implements directly, no paper search needed
/implement increase spd_rank from 4 to 8

# Explore what's new — agent fetches recent papers and proposes ideas
/find-papers medical image segmentation transformers
```

---

## What It Does

Each `/auto-research` call runs the full cycle:

**Idea → Papers → Code → Experiment → Results**

1. Fetches relevant papers from arXiv + Semantic Scholar
2. Generates research ideas, selects the best approach
3. Implements code changes via Agent subagent
4. Runs the experiment, extracts metrics
5. Records results, merges to main if new best
6. Presents a full summary with all iteration history

See [docs/pipeline.md](docs/pipeline.md) for the detailed 12-step breakdown.

---

## Iterating

Call `/auto-research` repeatedly. State accumulates — each call sees the full history and builds on it:

```
/auto-research add residual attention to nnunet decoder
```
```
Iteration 1: test_3d_dice = 0.88 (baseline: 0.85, +0.030) — NEW BEST

| # | Change                            | test_3d_dice | vs baseline |
|---|-----------------------------------|--------------|-------------|
| 1 | add residual attention to decoder | 0.88         | +0.030      |
```

```
/auto-research increase batch size from 2 to 4
```
```
Iteration 2: test_3d_dice = 0.89 (baseline: 0.85, +0.040) — NEW BEST

| # | Change                            | test_3d_dice | vs baseline |
|---|-----------------------------------|--------------|-------------|
| 1 | add residual attention to decoder | 0.88         | +0.030      |
| 2 | increase batch size from 2 to 4   | 0.89         | +0.040      |
```

```
/auto-research combine attention with deeper supervision
```
```
Iteration 3: test_3d_dice = 0.87 (baseline: 0.85, +0.020) — REGRESSED (best: iter 2)

| # | Change                             | test_3d_dice | vs baseline |
|---|------------------------------------|--------------|-------------|
| 1 | add residual attention to decoder  | 0.88         | +0.030      |
| 2 | increase batch size from 2 to 4    | 0.89         | +0.040      |
| 3 | combine attention + deep supervise | 0.87         | +0.020      |
```

---

## Installation

```bash
# 1. Copy into your project
cp -r research_agent/ /path/to/your/project/
cp -r .claude/skills/ /path/to/your/project/.claude/skills/

# 2. Append protocol to CLAUDE.md
cat research_agent/protocol.md >> /path/to/your/project/CLAUDE.md

# 3. (Optional) Create progress.md with your research goal
cat > progress.md << 'EOF'
# Research Goal
Improve heart segmentation 3D Dice above 0.92.
EOF

# 4. Start
cd /path/to/your/project && claude
# Then type: /auto-research <your idea>
```

---

## Skills

| Command | Purpose |
|---------|---------|
| `/auto-research <idea>` | Idea → papers → code → launch experiment (non-blocking) |
| `/auto-research <idea> --auto` | Same but skips confirmation — fully autonomous |
| `/check-experiments` | Check running experiments, collect results, present summary |
| `/find-papers <topic>` | Search literature, generate research ideas |
| `/implement <instruction>` | Implement a specific change + launch experiment |
| `/combine-findings <input>` | Integrate a paper, idea, or literature into current work |

### Concurrent iterations

`/auto-research` launches the experiment and returns immediately. Start multiple iterations in parallel:

```
/auto-research add attention gates to decoder        → launches iter 1
/auto-research increase batch size to 4              → launches iter 2
/auto-research try cosine annealing schedule         → launches iter 3

/check-experiments                                   → collects all finished results
```

See [docs/skills.md](docs/skills.md) for details.

---

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/pipeline.md](docs/pipeline.md) | Detailed 12-step pipeline breakdown |
| [docs/skills.md](docs/skills.md) | All slash commands with examples |
| [docs/architecture.md](docs/architecture.md) | Architecture, components, project structure, rules |
| [docs/cli-reference.md](docs/cli-reference.md) | CLI commands for state, git, paper fetching |
