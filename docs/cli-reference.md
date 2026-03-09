# CLI Reference

## state.py

```bash
python -m research_agent.state init --progress progress.md --metric test_3d_dice
python -m research_agent.state read
python -m research_agent.state read --field next_id          # next iteration number
python -m research_agent.state read --field best             # best result
python -m research_agent.state set-baseline --checkpoint "..." --metrics '{"test_3d_dice": 0.905}'
python -m research_agent.state start-iteration --hypothesis "..." --change "..."
python -m research_agent.state launch-iteration --id 3 --checkpoint "checkpoints/exp3"
python -m research_agent.state complete-iteration --id 3 --metric-name test_3d_dice --metric-value 0.912
python -m research_agent.state fail-iteration --id 3 --feedback "OOM error"
python -m research_agent.state report                        # full markdown report
```

### Iteration Lifecycle

| Command | From | To | When |
|---------|------|----|------|
| `start-iteration` | *(new)* | `coding` | After branch creation, before coding |
| `launch-iteration` | `coding` | `running` | After commit, before experiment |
| `complete-iteration` | `running` | `completed` | After experiment succeeds |
| `fail-iteration` | `coding`/`running` | `failed` | On error (OOM, NaN, abandoned) |
| `add-iteration` | *(new)* | `completed` | Shortcut: one-step create + complete |

## git_ops.py

```bash
python -m research_agent.git_ops branch-start --iteration 3 --change "enable tokenwise film"
python -m research_agent.git_ops commit-code --iteration 3 --hypothesis "..." --change "..."
python -m research_agent.git_ops commit-results --iteration 3 --state state.json
python -m research_agent.git_ops merge-best --state state.json
python -m research_agent.git_ops push
python -m research_agent.git_ops log
```

### Git Workflow

```
main                          ← best configuration (merged after each new best)
├── iter/1-spd-rank-increase  ← 2 commits: code + results
├── iter/2-tokenwise-film
└── iter/3-film-bias-scale
```

Each iteration: `branch-start` → `commit-code` → experiment → `commit-results` → (if best) `merge-best`

## idea_discovery.py

```bash
# Fetch papers only (pure Python, always safe)
python research_agent/idea_discovery.py --categories cs.CV,eess.IV --days 3 --fetch-only

# With Semantic Scholar search
python research_agent/idea_discovery.py --categories cs.CV --days 3 \
  --s2-query "medical image segmentation" --fetch-only

# Category aliases: medical-imaging, computer-vision, machine-learning, ai, nlp, robotics
```

## search_papers.py

```bash
python research_agent/search_papers.py "query" --limit 10 --year-min 2023
```

## Customization

```bash
# Different metric
python -m research_agent.state init --progress progress.md --metric val_loss

# Override file locations
export RESEARCH_STATE_FILE=my_state.json
export RESEARCH_PROGRESS_FILE=my_progress.md
```
