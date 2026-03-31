# idea2code

Turn a research idea into running code. One command, one experiment.

<p align="center">
  <img src="assets/diagram.jpg" alt="idea2code pipeline" width="800"/>
</p>

> "Talk is cheap. Show me the code." But now in the era of AI coding, the reverse might be true — **your ability to create a new idea is far more important than implementing it.**
>
> This tool bridges that gap. You bring the idea. It writes the code.

```
/idea-iter try attention gates in the decoder
```

## What it does

You describe an idea. The agent:
- Finds relevant papers to inform the implementation
- Reads your codebase to understand the architecture
- Makes surgical code edits to implement your idea
- Commits, pushes, and launches the experiment
- Returns immediately so you can start the next idea

## Install

### Option A: npx (requires Node.js)

```bash
npx idea2code
```

### Option B: git clone (no Node.js needed)

```bash
git clone https://github.com/haoyudong-97/idea2code.git /tmp/idea2code && \
  rm -rf ~/.claude/skills/idea-iter ~/.claude/skills/check-experiments ~/.claude/skills/combine-findings && \
  cp -r /tmp/idea2code/skill/idea-iter ~/.claude/skills/ && \
  cp -r /tmp/idea2code/skill/check-experiments ~/.claude/skills/ && \
  cp -r /tmp/idea2code/skill/combine-findings ~/.claude/skills/ && \
  for s in idea-iter check-experiments combine-findings; do \
    cp -r /tmp/idea2code/skill/research_agent ~/.claude/skills/$s/; \
  done && \
  rm -rf /tmp/idea2code && \
  echo "Done! Skills installed."
```

### Requirements

- [Claude Code](https://claude.ai/code) installed
- Python 3.10+
- Git

### Uninstall

```bash
rm -rf ~/.claude/skills/idea-iter ~/.claude/skills/check-experiments ~/.claude/skills/combine-findings
```

## Usage

```bash
cd your-project && claude
```

```
/idea-iter try attention gates in the decoder       # idea -> papers -> code -> launch
/idea-iter --auto increase batch size to 4          # skip confirmation, launch directly
/check-experiments                                   # collect results when training finishes
/combine-findings https://arxiv.org/abs/2401...      # integrate a specific paper
```

Run multiple iterations in parallel — each gets its own git branch and checkpoint:

```
/idea-iter add attention gates to decoder        -> iter 1 launched
/idea-iter increase batch size to 4              -> iter 2 launched
/idea-iter try cosine annealing schedule         -> iter 3 launched

/check-experiments                               -> collects all finished results
```

## How It Works

```
Your idea
    ↓
Find relevant papers (arXiv API + WebSearch, top 10 with full text)
    ↓
Read your codebase, understand the architecture
    ↓
Implement the idea (surgical code edits via Agent)
    ↓
Commit to git branch (iter/1-attention-gates)
    ↓
Launch experiment (GPU-aware, local or remote SSH)
    ↓
Return immediately — start next idea
```

State tracking happens automatically via hooks — every `git commit`, `deploy launch`, and experiment completion updates `state.json` and `progress.md` without manual commands.

## License

MIT
