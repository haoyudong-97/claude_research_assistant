# Skills (Slash Commands)

## `/auto-research <idea>` — Full Research Cycle

The main command. Takes a rough idea and delivers a results summary.

```
/auto-research use boundary-aware loss to improve segmentation edges
/auto-research try token-wise FiLM conditioning for adapter layers
/auto-research explore attention gating for skip connections
```

**Full pipeline:**

| Step | What happens | How |
|------|-------------|-----|
| 0. Load context | Read `state.json` + `progress.md` | `python -m research_agent.state read` |
| 1. Fetch papers | Search arXiv + Semantic Scholar | `idea_discovery.py --fetch-only` (pure Python) |
| 2a. Generate ideas | Digest papers, propose ideas | Agent subagent → `results/ideas.json` |
| 2b. Select approach | Pick best idea | Orchestrator judgment |
| 3. Git setup | Create branch, register iteration | `git_ops branch-start` + `state start-iteration` |
| 4. Implement code | Read code, make edits | Agent subagent → `results/impl_summary.json` |
| 5. Review + commit | `git diff`, commit, push | `git_ops commit-code` + `git_ops push` |
| 6. Discover script | Find experiment/training script | Check progress.md, state, or ask user |
| 7. Run experiment | Launch training, poll | `state launch-iteration` + `run_and_wait.sh` |
| 8. Analyze results | Extract metrics from output | Read checkpoint dir / training log |
| 9. Record results | Update state + progress.md | `state complete-iteration` or `fail-iteration` |
| 10. Commit + merge | Commit results, merge if best | `git_ops commit-results` + `merge-best` |
| 11. Present summary | Show metrics, verdict, next steps | Orchestrator output |

**Fallback chain:** If paper fetching fails, degrades gracefully (idea_discovery → search_papers → WebSearch → raw idea). Implementation always uses the Agent tool.

## `/find-papers <topic>` — Search Literature

Search for papers and generate research ideas.

```
/find-papers medical image segmentation transformers
/find-papers attention mechanisms --days 7
/find-papers PEFT adapters --categories machine-learning --fetch-only
```

**Steps:** fetch papers (pure Python) → present to user → generate ideas (Agent subagent) → offer to implement

## `/implement <instruction>` — Full Implementation Cycle

Implement a specific code change and run the experiment.

```
/implement increase spd_rank from 4 to 8
/implement add dropout after the adapter layer
/implement apply idea 3 from the last paper search
```

**Steps:** parse instruction → git branch → implement (Agent subagent) → commit → run experiment → analyze → record results → present summary

## `/combine-findings <input>` — Integrate New Input

Combine a paper, idea, or literature search with current research state.

```
/combine-findings https://arxiv.org/abs/2401.12345
/combine-findings try orthogonal regularization on adapter weights
/combine-findings find related literature
```

**Input types:**
- **Paper URL** — fetches paper, extracts key ideas, proposes hypothesis
- **Rough idea** — formulates hypothesis combining idea with current state
- **"find related literature"** — searches for papers, user picks, then implements
