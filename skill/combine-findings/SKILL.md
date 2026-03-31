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
          command: "python $HOME/.claude/skills/combine-findings/research_agent/hooks/track_state.py"
---

# Combine Findings: Integrate External Input

You are integrating new input — a paper, a rough idea, or fresh literature — with the current research state and implementing code changes.

Your FIRST action must be to set up the Python tools:

```bash
export PYTHONPATH="$HOME/.claude/skills/combine-findings:$PYTHONPATH"
```

---

## Phase 1: Load State

```bash
cd "$(git rev-parse --show-toplevel)"
python -m research_agent.state read
```

Note: `GOAL`, `BASELINE`, `BEST`, `PRIMARY_METRIC`, `LAST_ITERS`.

---

## Phase 2: Classify & Process Input

Examine `$input` and determine the type:

### If URL (contains `http` or `arxiv.org`):

Use `WebFetch` to retrieve the page. Extract title, authors, abstract, and key techniques.

If WebFetch fails (timeout, 404, paywall), extract the paper title from the URL and fall back to:

```bash
python -m research_agent.search_papers "<extracted title>" results/combine_search.json --limit 5
```

Then search for related work:

```bash
python -m research_agent.search_papers "<paper title keywords>" results/combine_search.json --limit 5
```

Formulate a hypothesis combining this paper's technique with the current best approach.

### If rough idea (free text):

Search for supporting papers:

```bash
python -m research_agent.search_papers "<IDEA>" results/combine_search.json --limit 5
```

Formulate a hypothesis combining the idea with the current research state.

### If "find related literature":

Derive search terms from the current goal and best iteration, then fetch papers:

```bash
python -m research_agent.search_papers "<derived terms>" results/combine_search.json --limit 5
```

Present results to the user. Ask which paper(s) to integrate. Once selected, process as a URL.

---

## Phase 3: Confirm with User

Present the combination plan:

> **Current best:** <BEST_DESCRIPTION> (<PRIMARY_METRIC>: <VALUE>)
> **New input:** <PAPER_TITLE or IDEA>
> **Proposed combination:** <HYPOTHESIS>
> **What will change:** <CHANGE_DESC>
>
> **Proceed?** Yes / Modify / Skip

**Wait for user response.**

---

## Phase 4: Implement

Get the next iteration number and create a branch:

```bash
python -m research_agent.state read --field next_id
```

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

Spawn an Agent (subagent_type: general-purpose) to implement:

```
You are implementing a code change that combines existing work with new research input.

## Instruction
<DETAILED_INSTRUCTION — how to integrate the new technique/idea>

## Current State
- Goal: <GOAL>
- Primary metric: <PRIMARY_METRIC>
- Current best (iter <N>): <BEST_METRICS>
- What the current best does: <BEST_CHANGE_SUMMARY>

## New Input
<PAPER_SUMMARY or IDEA_DESCRIPTION>
<KEY_TECHNIQUES to integrate>

## Rules
1. Read relevant code files first.
2. Implement one focused combination of existing + new approach.
3. Use the Edit tool for modifications. Make minimal, surgical edits.
4. Write summary to results/impl_summary.json:
   {"hypothesis": "...", "change_summary": "...", "files_modified": [...], "papers_used": [...]}
```

**Wait for the Agent to complete.**

---

## Phase 5: Review

Read `results/impl_summary.json` and show the diff:

```bash
git diff
```

Tell the user what changed and how the new input was integrated. Then ask:

> **Accept** / **Modify** / **Reject**

- **Accept** → commit and optionally launch experiment via `/idea-iter` style launch
- **Modify** → user gives feedback, re-run Agent once with updated instruction, then ask Accept/Reject
- **Reject** → discard changes:
  ```bash
  git checkout .
  git checkout main
  python -m research_agent.state fail-iteration --id <NEXT_ITER> --feedback "rejected by user"
  ```

If accepted, commit:

```bash
python -m research_agent.git_ops commit-code \
  --iteration <NEXT_ITER> \
  --hypothesis "<HYPOTHESIS>" \
  --change "<CHANGE_DESC>" \
  --papers "<PAPER_TITLES>"
```

```bash
python -m research_agent.git_ops push
```

---

## Rules

- Always read state first to understand what exists before combining.
- Delegate code implementation to the Agent tool. Use Edit, not Write.
- Present the combination plan before implementing.
- One combination per invocation.
