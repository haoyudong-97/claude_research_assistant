# Architecture

The research agent uses a clean separation between **pure Python** (API calls, state, git) and **Agent subagents** (reasoning, code implementation):

```
Claude Code Session
├── Orchestrator (you / skill instructions)
│   ├── Reads state, selects approaches, manages git
│   └── Presents results, asks for user feedback
│
├── Pure Python Scripts (always safe, no Claude needed)
│   ├── idea_discovery.py --fetch-only  → arXiv RSS + API + Semantic Scholar
│   ├── search_papers.py               → fallback paper search
│   ├── state.py                       → JSON state + progress.md updates
│   └── git_ops.py                     → branch/commit/merge per iteration
│
└── Agent Subagents (Claude Code's native mechanism)
    ├── Idea Generation  → digests papers, proposes research ideas
    └── Code Implementation → reads code, makes surgical edits
```

**Why Agent subagents?** Claude Code's Agent tool spawns isolated subagents with full tool access (Read/Edit/Write/Bash/Grep/Glob). This avoids the nesting issues of `claude -p` while keeping implementation work separate from orchestration.

**Fallback chain:** If paper fetching fails, the pipeline degrades gracefully — from full paper context down to using just the raw idea. Implementation always goes through the Agent tool.

## Components

| File | Purpose |
|------|---------|
| `idea_discovery.py` | Paper fetching (arXiv RSS + API, Semantic Scholar) + Claude worker for idea generation |
| `search_papers.py` | Fallback paper search via Semantic Scholar + arXiv APIs (no Claude needed) |
| `state.py` | Persistent JSON state + auto-updates `progress.md` |
| `git_ops.py` | Branch per iteration, structured commits, merge best to main |
| `deploy.py` | GPU-aware experiment deployment: preflight checks, local/remote launch, status, result collection |
| `run_and_wait.sh` | Low-level experiment runner with `.done` completion marker (called by `deploy.py`) |
| `protocol.md` | Research loop protocol (append to your project's CLAUDE.md) |
| `archive/` | Deprecated scripts (`code_implementation.py`, `literature_search.py`) — kept for reference only |

## Project Structure

```
your_project/
├── CLAUDE.md                    # Protocol instructions (appended from protocol.md)
├── .claude/skills/              # Slash command definitions
│   ├── auto-research/SKILL.md
│   ├── find-papers/SKILL.md
│   ├── implement/SKILL.md
│   └── combine-findings/SKILL.md
├── progress.md                  # Your goal + auto-updated tracking dashboard
├── state.json                   # Machine-readable state (created at runtime)
└── research_agent/
    ├── idea_discovery.py        # Paper fetching + idea generation
    ├── search_papers.py         # Fallback paper search
    ├── state.py                 # State management + progress.md auto-updates
    ├── git_ops.py               # Git branching, commits, merges per iteration
    ├── deploy.py                # GPU-aware deployment (local + remote)
    ├── run_and_wait.sh          # Low-level experiment runner (used by deploy.py)
    ├── protocol.md              # Source protocol
    └── archive/                 # Deprecated (kept for reference)
        ├── code_implementation.py
        └── literature_search.py
```

## State & Progress Tracking

### progress.md

The human-readable dashboard with two sections:

1. **Your goal** (top) — you write this. The agent never touches it.
2. **Agent tracking** (bottom) — auto-generated below `<!-- AGENT PROGRESS BELOW -->`. Updated after every action.

### state.json

Machine-readable state with goal, baseline, best result, and full iteration history. Persists across context compression and session restarts.

## Rules (for Claude)

1. **ONE change per iteration** — isolate variables
2. **NEVER overwrite checkpoints** — unique directory per iteration
3. **Create branch + commit BEFORE experiments** — code must be in git first
4. **Re-read state.json** every iteration — recover context after compression
5. **Review changes** — always `git diff` before committing
6. **Push after every commit** — keep remote in sync
7. **Never edit the user's goal** in `progress.md`
8. **Cite papers** when techniques come from literature
9. **NEVER call archived scripts** (`code_implementation.py`, `literature_search.py`) — use Agent tool instead
10. **Final output is always a results summary** — not just a diff
