---
name: idea-iter
description: Autonomous research pipeline — idea to launched experiment in one shot.
when_to_use: When the user gives a research idea and expects code + experiment, or says "research and implement", "idea to code", "idea iter", "take this idea and build it", "implement this concept", or any phrasing that implies going from a rough idea to code changes. This skill launches the experiment and returns — use /check-experiments to see results.
argument-hint: <rough idea or research direction> [--auto]
arguments: idea
disable-model-invocation: false
version: "0.2.0"
effort: high
allowed-tools: Bash(python -m research_agent:*), Bash(test:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(git branch:*), Read, Grep, WebFetch(domain:arxiv.org), WebFetch(domain:semanticscholar.org), WebSearch, Agent
hooks:
  PreToolUse:
    - matcher: Bash
      hooks:
        - type: command
          command: "python $HOME/.claude/skills/idea-iter/research_agent/hooks/track_state.py"
  PostToolUse:
    - matcher: Bash|Edit
      hooks:
        - type: command
          command: "python $HOME/.claude/skills/idea-iter/research_agent/hooks/track_state.py"
---

# Idea-Iter: Autonomous Research Orchestrator

You are orchestrating a research iteration. The user gives you one rough idea — you turn it into a running experiment, then return control immediately so they can launch more iterations in parallel.

```
/idea-iter try attention gates in the decoder
/idea-iter improve model generalization with mixup
/idea-iter --auto increase batch size from 2 to 4
```

Your FIRST action must be to set up the Python tools:

```bash
export PYTHONPATH="$HOME/.claude/skills/idea-iter:$PYTHONPATH"
```

Run this once. All subsequent commands use `python -m research_agent.<module>`.

---

## Phase 1: Validate & Load State

Confirm this is a git repository:

```bash
cd "$(git rev-parse --show-toplevel)"
```

If this fails, stop and tell the user: "This is not a git repo. Run `git init` first."

Now load research state:

```bash
test -f state.json && python -m research_agent.state read || echo "NO_STATE"
```

Note the values: `GOAL`, `BASELINE`, `BEST`, `LAST_ITERS`, `PRIMARY_METRIC`.

If no state exists, create one:

```bash
python -m research_agent.state init --goal "$idea" --metric "improvement"
```

Get the next iteration number:

```bash
python -m research_agent.state read --field next_id
```

Store the result as `NEXT_ITER`. Infer arXiv `CATEGORIES` from the idea:
- Medical/imaging → `medical-imaging`
- Vision/CV → `cs.CV`
- ML/learning → `cs.LG`
- NLP/language → `nlp`
- Unsure → `cs.CV,cs.LG`

---

## Phase 2: Fetch Papers (two sources, ~10 total)

### 2a: arXiv + Semantic Scholar (structured, with full text)

Run the Python search — this returns 5 relevance-ranked papers with full text from arXiv HTML:

```bash
python -m research_agent.idea_discovery \
  --categories <CATEGORIES> \
  --days 7 \
  --s2-query "<IDEA>" \
  --papers-output results/recent_papers.json \
  --limit 5
```

If this fails, fall back to:

```bash
python -m research_agent.search_papers "<IDEA>" results/recent_papers.json --limit 5
```

### 2b: WebSearch (broader coverage)

Use the `WebSearch` tool to search for: `"<IDEA>" recent paper 2025 2026 arxiv`

From the results, extract up to 5 papers NOT already in `results/recent_papers.json`. For each, record title, authors, year, abstract (from snippet), url, and `source: "web_search"`. Append them to `results/recent_papers.json`.

For any WebSearch paper with an arXiv URL, use `WebFetch` on the abstract page to get the full abstract.

### Result

After both steps, `results/recent_papers.json` should contain ~10 papers. If one source fails, proceed with whatever the other returned. If all search fails, skip to Phase 3 with just the user's raw idea.

---

## Phase 3: Generate Ideas & Select Approach

### 3a: Launch idea generation Agent

Spawn an Agent (subagent_type: general-purpose) with this prompt:

```
Read results/recent_papers.json in the project root.
It contains ~10 papers: some with full text (from arXiv), some with abstracts only (from web search).
Also read state.json if it exists for project context.

The user's research idea is: <IDEA>

From these papers:
1. Identify the 3-5 most relevant trends/techniques.
2. Propose 3-5 concrete research ideas aligned with the user's idea.

For each idea include: title, hypothesis, approach (specific code changes), expected_impact, difficulty (low/medium/high), relevant_papers, and a pilot_design (what to run, estimated gpu_hours, success_criterion).

Write output to results/ideas.json as JSON:
{
  "trend_digest": ["Trend 1: ...", ...],
  "ideas": [{"id": 1, "title": "...", "hypothesis": "...", "approach": "...", "expected_impact": "...", "difficulty": "low", "relevant_papers": ["..."], "pilot_design": {"experiment": "...", "gpu_hours": 0.5, "success_criterion": "..."}}]
}

This is a research-only task. Do not modify any project code.
```

**Wait for the Agent to complete.**

### 3b: Select the best approach

Read `results/ideas.json`. Pick ONE idea based on relevance to `IDEA`, feasibility (prefer low/medium difficulty), novelty (skip what overlaps with `LAST_ITERS`), and concreteness.

Formulate: `HYPOTHESIS`, `CHANGE_DESC` (short, for git), `INSTRUCTION` (detailed, for the implementation Agent), `PAPERS_USED`.

Tell the user in 2-3 lines which approach you picked and why.

If no ideas.json exists (Agent or fetch failed), formulate an instruction directly from the user's raw `IDEA`.

### 3c: Confirm with user

If `$idea` contains `--auto`, skip confirmation and proceed.

Otherwise, present:

> **Selected approach:** <TITLE>
> **Hypothesis:** <HYPOTHESIS>
> **What will change:** <CHANGE_DESC>
> **Pilot:** <PILOT_EXPERIMENT> (~<GPU_HOURS> GPU-hours)
>
> Proceed with: **Full experiment** / **Pilot first** / **Modify** / **Skip**

- **Full experiment** → continue to Phase 4
- **Pilot first** → continue to Phase 4 with pilot_design parameters (fewer epochs, smaller data)
- **Modify** → user gives feedback, reformulate, ask again
- **Skip** → stop here

**Wait for user response before continuing.**

---

## Phase 4: Implement the Change

Create a branch and register the iteration:

```bash
python -m research_agent.git_ops branch-start \
  --iteration <NEXT_ITER> \
  --change "<CHANGE_DESC>"
```

```bash
python -m research_agent.state start-iteration \
  --hypothesis "<HYPOTHESIS>" \
  --change "<CHANGE_DESC>"
```

Now spawn an Agent (subagent_type: general-purpose) to implement the code change:

```
You are implementing a code change in this project.

## Instruction
<INSTRUCTION>

## Project Context
- Goal: <GOAL>
- Primary metric: <METRIC>
- Baseline: <BASELINE_METRICS>
- Current best (iter <N>): <BEST_METRICS>
- Last change: <LAST_CHANGE> → <LAST_RESULT>

## Papers
<PAPER_TITLES_AND_KEY_IDEAS>

## Key files
<FOCUS_FILES or "explore the codebase to find relevant files">

## Rules
1. Read relevant code files first to understand the current implementation.
2. Implement one focused change. Use the Edit tool for modifications.
3. Make minimal, surgical edits — do not rewrite entire files.
4. Verify changes are syntactically correct.
5. Write a summary to results/impl_summary.json:
   {"hypothesis": "...", "change_summary": "...", "files_modified": [...], "papers_used": [...]}
```

**Wait for the Agent to complete.**

---

## Phase 5: Review & Commit

Read `results/impl_summary.json` and show the diff:

```bash
git diff
```

Briefly tell the user what changed and why. Then commit and push:

```bash
python -m research_agent.git_ops commit-code \
  --iteration <NEXT_ITER> \
  --hypothesis "<HYPOTHESIS>" \
  --change "<CHANGE_DESC>" \
  --papers "<PAPER1>" "<PAPER2>"
```

```bash
python -m research_agent.git_ops push
```

---

## Phase 6: Launch Experiment

Find the training script. Check in order:
1. `state.json` — previous iterations may have checkpoint paths hinting at the script
2. File search — look for `train*.sh`, `train*.py`, `run*.sh`, `scripts/` directory
3. If not found — ask the user: "What script should I run?"

Pick a unique checkpoint directory (e.g., `checkpoints/iter_<NEXT_ITER>`).

Run a GPU pre-flight check:

```bash
python -m research_agent.deploy preflight
```

If GPUs are available, launch. If not, ask the user whether to proceed or wait.

Launch the experiment with `run_in_background: true`:

```bash
python -m research_agent.deploy launch <EXP_SCRIPT> <CHECKPOINT_DIR>
```

The PostToolUse hook auto-updates state.json — no manual `state launch-iteration` call needed.

For remote deployment, add `--host <HOST>`. The tool auto-selects the GPU with most free memory, syncs code via rsync, and launches in a screen session.

**Return control to the user immediately. Do not poll.**

---

## Phase 7: Summary

Tell the user:

```
## Iteration <N> — Launched

**Idea:** <TITLE>
**Hypothesis:** <HYPOTHESIS>
**Changes:** <CHANGE_DESC> (files: <FILES>)
**Experiment:** running in `<CHECKPOINT_DIR>`

## What you can do now
- `/idea-iter <another idea>` — launch iteration <N+1> in parallel
- `/combine-findings <paper url>` — integrate a paper into current work
- `/check-experiments` — check when experiments finish
```

---

## Fallback Chain

| Level | Paper fetch | Idea generation | Implementation |
|---|---|---|---|
| Full | `idea_discovery.py` (top 5 + fulltext) + WebSearch (5 more) | Agent | Agent |
| Partial | `search_papers.py` (5) | Agent | Agent |
| Minimal | WebSearch only | You synthesize | Agent |
| Direct | None | User's raw idea | Agent |

Implementation always goes through the Agent tool. Only paper context quality degrades.

---

## Rules

- Always delegate code changes to an Agent subagent. Use the Edit tool, not Write.
- Paper fetching uses Python scripts (`idea_discovery.py`, `search_papers.py`) — always safe.
- State tracking is automatic via PostToolUse hooks on deploy, git commit, and git checkout.
- One change per invocation. Run phases sequentially.
- Commit code before launching experiments. Push after commits.
- Each iteration gets a unique checkpoint directory — never reuse.
- After launching, return immediately. Do not poll for completion.
