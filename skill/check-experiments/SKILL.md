---
name: check-experiments
description: Check running experiments, collect results, and present a research summary.
when_to_use: When the user says "check experiments", "check results", "any experiments done", "check iterations", "what's running", or wants to see the status of launched experiments.
argument-hint:
disable-model-invocation: false
version: "0.2.0"
effort: low
model: sonnet
allowed-tools: Bash(python -m research_agent:*), Bash(test:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(git branch:*), Bash(git checkout:*), Read, Grep
hooks:
  PostToolUse:
    - matcher: Bash|Edit
      hooks:
        - type: command
          command: "python ${CLAUDE_SKILL_DIR}/research_agent/hooks/track_state.py"
---

# Check Experiments

Sweep all running iterations — complete any that finished, report status of those still running, and present a full research summary.

## Tool Discovery

```bash
export PYTHONPATH="${CLAUDE_SKILL_DIR}:$PYTHONPATH"
```

---

## Step 1: Read State

```bash
cd "$(git rev-parse --show-toplevel)"
python -m research_agent.state read
```

Find all iterations with `"status": "running"`. For each, note its `id` and `checkpoint` path.

If no iterations are running, just show the full report (Step 5) and exit.

---

## Step 1.5: Collect Remote Results (if applicable)

If any experiments were deployed remotely, pull results first:

```bash
python -m research_agent.deploy collect <CHECKPOINT> --host <HOST>
```

This downloads `.done`, `.status`, `training.log`, and result files from the remote server.

---

## Step 2: Check Each Running Iteration

For each running iteration, first validate the checkpoint directory exists:

```bash
test -d <CHECKPOINT> || echo "LOST"
```

If the checkpoint directory is missing, mark the iteration as LOST:
```bash
python -m research_agent.state fail-iteration --id <ID> \
  --feedback "Checkpoint directory <CHECKPOINT> not found — marking as LOST"
```

If the checkpoint directory exists, check if it's done:

```bash
test -f <CHECKPOINT>/.done && cat <CHECKPOINT>/.done || echo RUNNING
```

### If still RUNNING:
Note it and move on. Report it as still running in the summary.

### If .done exists:

1. Read the exit code:
   ```bash
   cat <CHECKPOINT>/.done
   ```

2. **EXIT_CODE != 0** (failed):
   - Read the error:
     ```bash
     tail -50 <CHECKPOINT>/training.log
     ```
   - Record failure:
     ```bash
     python -m research_agent.state fail-iteration --id <ID> \
       --feedback "<error summary>"
     ```

3. **EXIT_CODE == 0** (succeeded):
   - Extract metrics from checkpoint dir / training log. Look for:
     - JSON result files in `<CHECKPOINT>/`
     - Metric values in the tail of `<CHECKPOINT>/training.log`
     - Eval result files in the project
   - Read the primary metric name from state (`primary_metric` field).
   - Record success:
     ```bash
     python -m research_agent.state complete-iteration --id <ID> \
       --metric-name <PRIMARY_METRIC> --metric-value <VALUE> \
       --feedback "<brief observation>"
     ```

---

## Step 3: Commit Results

For each iteration that just completed or failed, switch to its branch and commit:

```bash
git checkout iter/<ID>-*
python -m research_agent.git_ops commit-results --iteration <ID> --state state.json
python -m research_agent.git_ops push
```

---

## Step 4: Merge Best

Check if any newly completed iteration is the new best:

```bash
python -m research_agent.state read --field best
```

If the best iteration just completed in this sweep:
```bash
python -m research_agent.git_ops merge-best --state state.json
python -m research_agent.git_ops push
```

Switch back to main:
```bash
git checkout main
```

---

## Step 5: Present Full Summary

### Per-iteration results (for newly finished iterations):

For each iteration that just completed:
```
## Iteration <ID> — COMPLETED
**Hypothesis:** <hypothesis>
**Changes:** <change_summary>
**Result:** <PRIMARY_METRIC>: <VALUE> (baseline: <BASELINE>, delta: <DELTA>)
**Verdict:** NEW_BEST / IMPROVED / REGRESSED
```

For each iteration that just failed:
```
## Iteration <ID> — FAILED
**Hypothesis:** <hypothesis>
**Error:** <error summary>
```

### Still running:
```
## Still Running
- Iter <ID>: <change_summary> (checkpoint: <CHECKPOINT>)
```

### Full research history:
```bash
python -m research_agent.state report
```

Present the full report table to the user.

### Suggest next direction:
- **Improved?** -> variant of same approach, or combine with another winner
- **Regressed?** -> revert direction, try something orthogonal
- **Plateaued (3+ iters)?** -> suggest fresh literature search
- **Goal reached?** -> congratulate, suggest refinement or stopping

---

## Rules

- Process ALL running iterations in one sweep — don't stop after the first.
- ALWAYS commit results and push for completed/failed iterations.
- ALWAYS show the full report at the end.
- If no experiments are running or finished, just show the current report.
