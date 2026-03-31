---
name: check-experiments
description: Check running experiments, collect results, and present a research summary.
when_to_use: When the user says "check experiments", "check results", "any experiments done", "check iterations", "what's running", or wants to see the status of launched experiments.
argument-hint:
disable-model-invocation: false
version: "0.2.0"
effort: low
allowed-tools: Bash(python -m research_agent:*), Bash(test:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(git branch:*), Bash(git checkout:*), Read, Grep
hooks:
  PostToolUse:
    - matcher: Bash|Edit
      hooks:
        - type: command
          command: "python $HOME/.claude/skills/check-experiments/research_agent/hooks/track_state.py"
---

# Check Experiments: Collect Results & Iterate

You are sweeping all running experiments — check which ones finished, collect their results, commit them, and present a full research summary with next-step recommendations.

Your FIRST action must be to set up the Python tools:

```bash
export PYTHONPATH="$HOME/.claude/skills/check-experiments:$PYTHONPATH"
```

---

## Phase 1: Load State

```bash
cd "$(git rev-parse --show-toplevel)"
python -m research_agent.state read
```

Find all iterations with `"status": "running"`. Note each iteration's `id` and `checkpoint` path.

If no iterations are running, skip to Phase 4 and show the full report.

If any experiments were deployed remotely, collect results first:

```bash
python -m research_agent.deploy collect <CHECKPOINT> --host <HOST>
```

---

## Phase 2: Check Each Running Iteration

Process ALL running iterations in one sweep — do not stop after the first.

For each running iteration:

1. **Validate checkpoint exists:**
   ```bash
   test -d <CHECKPOINT> && echo EXISTS || echo MISSING
   ```
   If MISSING, mark as lost and move on:
   ```bash
   python -m research_agent.state fail-iteration --id <ID> \
     --feedback "Checkpoint directory not found — experiment lost"
   ```

2. **Check completion:**
   ```bash
   test -f <CHECKPOINT>/.done && cat <CHECKPOINT>/.done || echo RUNNING
   ```
   If still RUNNING, note it and move to the next iteration.

3. **If done with exit code != 0** (failed):
   Read the error log:
   ```bash
   tail -50 <CHECKPOINT>/training.log
   ```
   Record the failure — explain what went wrong and what to try differently:
   ```bash
   python -m research_agent.state fail-iteration --id <ID> \
     --feedback "<what went wrong and what to try differently>"
   ```

4. **If done with exit code == 0** (succeeded):
   Extract metrics from the checkpoint directory or training log. Look for JSON result files, metric values in the log tail, or eval files in the project.

   Record success. The feedback is important — write 1-2 sentences about what you learned (e.g., "Attention gates helped small organs +0.05 but hurt liver -0.01. Consider organ-specific gating."):
   ```bash
   python -m research_agent.state complete-iteration --id <ID> \
     --metric-name <PRIMARY_METRIC> --metric-value <VALUE> \
     --feedback "<what we learned — insights, surprises, what to try next>"
   ```

---

## Phase 3: Commit & Merge

For each iteration that just completed or failed, switch to its branch and commit:

```bash
git checkout iter/<ID>-*
python -m research_agent.git_ops commit-results --iteration <ID> --state state.json
python -m research_agent.git_ops push
```

After committing all results, check if any newly completed iteration is the new best:

```bash
python -m research_agent.state read --field best
```

If the best iteration just completed in this sweep, merge it to main:

```bash
python -m research_agent.git_ops merge-best --state state.json
python -m research_agent.git_ops push
git checkout main
```

---

## Phase 4: Present Summary

Show results for each newly finished iteration:

```
## Iteration <ID> — COMPLETED
**Hypothesis:** <hypothesis>
**Changes:** <change_summary>
**Result:** <PRIMARY_METRIC>: <VALUE> (baseline: <BASELINE>, delta: <DELTA>)
**Learnings:** <feedback>
**Verdict:** NEW_BEST / IMPROVED / REGRESSED
```

For failed iterations:
```
## Iteration <ID> — FAILED
**Hypothesis:** <hypothesis>
**Error:** <error summary>
```

For still-running iterations:
```
## Still Running
- Iter <ID>: <change_summary> (checkpoint: <CHECKPOINT>)
```

Then show the full research history:

```bash
python -m research_agent.state report
```

### Suggest next direction

Based on the results:
- **Improved?** → suggest a variant of the same approach, or combine with another winning iteration
- **Regressed?** → suggest reverting direction, try something orthogonal
- **Plateaued (3+ iterations)?** → suggest a fresh literature search with `/idea-iter`
- **Goal reached?** → congratulate and suggest refinement or stopping

---

## Rules

- Process all running iterations in one sweep.
- Commit results and push for every completed or failed iteration.
- Always show the full report at the end.
- If no experiments are running, just show the current report and suggest next steps.
