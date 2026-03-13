---
name: find-papers
description: Search for and fetch research papers. TRIGGER when the user asks to find papers, search literature, look for recent publications, discover research ideas, or mentions a specific research topic they want papers on. Examples: "find papers on X", "search for literature about Y", "what's new in Z on arXiv".
argument-hint: [topic or keywords] [--days N] [--categories arXiv-cats]
disable-model-invocation: false
allowed-tools: Bash(python:*), Bash(cat:*), Read, Grep, Agent, WebSearch, WebFetch
---

# Find Papers

Search for research papers and generate research ideas.

## Parsing arguments

Extract from `$ARGUMENTS`:
- **topic**: the main search topic (required)
- **--days N**: how many days back to search (default: 3)
- **--categories CATS**: arXiv categories, comma-separated (default: cs.CV,eess.IV). Aliases accepted: `medical-imaging`, `computer-vision`, `machine-learning`, `ai`, `nlp`, `robotics`
- **--fetch-only**: only fetch papers, skip idea generation

Infer arXiv categories from the topic if not specified:
- "medical image segmentation" → `medical-imaging`
- "transformer architectures" → `cs.CV,cs.LG`
- "NLP" or "language models" → `nlp`
- If unsure → `cs.CV,cs.LG`

## Step 1: Fetch papers (pure Python — no Claude worker needed)

```bash
cd "$(git rev-parse --show-toplevel)" && \
python research_agent/idea_discovery.py \
  --categories <CATEGORIES> \
  --days <DAYS> \
  --s2-query "<TOPIC>" \
  [--state state.json] \
  [--progress progress.md] \
  --fetch-only \
  --papers-output results/recent_papers.json
```

**Fallback** if idea_discovery.py fails:
```bash
cd "$(git rev-parse --show-toplevel)" && \
python research_agent/search_papers.py "<TOPIC>" results/search_fallback.json --limit 15
```

## Step 2: Read fetched papers

Read `results/recent_papers.json` (or `results/search_fallback.json`).
Present the papers to the user: title, authors, abstract snippet, URL.

## Step 3: Generate research ideas (via Agent tool)

If `--fetch-only` was specified, skip this step.

Otherwise, use the **Agent tool** to spawn a subagent that digests the papers and proposes ideas:

```
Read the file results/recent_papers.json in the project root.
Also read state.json if it exists (for project context).

The user's research topic is: <TOPIC>

From these papers:
1. Identify the 3-5 most interesting trends and techniques.
2. Propose 3-5 concrete, actionable research ideas.

For each idea: title, hypothesis, approach, expected_impact, difficulty, relevant_papers.

Write output to results/ideas.json. Do NOT modify any project code.
```

After the Agent returns, read `results/ideas.json` and present:
- **Trend digest**: bullet-point summary
- **Research ideas**: each with title, hypothesis, approach, expected impact, difficulty

## Step 4: Offer next steps

- Would you like to **implement** one of these ideas?
- Would you like to save any papers to state for future reference?

## Notes

- Paper fetching (Step 1) is pure Python — fast, always works, no Claude needed.
- Idea generation (Step 3) uses the Agent tool — runs as a subagent, not nested `claude -p`.
- Do NOT hallucinate papers. Only present papers from the output JSON files.
