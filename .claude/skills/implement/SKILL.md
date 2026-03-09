---
name: implement
description: Implement a code change and launch the experiment. TRIGGER when the user asks to implement something, make a code change, try an idea in code, apply a technique, modify the model/config, or says things like "implement X", "try X in code", "change Y to Z", "apply this paper's approach". Do NOT trigger for pure discussion or analysis — only when actual code changes are requested.
argument-hint: <instruction or description of what to implement> [--papers path] [--files file1 file2]
disable-model-invocation: false
allowed-tools: Bash(python:*), Bash(cat:*), Bash(test:*), Bash(bash:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(git branch:*), Read, Grep, Agent
---

# Implement Code Change → Launch Experiment

Delegate a code change to an **Agent subagent**, launch the experiment, and return. Use `/check-experiments` to collect results. You are the orchestrator — NEVER edit project code directly.

## Step 0: Read current state

```bash
cd /data/humanBodyProject/new_proj/research_agent
```

1. If `state.json` exists:
   ```bash
   python -m research_agent.state read
   ```
2. If `progress.md` exists, read the user section for notes/constraints.
3. Get the next iteration number:
   ```bash
   python -m research_agent.state read --field next_id
   ```
   Store as `NEXT_ITER` (a single integer, e.g., `4`). All subsequent commands use this number.

Record from state output: `GOAL`, `BASELINE`, `BEST`, `LAST_ITERS`, `PRIMARY_METRIC`.

## Step 1: Parse the input

- **instruction**: the main thing to implement (required).
- **--papers PATH**: path to a papers JSON file.
- **--files FILE1 FILE2 ...**: specific files to focus on.

If the user references an idea number from `/find-papers`, read `results/ideas.json` and extract that idea's details.

## Step 2: Prepare the iteration (if state exists)

```bash
python -m research_agent.git_ops branch-start --iteration <N> --change "<CHANGE_DESC>"
python -m research_agent.state start-iteration --hypothesis "<HYPOTHESIS>" --change "<CHANGE_DESC>"
```

## Step 3: Implement via Agent tool

Launch an **Agent** subagent with a detailed prompt including:
- The instruction
- Project context (goal, baseline, best, last iteration)
- Key files to focus on
- Requirement to write summary to `results/impl_summary.json`

## Step 4: Review + Commit Code

1. Read `results/impl_summary.json`.
2. Show `git diff`.
3. Briefly tell the user what was changed.

4. Commit:
   ```bash
   python -m research_agent.git_ops commit-code --iteration <N> \
     --hypothesis "<HYPOTHESIS>" --change "<CHANGE_DESC>" --papers "<PAPERS>"
   python -m research_agent.git_ops push
   ```

## Step 5: Discover Experiment Script + Launch

Find the experiment/training script. Check in order:
1. `progress.md` — look for script path or "How to run" section.
2. Previous iterations in `state.json` — checkpoint path patterns.
3. File search — `train*.sh`, `train*.py`, `scripts/` directory.
4. **If not found** — ask the user what script to run.

Determine a unique `CHECKPOINT_DIR` for this iteration (e.g., `checkpoints/iter_<N>`).

### Launch (non-blocking):

```bash
python -m research_agent.state launch-iteration --id <N> --checkpoint "<CHECKPOINT_DIR>"
```

Launch in background using `run_in_background: true`:
```bash
bash research_agent/run_and_wait.sh <EXP_SCRIPT> <CHECKPOINT_DIR>
```

**Do NOT poll. Return control to the user immediately.**

## Step 6: Present Launch Summary

```
## Iteration <N> — Launched

**Hypothesis:** <HYPOTHESIS>
**Changes:** <CHANGE_DESC> (files: <FILES>)
**Experiment:** running in `<CHECKPOINT_DIR>`

Run `/check-experiments` to see results when training finishes.
```

## Notes

- NEVER implement code yourself. ALWAYS use the Agent tool.
- NEVER call `code_implementation.py` — it is archived.
- ONE change per invocation.
- ALWAYS commit code BEFORE launching experiments.
- Each iteration gets a UNIQUE checkpoint directory.
- After launching, RETURN IMMEDIATELY. Do NOT poll for completion.
- Use `/check-experiments` to collect results.
