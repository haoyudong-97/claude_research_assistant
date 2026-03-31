# code2idea

Autonomous research loop for Claude Code. Give one idea, get a launched experiment.

```
npx code2idea
```

## What It Does

Three skills that work together for iterative research:

```bash
/idea-iter try attention gates in the decoder    # idea -> papers -> code -> launch
/check-experiments                                # collect results, present summary
/combine-findings https://arxiv.org/abs/2401...   # integrate a paper into current work
```

Each `/idea-iter` call runs the full cycle and **returns immediately** — the experiment runs in the background. Start multiple iterations in parallel:

```
/idea-iter add attention gates to decoder        -> launches iter 1
/idea-iter increase batch size to 4              -> launches iter 2
/idea-iter try cosine annealing schedule         -> launches iter 3

/check-experiments                               -> collects all finished results
```

## Install

```bash
npx code2idea
```

This installs three skills into `~/.claude/skills/`. Python tools are bundled — no `pip install` needed.

### Requirements

- [Claude Code](https://claude.ai/code) installed
- Python 3.10+
- Git

### Uninstall

```bash
npx code2idea --uninstall
```

## How It Works

1. **Fetch papers** from arXiv + Semantic Scholar — top 5 with full text (cached 15 min)
2. **Generate ideas** via Agent subagent — digests papers, proposes approaches
3. **Select approach** — picks the best idea, asks for confirmation
4. **Implement code** via Agent subagent — reads your codebase, makes surgical edits
5. **Commit + push** — each iteration gets a git branch
6. **Launch experiment** — GPU-aware deployment (local or remote via SSH)
7. **Return immediately** — start the next iteration while this one trains

### Hooks

PostToolUse hooks auto-update `state.json` on deploy, git commit, and git checkout. PreToolUse hooks warn when training commands run outside the framework.

## Project Setup

Create a `progress.md` in your project:

```markdown
# Research Goal
Improve val_accuracy above 0.92.

## How to run
Experiment script: scripts/train.sh
```

Then: `cd your-project && claude` and type `/idea-iter improve model generalization`.

## License

MIT
