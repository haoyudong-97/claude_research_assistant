## Research Loop Protocol

When asked to start a research loop, follow this protocol. You are running in a **live tmux session** — the user can watch your progress, detach/reattach, and provide feedback.

### progress.md

The user creates `progress.md` to define the research goal. The agent auto-updates it with tracking data below the sentinel line. **Never edit the user's goal section above the sentinel.**

**User creates:**
```markdown
# Research Goal

Improve heart segmentation 3D Dice above 0.92 using adapter architecture changes.

## Constraints
- Keep parameter count under 1M
- Must converge within 200 epochs
```

**Agent updates everything below** `<!-- AGENT PROGRESS BELOW -->` automatically via `state.py`.

### Git Tracking

Every iteration is tracked as a **git branch** with structured commits. This gives full traceability — `git log` shows every hypothesis and result, `git diff` between iterations shows exactly what changed.

**Branch structure:**
```
main                          ← always has the best-performing code
├── iter/1-spd-rank-increase  ← branch per iteration
├── iter/2-tokenwise-film     ← each has 2 commits: code + results
└── iter/3-bias-scale-tuning
```

**Each iteration creates 2 commits:**
1. **Code commit** (before experiment) — records hypothesis, change, papers
2. **Results commit** (after experiment) — records metrics, delta vs baseline

**Best iteration merges to main**, so `main` always reflects the top configuration.

### Setup (first time only)

1. Read the user's `progress.md` to understand the goal.
2. Initialize state from it:
   ```
   python -m research_agent.state init --progress progress.md --metric "<primary_metric>"
   ```
3. Identify baseline: read existing results, record in state:
   ```
   python -m research_agent.state set-baseline --checkpoint "<path>" --metrics '{"metric": value}'
   ```
   (This auto-updates `progress.md`.)

### Each Iteration

1. **Read state** — recover full context after compression:
   ```
   python -m research_agent.state read
   ```

2. **Search literature** — use the Python search tool (Semantic Scholar + arXiv):
   ```
   python research_agent/search_papers.py \
     "orthogonal adapter Gram-preserving fine-tuning for ViT" \
     results/search_iter3.json \
     --limit 10 --year-min 2023
   ```
   - The query must be specific to this iteration's technique.
   - Use `--related-to <arxiv_id>` to find papers related to a known one.
   - Read the JSON results, evaluate relevance to the project, pick top papers.
   - Supplement with your own WebSearch if the APIs miss key papers.

3. **Form hypothesis** — based on papers + previous results.

4. **Create branch** — start a git branch for this iteration:
   ```
   python -m research_agent.git_ops branch-start \
     --iteration 3 --change "enable token-wise FiLM"
   ```

5. **Implement** — make ONE principal change. Create a new experiment script if needed.

6. **Commit code** — commit changes with structured message (before running experiment):
   ```
   python -m research_agent.git_ops commit-code \
     --iteration 3 \
     --hypothesis "Token-wise FiLM enables per-token adaptation" \
     --change "cond_scale_tokenwise=True" \
     --papers "FiLM 2018" "AdaptFormer 2022" \
     --checkpoint "checkpoints/exp_tokenfilm"
   ```

7. **Push branch** — push to GitLab so changes are backed up while experiment runs:
   ```
   python -m research_agent.git_ops push
   ```

8. **Execute** — launch experiment in background:
   ```
   bash research_agent/run_and_wait.sh <script> <checkpoint_dir>
   ```

9. **Poll** — check completion every ~10 minutes:
   ```
   test -f <checkpoint_dir>/.done && cat <checkpoint_dir>/.done || echo RUNNING
   ```

10. **Analyze** — read results, compare with baseline and previous best.

11. **Update state** — record iteration (auto-updates `progress.md`):
    ```
    python -m research_agent.state add-iteration \
      --hypothesis "..." --change "..." --checkpoint "..." \
      --metric-name <name> --metric-value <value> \
      --feedback "..."
    ```

12. **Commit results** — add a results commit to the branch:
    ```
    python -m research_agent.git_ops commit-results \
      --iteration 3 --state state.json
    ```

13. **If new best → merge to main** and push:
    ```
    python -m research_agent.git_ops merge-best --state state.json
    python -m research_agent.git_ops push
    ```

14. **Summarize** — present results and proposed next steps to user.

15. **Get feedback** — wait for user response before next iteration.

### Git Commands Reference

| Command | When | What it does |
|---------|------|-------------|
| `branch-start --iteration N --change "..."` | Before coding | Creates `iter/N-slug` from main |
| `commit-code --iteration N --hypothesis "..." --change "..."` | After coding, before experiment | Commits code with structured message |
| `commit-results --iteration N --state state.json` | After experiment results | Commits with metrics + delta vs baseline |
| `merge-best --state state.json` | When new best found | Merges best branch into main |
| `push` | After commit or merge | Pushes current branch to remote |
| `push-all` | Periodically | Pushes main + all iter branches |
| `log` | Anytime | Shows all iteration commits |

### Rules

- **ONE principal change per iteration** — isolate variables for clean comparison.
- **NEVER overwrite previous checkpoints** — each iteration gets a unique checkpoint directory.
- **ALWAYS commit before running experiments** — code changes must be tracked in git before any long-running job starts.
- **Re-read state.json** at the start of every iteration to recover context.
- **Primary metric drives decisions**; always report secondary metrics too.
- **Save experiment scripts** — each iteration's script should be reproducible.
- **Cite papers** — when a technique comes from literature, note the reference.
- **Never edit the user's goal section** in `progress.md`.
- **Push after every commit** — keep GitLab in sync so nothing is lost.
- **Present clear summaries** — the user is watching in tmux, make status updates readable.
