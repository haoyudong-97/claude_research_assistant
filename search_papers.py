#!/usr/bin/env python3
"""Search for papers using a Claude agent via the Claude Agent SDK.

Uses @anthropic-ai/claude-agent-sdk to spawn a Claude agent with web search.
Requires ANTHROPIC_API_KEY environment variable.

The agent gets full access to WebSearch, WebFetch, and file reading.

Usage:
    python search_papers.py "topic" output.json
    python search_papers.py "topic" output.json --progress progress.md --state state.json

Output:
    Writes JSON array to output.json with fields:
        title, authors, year, abstract, url, arxiv_id,
        relevance (1-5), relevance_reason, key_idea
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_SCRIPT = Path(__file__).parent / "search_agent.mjs"

SYSTEM_INSTRUCTIONS = """\
You are a research paper search agent for an ML project. Your ONLY job is to \
find academic papers relevant to a specific topic within the project's context.

## Instructions

1. **Understand the project**: Read the project context provided. Understand what \
the project does, what has been tried, and what the current research direction is.

2. **Plan search queries**: Based on the topic and project context, plan 3-5 \
specific search queries. Each query should target a different angle:
   - The core technique/method mentioned in the topic
   - The technique applied to the project's domain (e.g., medical image segmentation)
   - Related or alternative approaches to the same problem
   - Key author names or paper titles if you recognize them

3. **Execute searches**: Use WebSearch for each query. For particularly relevant \
results, use WebFetch to read the abstract or paper page for more detail.

4. **Evaluate relevance**: For each paper found, score its relevance (1-5):
   - 5: Directly applicable — describes the exact technique or a close variant
   - 4: Highly relevant — same problem domain and approach category
   - 3: Relevant — useful background or related technique
   - 2: Tangentially related
   - 1: Not relevant
   Only keep papers scoring 3 or above.

5. **Return results**: Your final response must contain ONLY a JSON array (no \
markdown fences, no commentary before or after). Each element:
   {
     "title": "Paper Title",
     "authors": "First Author et al.",
     "year": 2024,
     "abstract": "First 2-3 sentences of abstract...",
     "url": "https://...",
     "arxiv_id": "2401.12345 or empty string",
     "relevance": 5,
     "relevance_reason": "Why this paper matters for the project",
     "key_idea": "One sentence: the main takeaway applicable to our work"
   }

   Sort by relevance descending, then year descending.

## Rules
- Be specific: every search query must relate to the topic, not generic terms.
- Quality over quantity: 3-8 highly relevant papers beat 15 vague ones.
- No hallucinated papers: only include papers you actually found via search.
- Valid JSON only: your final message must be a parseable JSON array, nothing else.\
"""


def _build_prompt(topic: str, progress_path: str | None,
                  state_path: str | None) -> str:
    """Build the full prompt with topic, instructions, and project context."""
    parts = [SYSTEM_INSTRUCTIONS, "", f"## Search Topic\n{topic}"]

    if progress_path and Path(progress_path).exists():
        content = Path(progress_path).read_text().strip()
        parts.append(f"\n## Project Goal (from progress.md)\n{content}")

    if state_path and Path(state_path).exists():
        try:
            state = json.loads(Path(state_path).read_text())
            summary_parts = []
            if state.get("goal"):
                goal_text = state["goal"]
                if len(goal_text) > 200:
                    goal_text = goal_text[:200] + "..."
                summary_parts.append(f"Goal: {goal_text}")
            if state.get("primary_metric"):
                summary_parts.append(f"Primary metric: {state['primary_metric']}")
            bl = state.get("baseline")
            if bl and bl.get("metrics"):
                summary_parts.append(f"Baseline: {json.dumps(bl['metrics'])}")
            best = state.get("best")
            if best and best.get("metrics"):
                summary_parts.append(
                    f"Best so far (iter {best.get('iteration', '?')}): "
                    f"{json.dumps(best['metrics'])}"
                )
            for it in state.get("iterations", [])[-3:]:
                summary_parts.append(
                    f"Iter {it['id']}: {it.get('change_summary', '')} "
                    f"-> {json.dumps(it.get('metrics', {}))}"
                )
            if summary_parts:
                parts.append(
                    "\n## Iteration History (from state.json)\n" +
                    "\n".join(f"- {s}" for s in summary_parts)
                )
        except (json.JSONDecodeError, IOError):
            pass

    parts.append(
        "\n## Task\n"
        "Search for papers relevant to the topic above, within the context of "
        "this project. Return ONLY a JSON array of results."
    )
    return "\n".join(parts)


def _extract_json_array(text: str) -> list | None:
    """Try to extract a JSON array from text, handling markdown fences."""
    import re
    text = text.strip()

    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fence or bare array
    for pattern in [r"```json\s*\n(.*?)\n```", r"```\s*\n(.*?)\n```", r"(\[.*\])"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                continue

    return None


def run_search(topic: str, output_path: str, progress_path: str | None,
               state_path: str | None) -> list | None:
    """Run the search agent via Claude Code SDK and parse results."""
    prompt = _build_prompt(topic, progress_path, state_path)

    # Write prompt to temp file for the Node.js agent
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(prompt)
        prompt_file = f.name

    # Raw output goes to a temp file, we parse and write the final JSON
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        raw_output_file = f.name

    print(f"Searching: {topic}", file=sys.stderr)
    print(f"Using Claude Agent SDK (search_agent.mjs)", file=sys.stderr)

    try:
        result = subprocess.run(
            ["node", str(AGENT_SCRIPT), prompt_file, raw_output_file],
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max
        )

        # Print agent stderr (progress messages)
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")

        if result.returncode != 0:
            print(f"Agent exited with code {result.returncode}", file=sys.stderr)
            return None

    except subprocess.TimeoutExpired:
        print("Agent timed out after 10 minutes", file=sys.stderr)
        return None
    except FileNotFoundError:
        print(
            "Error: 'node' not found. Install Node.js and run:\n"
            "  cd research_agent && npm install",
            file=sys.stderr,
        )
        return None
    finally:
        # Clean up prompt file
        Path(prompt_file).unlink(missing_ok=True)

    # Read raw output
    raw_text = Path(raw_output_file).read_text()
    Path(raw_output_file).unlink(missing_ok=True)

    # Parse JSON
    papers = _extract_json_array(raw_text)
    if papers is None:
        print("Warning: Could not parse JSON from agent response.", file=sys.stderr)
        print(f"Raw response:\n{raw_text[:500]}...", file=sys.stderr)
        Path(output_path).write_text(raw_text)
        return None

    # Write structured output
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(papers, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return papers


def main():
    parser = argparse.ArgumentParser(
        description="Search for papers using Claude Code SDK with web search. "
                    "No API key needed — uses your Claude Code auth.",
        epilog="""Examples:
  python search_papers.py "Householder orthogonal adapters for ViT" results.json
  python search_papers.py "nullspace bias adapter layers" results.json --progress progress.md
  python search_papers.py "Gram matrix preservation PEFT" results.json --state state.json
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("topic",
                        help="What to search for — must be specific to the project")
    parser.add_argument("output",
                        help="Output JSON file path")
    parser.add_argument("--progress", default=None,
                        help="Path to progress.md for project context")
    parser.add_argument("--state", default=None,
                        help="Path to state.json for iteration history")
    args = parser.parse_args()

    papers = run_search(args.topic, args.output, args.progress, args.state)

    if papers is not None:
        print(f"Found {len(papers)} papers -> {args.output}", file=sys.stderr)
        json.dump(papers, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
