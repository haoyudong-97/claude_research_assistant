---
name: auto-research
description: End-to-end research pipeline from idea to results summary. TRIGGER when the user gives a research idea and expects working code at the end, or says "research and implement", "idea to code", "auto-research", "take this idea and build it", "implement this concept", or any phrasing that implies going from a rough idea all the way to code changes without manual steps in between.
argument-hint: <rough idea or research direction>
disable-model-invocation: false
allowed-tools: Bash(python:*), Bash(cat:*), Bash(test:*), Bash(bash:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(git branch:*), Read, Grep, WebFetch, WebSearch, Agent
---

# Auto-Research: Idea → Code → Results

You are an autonomous research orchestrator. The user gives you ONE rough idea. You deliver a **results summary** — hypothesis, code changes, experiment metrics, and comparison to baseline.

Pipeline: **fetch papers → select approach → implement code → commit → run experiment → analyze → present summary**

## Architecture — What runs where

| Step | Who does it | How |
|---|---|---|
| Paper fetching | Python scripts | `idea_discovery.py --fetch-only` or `search_papers.py` — pure API calls, no Claude |
| Idea generation | Agent subagent | Agent tool reads fetched papers, proposes ideas |
| Approach selection | You (orchestrator) | Judgment call — pick the best idea |
| Git setup | Python scripts | `git_ops.py`, `state.py` — pure CLI |
| Code implementation | Agent subagent | Agent tool reads code, makes edits |
| Experiment | Shell | `run_and_wait.sh` + polling |
| Analysis & summary | You (orchestrator) | Read results, compare to baseline, present |

**NEVER call `code_implementation.py` or `literature_search.py`** — they are archived.

---

## Step 0: Load Context

```bash
cd /data/humanBodyProject/new_proj/research_agent
```

```bash
test -f state.json && python -m research_agent.state read || echo "NO_STATE"
```

```bash
test -f progress.md && head -30 progress.md || echo "NO_PROGRESS"
```

Record from the state output: `HAS_STATE`, `GOAL`, `BASELINE`, `BEST`, `LAST_ITERS`, `PRIMARY_METRIC`.

If no state exists, initialize:
```bash
python -m research_agent.state init --goal "$ARGUMENTS" --metric "improvement"
```

Get the next iteration number:
```bash
python -m research_agent.state read --field next_id
```
This returns a single integer (e.g., `4`). Store it as `NEXT_ITER`. All subsequent commands use this number.

Extract `IDEA` from `$ARGUMENTS`.

Infer `CATEGORIES`:
- Medical/imaging → `medical-imaging`
- Vision/CV → `cs.CV`
- ML/learning → `cs.LG`
- NLP/language → `nlp`
- Unsure → `cs.CV,cs.LG`

---

## Step 1: Fetch Papers (pure Python — always works)

```bash
cd /data/humanBodyProject/new_proj/research_agent && \
python research_agent/idea_discovery.py \
  --categories <CATEGORIES> \
  --days 7 \
  --s2-query "<IDEA>" \
  --fetch-only \
  --papers-output results/recent_papers.json
```

Pass `--state state.json` and `--progress progress.md` if they exist.

**Fallback** if this fails:
```bash
python research_agent/search_papers.py "<IDEA>" results/recent_papers.json --limit 15
```

**If all search fails**, skip to Step 3 with just the user's raw idea.

---

## Step 2: Generate Ideas + Select Approach

### 2a: Generate ideas via Agent

Launch an **Agent** (subagent_type: general-purpose) to digest the papers:

```
Read the file results/recent_papers.json in /data/humanBodyProject/new_proj/research_agent.
Also read state.json if it exists for project context.

The user's research idea is: <IDEA>

From these papers:
1. Identify the 3-5 most relevant trends/techniques.
2. Propose 3-5 concrete research ideas aligned with the user's idea.

For each idea include: title, hypothesis, approach (specific code changes), expected_impact, difficulty (low/medium/high), relevant_papers.

Write output to results/ideas.json as JSON:
{
  "trend_digest": ["Trend 1: ...", ...],
  "ideas": [{"id": 1, "title": "...", "hypothesis": "...", "approach": "...", "expected_impact": "...", "difficulty": "low", "relevant_papers": ["..."]}]
}

This is a research-only task. Do NOT modify any project code. Only read files and write results/ideas.json.
```

### 2b: Select the best approach (YOUR judgment)

Read `results/ideas.json`. Select ONE idea based on:
1. **Relevance** to `IDEA`
2. **Feasibility** — prefer low/medium difficulty
3. **Novelty** — skip what overlaps with `LAST_ITERS`
4. **Concreteness** — clear `approach` field

Formulate:
- `HYPOTHESIS`
- `CHANGE_DESC` (short, for git)
- `INSTRUCTION` (detailed, for the implementation Agent)
- `PAPERS_USED`

Tell the user (2-3 lines): which approach and why.

**If no ideas.json** (Agent or fetch failed): formulate an instruction directly from the user's raw `IDEA`.

---

## Step 3: Git Setup + Register Iteration

```bash
cd /data/humanBodyProject/new_proj/research_agent && \
python -m research_agent.git_ops branch-start \
  --iteration <NEXT_ITER> \
  --change "<CHANGE_DESC>"
```

```bash
python -m research_agent.state start-iteration \
  --hypothesis "<HYPOTHESIS>" \
  --change "<CHANGE_DESC>"
```

---

## Step 4: Implement Code via Agent

Launch an **Agent** (subagent_type: general-purpose) to implement the change:

```
You are implementing a code change in the project.
Working directory: /data/humanBodyProject/new_proj/research_agent

## Instruction
<INSTRUCTION — detailed, specific implementation plan>

## Project Context
- Goal: <GOAL>
- Primary metric: <METRIC>
- Baseline: <BASELINE_METRICS>
- Current best (iter <N>): <BEST_METRICS>
- Last change: <LAST_CHANGE> -> <LAST_RESULT>

## Papers
<PAPER_TITLES_AND_KEY_IDEAS>

## Key files to examine
<FOCUS_FILES or "explore the codebase to find relevant files">

## Rules
1. Read relevant code files FIRST to understand current implementation.
2. Implement ONE focused change based on the instruction.
3. Make minimal, surgical edits — don't rewrite entire files.
4. Verify changes are syntactically correct.
5. After implementing, write a summary to results/impl_summary.json:
{
  "hypothesis": "What you expect this change to achieve",
  "change_summary": "Short description of what was changed",
  "files_modified": ["path/to/file1.py"],
  "papers_used": ["Paper Title"]
}
```

---

## Step 5: Review + Commit Code

1. Read `results/impl_summary.json`.
2. Show the diff:
   ```bash
   git diff
   ```
3. Briefly tell the user what was changed and why.

4. Commit the code:
   ```bash
   python -m research_agent.git_ops commit-code \
     --iteration <NEXT_ITER> \
     --hypothesis "<HYPOTHESIS>" \
     --change "<CHANGE_DESC>" \
     --papers "<PAPER1>" "<PAPER2>"
   ```

5. Push:
   ```bash
   python -m research_agent.git_ops push
   ```

---

## Step 6: Discover Experiment Script

Find the experiment/training script to run. Check in order:

1. **progress.md** — look for a line like `Experiment script: scripts/train.sh` or `## How to run` section above the sentinel.
2. **state.json** — check if previous iterations have checkpoint paths that hint at the script location.
3. **File search** — look for `train*.sh`, `train*.py`, `run*.sh`, `experiment*.sh`, `scripts/` directory in the project.
4. **If not found** — ask the user: "What script should I run for the experiment? (e.g., `bash scripts/train.sh`)"

Also determine the **checkpoint directory** for this iteration:
- Convention: `checkpoints/iter_<NEXT_ITER>` or follow the pattern from previous iterations.
- Each iteration MUST have a unique checkpoint directory.

Record: `EXP_SCRIPT`, `CHECKPOINT_DIR`.

---

## Step 7: Run Experiment

1. Mark iteration as running:
   ```bash
   python -m research_agent.state launch-iteration \
     --id <NEXT_ITER> \
     --checkpoint "<CHECKPOINT_DIR>"
   ```

2. Launch the experiment in background:
   ```bash
   bash research_agent/run_and_wait.sh <EXP_SCRIPT> <CHECKPOINT_DIR>
   ```
   Run this with `run_in_background: true` so it doesn't block.

3. Tell the user: "Experiment launched. Training in `<CHECKPOINT_DIR>`. I'll poll for completion."

4. Poll for completion (check every 60 seconds, up to a reasonable timeout):
   ```bash
   test -f <CHECKPOINT_DIR>/.done && cat <CHECKPOINT_DIR>/.done || echo RUNNING
   ```

   While polling, give periodic updates: "Still training... (Xm elapsed)"

---

## Step 8: Analyze Results

Once `.done` exists:

1. Read the exit code from `.done`:
   ```bash
   cat <CHECKPOINT_DIR>/.done
   ```

2. **If EXIT_CODE != 0** (experiment failed):
   ```bash
   python -m research_agent.state fail-iteration \
     --id <NEXT_ITER> \
     --feedback "<error description from training.log tail>"
   ```
   Read `tail -50 <CHECKPOINT_DIR>/training.log` to understand what went wrong.
   Skip to Step 10 with a failure summary.

3. **If EXIT_CODE == 0** (experiment succeeded):
   - Read experiment output/logs to extract metrics. Look for:
     - JSON result files in `<CHECKPOINT_DIR>/`
     - Metric values in `<CHECKPOINT_DIR>/training.log` (tail)
     - Eval result files in the project
   - Extract the primary metric value (`METRIC_VALUE`) and any secondary metrics.

4. Record the result:
   ```bash
   python -m research_agent.state complete-iteration \
     --id <NEXT_ITER> \
     --metric-name <PRIMARY_METRIC> \
     --metric-value <METRIC_VALUE> \
     --feedback "<brief observation about the result>"
   ```

---

## Step 9: Commit Results + Merge

1. Commit results:
   ```bash
   python -m research_agent.git_ops commit-results \
     --iteration <NEXT_ITER> \
     --state state.json
   ```

2. Push:
   ```bash
   python -m research_agent.git_ops push
   ```

3. Check if this is a new best. Read state:
   ```bash
   python -m research_agent.state read --field best
   ```
   If this iteration is the new best:
   ```bash
   python -m research_agent.git_ops merge-best --state state.json
   python -m research_agent.git_ops push
   ```

---

## Step 10: Present Results Summary

Present a clear summary to the user:

### On success:
```
## Results: Iteration <N>

**Idea:** <SELECTED_IDEA_TITLE>
**Hypothesis:** <HYPOTHESIS>
**Papers:** <PAPERS_USED>

**Changes:** <CHANGE_DESC>
- Files modified: <FILES>

**Results:**
- <PRIMARY_METRIC>: <VALUE> (baseline: <BASELINE>, delta: <DELTA>)
- <SECONDARY_METRICS if any>

**Verdict:** <NEW_BEST / IMPROVED / NO_IMPROVEMENT / REGRESSED>

**Suggestion for next iteration:** <based on what you learned>
```

### On failure:
```
## Results: Iteration <N> — FAILED

**Idea:** <SELECTED_IDEA_TITLE>
**Hypothesis:** <HYPOTHESIS>
**Error:** <what went wrong>

**Suggestion:** <how to fix or what to try instead>
```

---

## Fallback Chain

| Level | Paper fetch | Idea generation | Implementation |
|---|---|---|---|
| Full | `idea_discovery.py --fetch-only` | Agent subagent | Agent subagent |
| Partial | `search_papers.py` | Agent subagent | Agent subagent |
| Minimal | WebSearch | Orchestrator synthesizes | Agent subagent |
| Direct | None | User's raw idea | Agent subagent |

Implementation always goes through the Agent tool. Only the quality of paper context degrades.

---

## Rules

- NEVER implement code yourself. ALWAYS use the Agent tool.
- NEVER call `code_implementation.py` or `literature_search.py` — they are archived.
- Paper fetching uses pure Python scripts (`idea_discovery.py --fetch-only`, `search_papers.py`) — always safe.
- ONE change per invocation.
- Run steps sequentially.
- Keep the user informed with brief status updates at each major step.
- ALWAYS commit code BEFORE running experiments.
- ALWAYS push after commits.
- Each iteration gets a UNIQUE checkpoint directory — never reuse.
- The final output MUST be a results summary, not just a diff.
