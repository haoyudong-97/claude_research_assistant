# Pipeline Steps (Detail)

Here's exactly what `/idea-iter <idea>` does under the hood:

## Step 0: Load Context

Reads `state.json` (goal, baseline, best result, iteration history) and `progress.md` (user's goal and constraints). If no state exists, initializes one from the idea.

```bash
python -m research_agent.state read    # recover full context
head -30 progress.md                   # check user's notes
```

## Step 1: Fetch Papers

Calls arXiv RSS + API and Semantic Scholar to find relevant papers. Pure Python — no Claude needed, always works.

```bash
python research_agent/idea_discovery.py \
  --categories <inferred> --days 7 --s2-query "<idea>" \
  --fetch-only --papers-output results/recent_papers.json
```

Fallback: `search_papers.py "<idea>" results/recent_papers.json --limit 15`

## Step 2: Generate Ideas + Select Approach

**2a.** An Agent subagent reads the fetched papers and proposes 3-5 concrete research ideas with hypothesis, approach, expected impact, and difficulty. Output: `results/ideas.json`.

**2b.** The orchestrator selects ONE idea based on relevance, feasibility, novelty (vs previous iterations), and concreteness. Tells the user which approach and why.

## Step 3: Git Setup + Register Iteration

Creates a dedicated branch and registers the iteration in state:

```bash
python -m research_agent.git_ops branch-start --iteration <N> --change "<description>"
python -m research_agent.state start-iteration --hypothesis "..." --change "..."
```

State moves to `coding` status. Shows in `progress.md` Active Experiments.

## Step 4: Implement Code

An Agent subagent receives a detailed prompt with the instruction, project context, papers, and key files. It reads the codebase, makes surgical edits, and writes a summary to `results/impl_summary.json`.

## Step 5: Review + Commit Code

Shows `git diff` and briefly explains what changed. Then commits and pushes:

```bash
python -m research_agent.git_ops commit-code --iteration <N> \
  --hypothesis "..." --change "..." --papers "..."
python -m research_agent.git_ops push
```

## Step 6: Discover Experiment Script

Finds the training script to run by checking (in order):
1. `progress.md` — look for script path or "How to run" section
2. `state.json` — checkpoint path patterns from previous iterations
3. File search — `train*.sh`, `train*.py`, `scripts/` directory
4. Ask the user if not found

## Step 6.5: GPU Pre-flight Check

```bash
python -m research_agent.deploy preflight                    # local
python -m research_agent.deploy preflight --host gpu-server  # remote
```

Checks GPU availability before launching. Reports free memory per GPU. Warns if no GPU has enough free memory.

## Step 7: Run Experiment

Marks iteration as running and launches the experiment:

```bash
python -m research_agent.state launch-iteration --id <N> --checkpoint "checkpoints/iter_<N>"
python -m research_agent.deploy launch <script> checkpoints/iter_<N>
```

For remote GPU servers:
```bash
python -m research_agent.deploy launch <script> checkpoints/iter_<N> --host gpu-server
```

This auto-selects the GPU with most free memory, syncs code if remote, and launches in a screen session. Polls via `python -m research_agent.deploy status`. State moves to `running` status.

## Step 8: Analyze Results

Reads the exit code from `.done` and extracts metrics from checkpoint dir / training log.

- **Success:** extracts primary metric value + secondary metrics
- **Failure:** reads `training.log` tail for error diagnosis

## Step 9: Record Results

Updates state and `progress.md`:

```bash
# On success:
python -m research_agent.state complete-iteration --id <N> \
  --metric-name <metric> --metric-value <value> --feedback "..."

# On failure:
python -m research_agent.state fail-iteration --id <N> --feedback "<error>"
```

## Step 10: Commit Results + Merge

```bash
python -m research_agent.git_ops commit-results --iteration <N> --state state.json
python -m research_agent.git_ops push
```

If this iteration is the new best:
```bash
python -m research_agent.git_ops merge-best --state state.json
python -m research_agent.git_ops push
```

## Step 11: Present Results Summary

```
## Results: Iteration <N>

Idea: <title>
Hypothesis: <what we expected>
Papers: <cited papers>

Changes: <description>
  Files modified: model.py, config.py

Results:
  <primary_metric>: 0.918 (baseline: 0.905, delta: +0.013)

Verdict: NEW BEST

## All Iterations
| # | Change | <primary_metric> | vs baseline |
|---|--------|------------------|-------------|
| 1 | ...    | 0.908            | +0.003      |
| 2 | ...    | 0.918            | +0.013      |

Suggestion: Try combining this with <next idea>
```
