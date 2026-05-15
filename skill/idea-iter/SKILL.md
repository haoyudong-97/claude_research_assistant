---
name: idea-iter
description: Autonomous research pipeline — idea to launched experiment in one shot.
when_to_use: When the user gives a research idea and expects code + experiment, or says "research and implement", "idea to code", "idea iter", "take this idea and build it", "implement this concept", or any phrasing that implies going from a rough idea to code changes. This skill launches the experiment and returns — use /check-experiments to see results.
argument-hint: <rough idea or research direction> [--auto]
arguments: idea
disable-model-invocation: false
version: "0.3.0"
effort: high
allowed-tools: Bash(python -m research_agent:*), Bash(claude:*), Bash(test:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(git branch:*), Bash(cat:*), Bash(sleep:*), Read, Grep
---

# Idea-Iter: Autonomous Research Orchestrator

You are orchestrating research iterations. The user gives you one or more ideas — you dispatch each phase as a **separate background agent** via `claude --bg`, keeping this conversation lean. Each agent gets a fresh context window with only the information it needs.

```
/idea-iter try attention gates in the decoder
/idea-iter add mixup augmentation and try label smoothing
/idea-iter --auto increase batch size from 2 to 4
```

**Multiple ideas:** If the user gives multiple ideas separated by "and", "also", commas, or numbered lists, treat each as a separate iteration. Run them sequentially — each gets its own branch and checkpoint.

Your FIRST action must be to set up the Python tools:

```bash
export PYTHONPATH="$HOME/.claude/skills/idea-iter:$PYTHONPATH"
```

---

## Background Agent Helpers

### Dispatching a phase

To dispatch a phase as a background agent:

```bash
claude --bg "<PROMPT>" 2>&1 | grep "backgrounded" | awk '{print $NF}'
```

This returns the session ID (e.g., `a1b2c3d4`). Store it as `SESSION_ID`.

### Waiting for completion

Poll the session state file until the agent finishes:

```bash
while true; do
    STATE=$(python3 -c "
import json, sys
try:
    s = json.load(open('$HOME/.claude/jobs/$SESSION_ID/state.json'))
    print(s.get('state', 'unknown'))
except: print('unknown')
" 2>/dev/null)
    if [ "$STATE" = "done" ] || [ "$STATE" = "completed" ] || [ "$STATE" = "stopped" ] || [ "$STATE" = "failed" ]; then
        echo "DONE: $STATE"
        break
    fi
    sleep 15
done
```

### Reading agent output

After completion, read the agent's result from the timeline:

```bash
python3 -c "
import json
with open('$HOME/.claude/jobs/$SESSION_ID/timeline.jsonl') as f:
    for line in f:
        entry = json.loads(line)
        if 'text' in entry:
            print(entry['text'])
" 2>/dev/null | tail -50
```

### Cleaning up

After reading the output, stop the session:

```bash
claude stop $SESSION_ID 2>/dev/null
```

---

## Phase 1: Validate & Load State (inline)

This phase is fast — run it directly, no background agent needed.

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

**Read the research history before proceeding:**

```bash
test -f progress.md && cat progress.md || echo "NO_PROGRESS"
```

This is your research memory. Pay attention to:
- **What Worked** — build on successful approaches
- **What Didn't Work** — avoid repeating failed ideas
- **Patterns** — plateau detection, improving/declining trends
- **Do Not Repeat** — these ideas have already been tried

Use this context when formulating your hypothesis and implementation plan. If the user's idea overlaps with something already tried, tell them: "Iter N already tried something similar — here's what happened: [result]. Want to proceed with a variant, or try something different?"

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

## Phase 2: Parse & Classify (inline + bg agent for paper search)

First, check if `$idea` contains multiple ideas. Split on "and", "also", commas, or numbered items. If multiple ideas are found, store them as a list: `IDEAS = [idea_1, idea_2, ...]`. You will run Phase 2–7 for each idea sequentially.

If only one idea, `IDEAS = [idea]`.

For each idea in `IDEAS`, decide how specific it is:

- **Specific** — the idea describes a concrete code change. You know exactly what to implement.
- **Exploratory** — the idea is a direction or question. You need papers to figure out *what* to implement.

### If Specific → skip to Phase 3

No paper search needed. Formulate directly:
- `HYPOTHESIS` — what you expect this change to achieve
- `CHANGE_DESC` — short summary for git
- `INSTRUCTION` — detailed implementation plan

### If Exploratory → dispatch paper search agent

Dispatch a background agent to search for papers and generate ideas:

```bash
claude --bg "You are a research paper search agent working in $(pwd).

export PYTHONPATH=\"\$HOME/.claude/skills/idea-iter:\$PYTHONPATH\"

## Task
Search for papers relevant to: <IDEA>

## Steps
1. Run the arXiv + Semantic Scholar search:
   python -m research_agent.idea_discovery --categories <CATEGORIES> --days 7 --s2-query \"<IDEA>\" --papers-output results/recent_papers.json --limit 5

   If that fails, fallback:
   python -m research_agent.search_papers \"<IDEA>\" results/recent_papers.json --limit 5

2. Use WebSearch to find: \"<IDEA> recent paper 2025 2026 arxiv\"
   Extract up to 5 additional papers. Note them.

3. Read results/recent_papers.json, state.json, and progress.md (if they exist).
   progress.md is the research memory — it tells you what has been tried, what worked, what failed, and what to avoid.

4. From the papers, identify 3-5 relevant trends and propose 3-5 concrete research ideas aligned with: <IDEA>
   IMPORTANT: Check the 'Do Not Repeat' section in progress.md — do NOT propose ideas that overlap with already-tried iterations.
   Build on approaches listed under 'What Worked'. Avoid directions listed under 'What Didn't Work' unless you have a specific reason.

5. Write output to results/ideas.json as JSON:
   {
     \"trend_digest\": [\"Trend 1: ...\", ...],
     \"ideas\": [{\"id\": 1, \"title\": \"...\", \"hypothesis\": \"...\", \"approach\": \"...\", \"expected_impact\": \"...\", \"difficulty\": \"low\", \"relevant_papers\": [\"...\"], \"pilot_design\": {\"experiment\": \"...\", \"gpu_hours\": 0.5, \"success_criterion\": \"...\"}}]
   }

6. Do NOT modify any project code. Only write to results/.
" 2>&1 | grep "backgrounded" | awk '{print $NF}'
```

Store the session ID. **Wait for completion** using the polling helper above.

After the agent finishes, read `results/ideas.json`. Pick ONE idea based on relevance, feasibility (prefer low/medium), novelty (skip overlap with `LAST_ITERS`), and concreteness.

Formulate: `HYPOTHESIS`, `CHANGE_DESC`, `INSTRUCTION`, `PAPERS_USED`.

---

## Phase 3: Discuss with User (inline)

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

## Phase 4: Implement the Change (bg agent)

First, create a branch and register the iteration **inline** (git ops must happen in the main repo):

```bash
python -m research_agent.git_ops branch-start \
  --iteration <NEXT_ITER> \
  --change "<CHANGE_DESC>"
```

**If exit code is 2:** The current branch has unmerged work. Show the user the warning output and ask:

> **Warning:** You're on branch `<BRANCH>` which has unmerged commits/changes.
> 1. **Merge to main first** — merge useful code from `<BRANCH>` to main, then branch from updated main
> 2. **Continue anyway** — switch to main and branch (unmerged work stays on `<BRANCH>`)
> 3. **Cancel** — stop this iteration

Wait for the user's choice. If (1), run `git checkout main && git merge <BRANCH>` then re-run `branch-start --force`. If (2), re-run `branch-start --force`. If (3), stop.

```bash
python -m research_agent.state start-iteration \
  --hypothesis "<HYPOTHESIS>" \
  --change "<CHANGE_DESC>"
```

Now dispatch the implementation agent. The agent works in the project directory on the current branch:

```bash
claude --bg "You are implementing a code change in $(pwd).
You are on branch $(git rev-parse --abbrev-ref HEAD).

## First: Read progress.md
Read progress.md in the project root. This is the research memory — it shows what has been tried before, what worked, and what failed. Use it to inform your implementation.

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
<FOCUS_FILES or 'explore the codebase to find relevant files'>

## Rules
1. Read relevant code files first to understand the current implementation.
2. Implement one focused change. Use the Edit tool for modifications.
3. Make minimal, surgical edits — do not rewrite entire files.
4. Verify changes are syntactically correct.
5. If you need data, weights, or checkpoints, create symlinks (ln -sfn <source> <link>) — NEVER copy or download large files into the project. Add symlink targets to .gitignore.
6. When done, write a summary to results/impl_summary.json:
   {\"hypothesis\": \"...\", \"change_summary\": \"...\", \"files_modified\": [...], \"papers_used\": [...]}
7. Do NOT commit or push. Only edit code and write the summary.
" 2>&1 | grep "backgrounded" | awk '{print $NF}'
```

Store the session ID. **Wait for completion** using the polling helper.

After the agent finishes, verify the changes were made:

```bash
git diff --stat
```

If no changes and `results/impl_summary.json` doesn't exist, the implementation failed. Read the agent's timeline output to understand why, and report to the user.

---

## Phase 5: Review & Commit (inline)

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

## Phase 6: Launch Experiment (bg agent)

Find the training script. Check in order:
1. `state.json` — previous iterations may have checkpoint paths hinting at the script
2. File search — look for `train*.sh`, `train*.py`, `run*.sh`, `scripts/` directory
3. If not found — ask the user: "What script should I run?"

Pick a unique checkpoint directory (e.g., `checkpoints/iter_<NEXT_ITER>`).

Dispatch the launch agent:

```bash
claude --bg "You are launching an experiment in $(pwd).

export PYTHONPATH=\"\$HOME/.claude/skills/idea-iter:\$PYTHONPATH\"

## Task
1. Run GPU pre-flight check:
   python -m research_agent.deploy preflight

2. If GPUs available, launch the experiment:
   python -m research_agent.deploy launch <EXP_SCRIPT> <CHECKPOINT_DIR>

   For remote deployment, add: --host <HOST>

3. After launching, update state:
   python -m research_agent.state launch-iteration --id <NEXT_ITER> --checkpoint \"<CHECKPOINT_DIR>\"

4. Report which GPU was selected and the PID.

If no GPUs are available, report that and exit — do NOT wait.
" 2>&1 | grep "backgrounded" | awk '{print $NF}'
```

Store the session ID. **Wait for completion** using the polling helper.

After the agent finishes, read its output to confirm the experiment launched. If it reported no GPUs, tell the user.

**Clean up the session and return control to the user. Do not poll the experiment.**

---

## Phase 7: Summary & Next Idea (inline)

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

Clean up all finished background sessions:

```bash
claude stop $PAPER_SESSION_ID 2>/dev/null
claude stop $IMPL_SESSION_ID 2>/dev/null
claude stop $LAUNCH_SESSION_ID 2>/dev/null
```

---

## Fallback Chain

| Idea type | Paper search | Idea generation | Implementation |
|---|---|---|---|
| Specific idea | Skipped | User's idea directly | bg agent |
| Exploratory + papers found | bg agent (arXiv + WebSearch) | bg agent proposes from papers | bg agent |
| Exploratory + search fails | bg agent (WebSearch only) | bg agent or orchestrator | bg agent |
| Exploratory + all fails | None | User refines the idea | bg agent |

Each heavy phase runs as its own `claude --bg` session. The orchestrator (this conversation) handles state, user interaction, git branching, and coordination.

---

## Rules

### MANDATORY: Use `claude --bg` for all code work

**You MUST dispatch code implementation, paper search, and experiment launch to `claude --bg` sessions. You MUST NOT write code, create files, or edit files directly in this conversation.** This is not a suggestion — the `Edit`, `Write`, and `Agent` tools are intentionally not available to this skill.

Why this is non-negotiable:
- Each bg session gets a **fresh context window** — this conversation stays clean
- bg sessions run in **isolated worktrees** — no git conflicts between tasks
- The orchestrator's job is to **coordinate, not implement**
- Inline code writing causes context bloat, branch drift (the iter/23 problem), and git lock conflicts

**This conversation may only:**
- Read files (Read, Grep) — to check results, read progress.md, review diffs
- Run research_agent Python tools — state management, git ops, deploy
- Run `claude --bg` — to dispatch work
- Run git commands — branching, committing, pushing
- Communicate with the user — discuss plans, show results

**This conversation must NOT:**
- Write or edit any project code files
- Use the Agent tool to spawn inline subagents for code work
- Implement anything directly, no matter how small the task seems

If a task seems "too small" for `claude --bg`, dispatch it anyway. The overhead is worth it to keep this conversation clean and organized.

### Other rules

- **Wait for each agent to complete before proceeding.** Poll `~/.claude/jobs/<id>/state.json` for `"state": "completed"` or `"stopped"`.
- **Git operations stay inline.** Branch creation, commits, and pushes run in this conversation — never in a bg agent. This prevents worktree isolation from diverging branches.
- **Bg agents do NOT commit or push.** They only edit code and write output files. The orchestrator handles all git operations.
- Paper fetching uses Python scripts (`idea_discovery.py`, `search_papers.py`) — always safe.
- Update state.json after launching experiments (use `state launch-iteration`).
- One change per invocation. Run phases sequentially.
- Commit code before launching experiments. Push after commits.
- Each iteration gets a unique checkpoint directory — never reuse.
- After launching, return immediately. Do not poll for experiment completion.
- When handling multiple ideas: complete ALL phases for one idea before starting the next.
- Clean up background sessions (`claude stop <id>`) after reading their output.

### Data & weights: symlink, never copy

Large files (datasets, model weights, checkpoints, preprocessed data) **must not** live inside the git-tracked project tree. Branch switching, rebasing, or cleaning will wipe them.

**Rule:** When the implementation needs data or weights, **symlink** them into the project from a stable location outside the repo. Never copy, move, or download them directly into the project directory.

```bash
# Good — symlink from a stable path
ln -sfn /data/datasets/AMOS_CT nnUNet_raw/Dataset003_AMOS_CT
ln -sfn /data/checkpoints/iter_5 checkpoints/iter_5

# Bad — copying into the repo (will be lost on branch switch)
cp -r /data/datasets/AMOS_CT nnUNet_raw/Dataset003_AMOS_CT
```

Ensure `.gitignore` covers all large-file directories. At project init or first iteration, verify these patterns exist in `.gitignore`:

```
checkpoints/
nnUNet_raw/
nnUNet_preprocessed/
nnUNet_results/
*.pth
*.npz
*.nii.gz
```

If missing, add them before committing.
