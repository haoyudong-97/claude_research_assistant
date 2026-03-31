---
name: combine-findings
description: Integrate a paper, idea, or literature into current research and implement code changes.
when_to_use: When the user says "combine existing findings with", "integrate X into current work", "merge this paper/idea with what we have", "build on current results with", or asks to incorporate a paper link, a rough idea, or related literature into the current research state. Also triggers on "find related literature" in the context of extending current work.
argument-hint: <paper-url | rough idea | "find related literature">
arguments: input
disable-model-invocation: false
version: "0.2.0"
effort: high
allowed-tools: Bash(python -m research_agent:*), Bash(test:*), Bash(git diff:*), Read, Grep, WebFetch(domain:arxiv.org), WebFetch(domain:semanticscholar.org), WebSearch, Agent
hooks:
  PostToolUse:
    - matcher: Bash|Edit
      hooks:
        - type: command
          command: "python ${CLAUDE_SKILL_DIR}/research_agent/hooks/track_state.py"
---

# Combine Existing Findings

Integrate new input (a paper, an idea, or fresh literature) with the current research state and produce implemented code.

## Tool Discovery

```bash
export PYTHONPATH="${CLAUDE_SKILL_DIR}:$PYTHONPATH"
```

## Step 0: Read current state

```bash
cd "$(git rev-parse --show-toplevel)"
python -m research_agent.state read
```

## Step 1: Classify the input

### Type A — Paper link (URL)
1. Use **WebFetch** to retrieve the page. Extract title, authors, abstract, key ideas.
   - **Fallback:** If WebFetch fails, extract the paper title from the URL (e.g., from the arXiv abstract page slug or PDF filename) and fall back to `python research_agent/search_papers.py "<extracted title>" results/combine_search.json --limit 5` to find the paper metadata via Semantic Scholar.
2. Save to `results/combine_paper.json`.
3. Propose hypothesis combining this paper with current best.

### Type B — Rough idea (free text)
1. Formulate hypothesis combining the idea with current state.

### Type C — "find related literature"
1. Fetch papers: `python research_agent/search_papers.py "<topic>" results/combine_search.json --limit 10`
2. Present results, user picks paper(s).

## Step 2: Implement via Agent tool

Use the **Agent tool** for code implementation. Do NOT call `code_implementation.py`.

Pass `$input` as context to the Agent along with the current state and the combined hypothesis.

## Step 3: Present results

1. Read `results/impl_summary.json`.
2. Show `git diff`.
3. Ask: Accept / Modify / Reject.

## Notes

- ALWAYS read state first.
- Code implementation goes through the **Agent tool**, not archived scripts.
- Use `/idea-iter` for full autonomous research iterations; use `/combine-findings` when integrating specific external input into current work.
