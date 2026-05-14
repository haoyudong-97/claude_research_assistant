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
- Discusses the plan with you before writing any code
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
  rm -rf ~/.claude/skills/idea-iter ~/.claude/skills/check-experiments ~/.claude/skills/combine-findings ~/.claude/skills/auto-loop ~/.claude/skills/reset-iterations ~/.claude/skills/reset-iterations && \
  cp -r /tmp/idea2code/skill/idea-iter ~/.claude/skills/ && \
  cp -r /tmp/idea2code/skill/check-experiments ~/.claude/skills/ && \
  cp -r /tmp/idea2code/skill/combine-findings ~/.claude/skills/ && \
  cp -r /tmp/idea2code/skill/auto-loop ~/.claude/skills/ && \
  cp -r /tmp/idea2code/skill/reset-iterations ~/.claude/skills/ && \
  for s in idea-iter check-experiments combine-findings auto-loop reset-iterations; do \
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
rm -rf ~/.claude/skills/idea-iter ~/.claude/skills/check-experiments ~/.claude/skills/combine-findings ~/.claude/skills/auto-loop ~/.claude/skills/reset-iterations
```

## Skills

| Command | What it does |
|---------|-------------|
| `/idea-iter <idea>` | Implement one idea → papers → discuss → code → launch experiment |
| `/idea-iter --auto <idea>` | Same but skips confirmation — launches directly |
| `/check-experiments` | Check running experiments, collect results, suggest next steps |
| `/combine-findings <input>` | Integrate a paper URL, rough idea, or literature into current work |
| `/auto-loop <goal>` | Run multiple iterations automatically toward a high-level goal |
| `/reset-iterations [reason]` | Archive current state and restart from iter/1 (new dataset, new direction) |

### /idea-iter

The core skill. Give it a specific idea or a vague direction:

```
/idea-iter add attention gates to decoder skip connections    # specific → skips paper search
/idea-iter improve model generalization                       # exploratory → searches papers first
```

It always discusses the plan with you before implementing (unless `--auto`).

### /auto-loop

Hands-free mode. Give a high-level goal, and it runs repeated iterations:

```
/auto-loop improve segmentation on small organs
```

It asks you upfront:
1. How many GPUs? (each runs a different iteration in parallel)
2. Stop by time or iterations? ("run for 12 hours" or "run 5 iterations")
3. Any constraints? ("only try attention-based methods")

Then it loops: formulate ideas → implement → launch → wait → collect results → formulate next ideas. All iterations stay focused on your goal. Running experiments are never killed — when the limit is reached, it waits for them to finish before reporting.

## How It Works

```
Your idea
    ↓
Classify: specific or exploratory?
    ↓
(exploratory only) Find relevant papers — arXiv API + WebSearch
    ↓
Discuss plan with you
    ↓
Implement the idea (surgical code edits via Agent)
    ↓
Commit to git branch (iter/1-attention-gates)
    ↓
Launch experiment (GPU-aware, local or remote SSH)
    ↓
Return immediately — start next idea
```

`state.json` and `progress.md` track all iterations, metrics, and results. Each iteration records its method, results, and learnings.

## License

MIT
