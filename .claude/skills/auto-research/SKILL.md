---
name: auto-research
description: Research pipeline from idea to launched experiment. TRIGGER when the user gives a research idea and expects code + experiment, or says "research and implement", "idea to code", "auto-research", "take this idea and build it", "implement this concept", or any phrasing that implies going from a rough idea to code changes. This skill launches the experiment and returns — use /check-experiments to see results.
argument-hint: <rough idea or research direction> [--auto]
disable-model-invocation: false
allowed-tools: Bash(python:*), Bash(cat:*), Bash(test:*), Bash(bash:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(git branch:*), Read, Grep, WebFetch, WebSearch, Agent
---

# Auto-Research: Idea → Code → Launch

You are an autonomous research orchestrator. The user gives you ONE rough idea. You implement it and **launch the experiment**, then return control so the user can start another iteration concurrently.

Pipeline: **fetch papers → select approach → implement code → commit → launch experiment → return**

Use `/check-experiments` to collect results after experiments finish.

## Architecture — What runs where

| Step | Who does it | How |
|---|---|---|
| Paper fetching | Python scripts | `idea_discovery.py --fetch-only` or `search_papers.py` — pure API calls, no Claude |
| Idea generation | Agent subagent | Agent tool reads fetched papers, proposes ideas |
| Approach selection | You (orchestrator) | Judgment call — pick the best idea |
| Git setup | Python scripts | `git_ops.py`, `state.py` — pure CLI |
| Code implementation | Agent subagent | Agent tool reads code, makes edits |
| GPU preflight | Python script | `deploy.py preflight` — checks GPU availability |
| Launch experiment | Python script | `deploy.py launch` — local or remote via SSH+screen |

**NEVER call `code_implementation.py` or `literature_search.py`** — they are archived.

---

## Step 0: Load Context

```bash
cd "$(git rev-parse --show-toplevel)"
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
cd "$(git rev-parse --show-toplevel)" && \
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
Read the file results/recent_papers.json in the project root.
Also read state.json if it exists for project context.

The user's research idea is: <IDEA>

From these papers:
1. Identify the 3-5 most relevant trends/techniques.
2. Propose 3-5 concrete research ideas aligned with the user's idea.

For each idea include: title, hypothesis, approach (specific code changes), expected_impact, difficulty (low/medium/high), relevant_papers, and a pilot_design (minimal experiment to test signal before full commitment: what to run, estimated gpu_hours, and success_criterion).

Write output to results/ideas.json as JSON:
{
  "trend_digest": ["Trend 1: ...", ...],
  "ideas": [{"id": 1, "title": "...", "hypothesis": "...", "approach": "...", "expected_impact": "...", "difficulty": "low", "relevant_papers": ["..."], "pilot_design": {"experiment": "...", "gpu_hours": 0.5, "success_criterion": "..."}}]
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

### 2c: Ask for confirmation (unless `--auto`)

If `$ARGUMENTS` contains `--auto`, skip this step and proceed directly.

Otherwise, present the selected approach to the user and ask:

> **Selected approach:** <TITLE>
> **Hypothesis:** <HYPOTHESIS>
> **What will change:** <CHANGE_DESC>
> **Pilot:** <PILOT_EXPERIMENT> (~<GPU_HOURS> GPU-hours)
> **Pilot success criterion:** <SUCCESS_CRITERION>
>
> Proceed with: Full experiment / Pilot first / Modify / Skip

- **Full experiment** → continue to Step 3 with full experiment
- **Pilot first** → continue to Step 3 but use the pilot_design parameters (fewer epochs, smaller data) for a quick signal check
- **Modify** → user gives feedback, reformulate INSTRUCTION, then continue
- **Skip** → stop here, do not implement

**Wait for user response before continuing.**

---

## Step 3: Git Setup + Register Iteration

```bash
cd "$(git rev-parse --show-toplevel)" && \
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
Working directory: the project root (git repo root)

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

## Step 6: Discover Experiment Script + Launch

Find the experiment/training script to run. Check in order:

1. **progress.md** — look for a line like `Experiment script: scripts/train.sh` or `## How to run` section above the sentinel.
2. **state.json** — check if previous iterations have checkpoint paths that hint at the script location.
3. **File search** — look for `train*.sh`, `train*.py`, `run*.sh`, `experiment*.sh`, `scripts/` directory in the project.
4. **If not found** — ask the user: "What script should I run for the experiment? (e.g., `bash scripts/train.sh`)"

Determine a unique **checkpoint directory** (e.g., `checkpoints/iter_<NEXT_ITER>`).

### Pre-flight GPU check:

```bash
python -m research_agent.deploy preflight
```

If GPUs are available, proceed. If not, tell the user and ask whether to launch anyway or wait.

### Launch the experiment (non-blocking):

```bash
python -m research_agent.state launch-iteration \
  --id <NEXT_ITER> \
  --checkpoint "<CHECKPOINT_DIR>"
```

Launch in background using `run_in_background: true`:
```bash
python -m research_agent.deploy launch <EXP_SCRIPT> <CHECKPOINT_DIR>
```

For remote GPU deployment, add `--host <HOST>`:
```bash
python -m research_agent.deploy launch <EXP_SCRIPT> <CHECKPOINT_DIR> --host <HOST>
```

This auto-selects the GPU with most free memory, syncs code to remote, and launches in a screen session.

**Do NOT poll. Return control to the user immediately.**

---

## Step 7: Present Launch Summary

Tell the user:

```
## Iteration <N> — Launched

**Idea:** <SELECTED_IDEA_TITLE>
**Hypothesis:** <HYPOTHESIS>
**Changes:** <CHANGE_DESC> (files: <FILES>)
**Experiment:** running in `<CHECKPOINT_DIR>`

Run `/check-experiments` to see results when training finishes.
You can start another `/auto-research <new idea>` now — it will run as iteration <N+1> concurrently.
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
- ALWAYS commit code BEFORE launching experiments.
- ALWAYS push after commits.
- Each iteration gets a UNIQUE checkpoint directory — never reuse.
- After launching the experiment, RETURN IMMEDIATELY. Do NOT poll for completion.
