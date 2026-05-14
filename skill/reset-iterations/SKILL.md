---
name: reset-iterations
description: Archive current iterations and restart from iter/1. Use when the project foundation changes (new dataset, new architecture, new direction).
when_to_use: When the user says "reset iterations", "start over", "restart from iter 1", "new baseline", "reset state", "fresh start", "clean slate", or indicates a fundamental shift in the project (new dataset, new architecture, new research direction).
argument-hint: [reason for reset]
arguments: reason
disable-model-invocation: false
version: "1.0.0"
effort: low
allowed-tools: Bash(python -m research_agent:*), Bash(test:*), Bash(git branch:*), Bash(git checkout:*), Bash(git tag:*), Bash(mv:*), Bash(mkdir:*), Bash(ls:*), Bash(cat:*), Read
---

# Reset Iterations

Archive the current research state and restart iteration numbering from 1. Use this when the project foundation changes — new dataset, new architecture, or a fundamentally different research direction.

Your FIRST action must be to set up the Python tools:

```bash
export PYTHONPATH="$HOME/.claude/skills/reset-iterations:$PYTHONPATH"
```

---

## Phase 1: Show Current State

```bash
cd "$(git rev-parse --show-toplevel)"
```

Load and display the current state:

```bash
test -f state.json && python -m research_agent.state read || echo "NO_STATE"
```

```bash
test -f progress.md && head -30 progress.md || echo "NO_PROGRESS"
```

Count existing iterations and branches:

```bash
python -m research_agent.state read --field next_id 2>/dev/null || echo "0"
git branch --list "iter/*" | wc -l
```

Present a summary:

> **Current state:**
> - **Goal:** <GOAL>
> - **Iterations:** <N> total (<completed> completed, <running> running, <failed> failed)
> - **Best result:** <METRIC>: <VALUE> (iter <ID>)
> - **Git branches:** <N> iter/* branches
>
> **Reason for reset:** <$reason or "not specified">

---

## Phase 2: Confirm with User

Ask the user to confirm and choose what to keep:

> **This will:**
> 1. Archive `state.json` → `state.archive.<timestamp>.json`
> 2. Archive `progress.md` → `progress.archive.<timestamp>.md`
> 3. Create a fresh `state.json` starting at iter 1
> 4. Tag all existing iter/* branches with `archive/` prefix
>
> **What about the git branches?**
> 1. **Tag and keep** — rename `iter/5-attention-gates` → `archive/iter/5-attention-gates` (branches stay, just renamed)
> 2. **Tag only** — create git tags for each branch, then delete the branches (saves clutter)
> 3. **Keep as-is** — don't touch branches (new iterations will start from iter/1, old branches stay as iter/*)
>
> **New goal?** Keep the current goal, or set a new one?

**Wait for the user's response.**

---

## Phase 3: Archive

Based on the user's choices:

### Archive state files

```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p archive

# Archive state.json
test -f state.json && mv state.json "archive/state.${TIMESTAMP}.json"

# Archive progress.md
test -f progress.md && mv progress.md "archive/progress.${TIMESTAMP}.md"

# Archive results/
test -d results && mv results "archive/results_${TIMESTAMP}"
```

### Handle git branches

**If "Tag and keep":**
```bash
for branch in $(git branch --list "iter/*" | sed 's/^[* ]*//')
do
    new_name="archive/${branch}"
    git branch -m "$branch" "$new_name" 2>/dev/null && echo "Renamed: $branch → $new_name"
done
```

**If "Tag only":**
```bash
for branch in $(git branch --list "iter/*" | sed 's/^[* ]*//')
do
    git tag "archive/${branch}" "$branch" 2>/dev/null && echo "Tagged: $branch"
    git branch -D "$branch" 2>/dev/null && echo "Deleted: $branch"
done
```

**If "Keep as-is":** do nothing.

### Create fresh state

```bash
python -m research_agent.state init \
  --goal "<NEW_GOAL or EXISTING_GOAL>" \
  --metric "<EXISTING_METRIC>"
```

If the user wants to keep the current baseline:

```bash
python -m research_agent.state set-baseline \
  --checkpoint "<EXISTING_BASELINE_CHECKPOINT>" \
  --metrics '<EXISTING_BASELINE_METRICS_JSON>'
```

Create a fresh results directory:

```bash
mkdir -p results
```

---

## Phase 4: Summary

```
## Reset Complete

**Previous state:** <N> iterations archived to `archive/`
**New state:** starting fresh at iter 1
**Goal:** <GOAL>
**Baseline:** <BASELINE or "not set — use `set-baseline` before first iteration">

### Archived files
- `archive/state.<TIMESTAMP>.json`
- `archive/progress.<TIMESTAMP>.md`
- `archive/results_<TIMESTAMP>/`
<branch info>

### Next steps
- `/idea-iter <your first idea>` — start iterating on the new direction
- Set a baseline if needed: `python -m research_agent.state set-baseline --checkpoint "..." --metrics '{"metric": value}'`
```

---

## Rules

- Always show the current state before resetting.
- Always confirm with the user before archiving.
- Never delete state.json or progress.md — always archive them.
- Never force-delete git branches without the user's explicit choice.
- The archive/ directory preserves the full history for reference.
- Ensure we're on main before renaming/deleting iter branches.
