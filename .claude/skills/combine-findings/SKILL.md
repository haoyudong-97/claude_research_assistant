---
name: combine-findings
description: Combine existing research findings with new input. TRIGGER when the user says "combine existing findings with", "integrate X into current work", "merge this paper/idea with what we have", "build on current results with", or asks to incorporate a paper link, a rough idea, or related literature into the current research state. Also triggers on "find related literature" in the context of extending current work.
argument-hint: <paper-url | rough idea | "find related literature">
disable-model-invocation: false
allowed-tools: Bash(python:*), Bash(cat:*), Bash(test:*), Read, Grep, WebFetch, WebSearch, Agent
---

# Combine Existing Findings

Integrate new input (a paper, an idea, or fresh literature) with the current research state and produce implemented code.

## Step 0: Read current state

```bash
cd "$(git rev-parse --show-toplevel)"
python -m research_agent.state read
```

## Step 1: Classify the input

### Type A — Paper link (URL)
1. Use **WebFetch** to retrieve the page. Extract title, authors, abstract, key ideas.
2. Save to `results/combine_paper.json`.
3. Propose hypothesis combining this paper with current best.

### Type B — Rough idea (free text)
1. Formulate hypothesis combining the idea with current state.

### Type C — "find related literature"
1. Fetch papers: `python research_agent/search_papers.py "<topic>" results/combine_search.json --limit 10`
2. Present results, user picks paper(s).

## Step 2: Implement via Agent tool

Use the **Agent tool** for code implementation. Do NOT call `code_implementation.py`.

## Step 3: Present results

1. Read `results/impl_summary.json`.
2. Show `git diff`.
3. Ask: Accept / Modify / Reject.

## Notes

- ALWAYS read state first.
- Code implementation goes through the **Agent tool**, not archived scripts.
