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
---

# Idea-Iter: Autonomous Research Orchestrator

You are orchestrating research iterations. The user gives you one or more ideas — you implement each as a separate iteration, then return control.

```
/idea-iter try attention gates in the decoder
/idea-iter add mixup augmentation and try label smoothing
/idea-iter --auto increase batch size from 2 to 4
```

**Multiple ideas:** If the user gives multiple ideas separated by "and", "also", commas, or numbered lists, treat each as a separate iteration. Run them sequentially — each gets its own branch and checkpoint. For example:

> `/idea-iter add attention gates and try deeper supervision`

→ Iteration N: add attention gates
→ Iteration N+1: try deeper supervision

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

## Phase 2: Parse & Classify

First, check if `$idea` contains multiple ideas. Split on "and", "also", commas, or numbered items. If multiple ideas are found, store them as a list: `IDEAS = [idea_1, idea_2, ...]`. You will run Phase 2–7 for each idea sequentially.

If only one idea, `IDEAS = [idea]`.

For each idea in `IDEAS`, decide how specific it is:

- **Specific** — the idea describes a concrete code change (e.g., "add attention gates to decoder skip connections", "increase batch size to 4", "replace ReLU with GELU in the encoder"). You know exactly what to implement.
- **Exploratory** — the idea is a direction or question (e.g., "improve generalization", "reduce inference time", "try something with text prompts"). You need papers to figure out *what* to implement.

### If Specific → skip to Phase 3

No paper search needed. Formulate directly:
- `HYPOTHESIS` — what you expect this change to achieve
- `CHANGE_DESC` — short summary for git
- `INSTRUCTION` — detailed implementation plan for the Agent

### If Exploratory → search for papers first

#### arXiv + Semantic Scholar (structured, with full text)

```bash
python -m research_agent.idea_discovery \
  --categories <CATEGORIES> \
  --days 7 \
  --s2-query "<IDEA>" \
  --papers-output results/recent_papers.json \
  --limit 5
```

Fallback: `python -m research_agent.search_papers "<IDEA>" results/recent_papers.json --limit 5`

#### WebSearch (broader coverage)

Use the `WebSearch` tool to search for: `"<IDEA>" recent paper 2025 2026 arxiv`

Extract up to 5 additional papers not already in `results/recent_papers.json`. Append them with `source: "web_search"`.

#### Generate ideas from papers

Spawn an Agent (subagent_type: general-purpose) with this prompt:

```
Read results/recent_papers.json in the project root.
Also read state.json if it exists for project context.

The user's research direction is: <IDEA>

From these papers:
1. Identify the 3-5 most relevant trends/techniques.
2. Propose 3-5 concrete research ideas aligned with the user's direction.

For each idea include: title, hypothesis, approach (specific code changes), expected_impact, difficulty (low/medium/high), relevant_papers, and a pilot_design (what to run, estimated gpu_hours, success_criterion).

Write output to results/ideas.json as JSON:
{
  "trend_digest": ["Trend 1: ...", ...],
  "ideas": [{"id": 1, "title": "...", "hypothesis": "...", "approach": "...", "expected_impact": "...", "difficulty": "low", "relevant_papers": ["..."], "pilot_design": {"experiment": "...", "gpu_hours": 0.5, "success_criterion": "..."}}]
}

This is a research-only task. Do not modify any project code.
```

**Wait for the Agent to complete.**

Read `results/ideas.json`. Pick ONE idea based on relevance, feasibility (prefer low/medium), novelty (skip overlap with `LAST_ITERS`), and concreteness.

Formulate: `HYPOTHESIS`, `CHANGE_DESC`, `INSTRUCTION`, `PAPERS_USED`.

---

## Phase 3: Discuss with User

Always discuss the plan before implementing — even for specific ideas.

If `$idea` contains `--auto`, skip this phase.

Present:

> **What I'll do:** <CHANGE_DESC>
> **Hypothesis:** <HYPOTHESIS>
> **Implementation plan:** <INSTRUCTION summary, 2-3 lines>
> **Papers:** <PAPERS_USED, if any — or "none, implementing your idea directly">
>
> Proceed? **Yes** / **Modify** / **Skip**

- **Yes** → continue to Phase 4
- **Modify** → user gives feedback, reformulate, present again
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

After launching, update state:

```bash
python -m research_agent.state launch-iteration \
  --id <NEXT_ITER> \
  --checkpoint "<CHECKPOINT_DIR>"
```

For remote deployment, add `--host <HOST>`. The tool auto-selects the GPU with most free memory, syncs code via rsync, and launches in a screen session.

**Return control to the user immediately. Do not poll.**

---

## Phase 7: Summary & Next Idea

If there are more ideas in `IDEAS`, show a brief summary for this iteration and loop back to Phase 2 for the next idea:

```
## Iteration <N> — Launched (<IDEA_INDEX>/<TOTAL_IDEAS>)
**Idea:** <TITLE>  |  Experiment: `<CHECKPOINT_DIR>`
Continuing to next idea...
```

If this is the last (or only) idea, show the full summary:

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

| Idea type | Paper search | Idea generation | Implementation |
|---|---|---|---|
| Specific idea | Skipped | User's idea directly | Agent |
| Exploratory + papers found | arXiv + WebSearch (~10) | Agent proposes from papers | Agent |
| Exploratory + search fails | WebSearch only | Agent or you synthesize | Agent |
| Exploratory + all fails | None | User refines the idea | Agent |

Implementation always goes through the Agent tool. Paper search only runs for exploratory ideas.

---

## Rules

- Always delegate code changes to an Agent subagent. Use the Edit tool, not Write.
- Paper fetching uses Python scripts (`idea_discovery.py`, `search_papers.py`) — always safe.
- Update state.json after launching experiments (use `state launch-iteration`).
- One change per invocation. Run phases sequentially.
- Commit code before launching experiments. Push after commits.
- Each iteration gets a unique checkpoint directory — never reuse.
- After launching, return immediately. Do not poll for completion.
- Never run git commands with `run_in_background`. Git operations must complete before the next step. Only `deploy launch` runs in background.
