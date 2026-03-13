#!/usr/bin/env python3
"""Idea discovery: pull recent arXiv papers, digest trends, propose research ideas.

Fetches the latest papers from arXiv RSS feeds (and optionally Semantic Scholar)
for your configured categories, then sends them to a Claude Code worker that
digests the papers and proposes concrete research ideas aligned with your goal.

Usage:
    # Fetch last 3 days of papers in cs.CV and eess.IV, propose ideas
    python research_agent/idea_discovery.py --categories cs.CV,eess.IV --days 3

    # With project context (reads goal from state.json)
    python research_agent/idea_discovery.py --categories cs.CV --days 7 --state state.json

    # Also read goal from progress.md
    python research_agent/idea_discovery.py --categories cs.CV --days 3 \
        --state state.json --progress progress.md

    # Skip Claude worker, just fetch and dump papers
    python research_agent/idea_discovery.py --categories cs.CV --days 3 --fetch-only

Output:
    - results/ideas.json with proposed research ideas (unless --fetch-only)
    - results/recent_papers.json with fetched papers (always)
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

POLL_INTERVAL = 5
DEFAULT_TIMEOUT = 600  # 10 minutes — digesting many papers takes time
WORKSPACE = Path(__file__).resolve().parent / "workspace"

ARXIV_RSS_BASE = "https://rss.arxiv.org/rss"
S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,abstract,year,citationCount,url,authors,externalIds,publicationDate"

# Common arXiv categories for medical imaging / CV / ML research
CATEGORY_ALIASES = {
    "medical-imaging": "eess.IV+cs.CV",
    "computer-vision": "cs.CV",
    "machine-learning": "cs.LG+stat.ML",
    "ai": "cs.AI",
    "nlp": "cs.CL",
    "robotics": "cs.RO",
}


# ── Paper fetching ────────────────────────────────────────────────────

def fetch_arxiv_rss(categories: str, days: int = 3) -> list[dict]:
    """Fetch recent papers from arXiv RSS feed for given categories.

    Args:
        categories: Comma or plus-separated arXiv categories (e.g. "cs.CV,eess.IV")
        days: How many days back to include (arXiv RSS only has ~1 day,
              so we also fall back to the arXiv API for longer windows)
    """
    cats = categories.replace(",", "+")
    papers = []

    # Try RSS first (gives today's/yesterday's papers)
    rss_url = f"{ARXIV_RSS_BASE}/{cats}"
    print(f"  Fetching arXiv RSS: {rss_url}", file=sys.stderr)

    req = urllib.request.Request(rss_url, headers={"User-Agent": "research-agent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read().decode("utf-8")
        papers.extend(_parse_rss(xml_data))
        print(f"  RSS: {len(papers)} papers", file=sys.stderr)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  RSS fetch failed: {e}", file=sys.stderr)

    # If user wants more than 1 day, supplement with arXiv API search
    if days > 1:
        time.sleep(3)  # arXiv requests ≥3s between API calls
        api_papers = _fetch_arxiv_api(categories, days)
        papers.extend(api_papers)

    # Deduplicate by arxiv_id or title
    papers = _dedup_papers(papers)
    print(f"  Total unique papers: {len(papers)}", file=sys.stderr)
    return papers


def _parse_rss(xml_data: str) -> list[dict]:
    """Parse arXiv RSS XML into paper dicts."""
    papers = []
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        return []

    # RSS 2.0 format: channel/item
    for item in root.findall(".//item"):
        title_el = item.find("title")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        if not title:
            continue
        # Clean up title (remove "arXiv:" prefix and newlines)
        title = re.sub(r"^arXiv:\d+\.\d+\s*", "", title).strip()
        title = title.replace("\n", " ")

        desc_el = item.find("description")
        abstract = ""
        if desc_el is not None and desc_el.text:
            abstract = desc_el.text.strip()
            # Remove HTML tags
            abstract = re.sub(r"<[^>]+>", "", abstract)
            abstract = abstract.replace("\n", " ")[:500]

        link_el = item.find("link")
        url = link_el.text.strip() if link_el is not None and link_el.text else ""

        # Extract arxiv ID from URL
        arxiv_id = ""
        if url:
            m = re.search(r"(\d{4}\.\d{4,5})", url)
            if m:
                arxiv_id = m.group(1)

        # Extract authors from dc:creator if available
        creator_el = item.find("{http://purl.org/dc/elements/1.1/}creator")
        authors = ""
        if creator_el is not None and creator_el.text:
            authors = creator_el.text.strip()

        papers.append({
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "url": url,
            "arxiv_id": arxiv_id,
            "source": "arxiv_rss",
        })

    return papers


def _fetch_arxiv_api(categories: str, days: int) -> list[dict]:
    """Fetch recent papers via arXiv API search for a date range."""
    cats = [c.strip() for c in categories.replace("+", ",").split(",")]
    cat_query = "+OR+".join(f"cat:{c}" for c in cats)

    # Date range
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    # arXiv API doesn't support date filtering directly in search,
    # so we fetch recent and filter client-side
    params = {
        "search_query": cat_query,
        "start": 0,
        "max_results": min(days * 50, 200),  # ~50 papers/day per category
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"https://export.arxiv.org/api/query?{urllib.parse.urlencode(params)}"
    print(f"  Fetching arXiv API (last {days} days)...", file=sys.stderr)

    req = urllib.request.Request(url, headers={"User-Agent": "research-agent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  arXiv API failed: {e}", file=sys.stderr)
        return []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    papers = []
    cutoff = start.isoformat()

    for entry in root.findall("atom:entry", ns):
        # Filter by date
        pub_el = entry.find("atom:published", ns)
        if pub_el is not None and pub_el.text:
            if pub_el.text < cutoff:
                continue

        title_el = entry.find("atom:title", ns)
        title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else ""
        if not title:
            continue

        abstract_el = entry.find("atom:summary", ns)
        abstract = abstract_el.text.strip().replace("\n", " ")[:500] if abstract_el is not None and abstract_el.text else ""

        authors_els = entry.findall("atom:author/atom:name", ns)
        author_names = [a.text for a in authors_els if a.text]
        authors = author_names[0] if author_names else ""
        if len(author_names) > 1:
            authors += " et al."

        id_el = entry.find("atom:id", ns)
        entry_url = id_el.text if id_el is not None and id_el.text else ""
        arxiv_id = ""
        if entry_url:
            m = re.search(r"(\d{4}\.\d{4,5})", entry_url)
            if m:
                arxiv_id = m.group(1)

        papers.append({
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "url": entry_url,
            "arxiv_id": arxiv_id,
            "source": "arxiv_api",
        })

    print(f"  arXiv API: {len(papers)} papers in date range", file=sys.stderr)
    return papers


def fetch_semantic_scholar_trending(query: str, limit: int = 20,
                                     year_min: int | None = None) -> list[dict]:
    """Fetch recent high-impact papers from Semantic Scholar."""
    params = {
        "query": query,
        "limit": limit,
        "fields": S2_FIELDS,
        "sort": "citationCount:desc",
    }
    if year_min:
        params["year"] = f"{year_min}-"

    url = f"{S2_SEARCH}?{urllib.parse.urlencode(params)}"
    print(f"  S2 trending: {query}", file=sys.stderr)

    req = urllib.request.Request(url, headers={"User-Agent": "research-agent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  S2 request failed: {e}", file=sys.stderr)
        return []

    if not data or "data" not in data:
        return []

    papers = []
    for raw in data["data"]:
        if not raw.get("title"):
            continue
        authors = raw.get("authors") or []
        author_str = authors[0].get("name", "") if authors else ""
        if len(authors) > 1:
            author_str += " et al."

        arxiv_id = ""
        ext = raw.get("externalIds") or {}
        if ext.get("ArXiv"):
            arxiv_id = re.sub(r"v\d+$", "", ext["ArXiv"])

        papers.append({
            "title": raw.get("title", ""),
            "authors": author_str,
            "abstract": (raw.get("abstract") or "")[:500],
            "url": raw.get("url", ""),
            "arxiv_id": arxiv_id,
            "citations": raw.get("citationCount", 0),
            "source": "semantic_scholar",
        })

    print(f"  S2: {len(papers)} papers", file=sys.stderr)
    return papers


def _dedup_papers(papers: list[dict]) -> list[dict]:
    """Deduplicate papers by arxiv_id or normalized title."""
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    unique = []
    for p in papers:
        # Prefer arxiv_id for dedup
        if p.get("arxiv_id"):
            if p["arxiv_id"] in seen_ids:
                continue
            seen_ids.add(p["arxiv_id"])
        else:
            norm = re.sub(r"\W+", " ", p["title"].lower()).strip()
            if norm in seen_titles:
                continue
            seen_titles.add(norm)
        unique.append(p)
    return unique


# ── Context loading ──────────────────────────────────────────────────

def _load_goal(state_path: str | None, progress_path: str | None) -> str:
    """Load research goal from state.json or progress.md."""
    if state_path and Path(state_path).exists():
        try:
            state = json.loads(Path(state_path).read_text(encoding="utf-8"))
            if state.get("goal"):
                return state["goal"]
        except (json.JSONDecodeError, IOError):
            pass

    if progress_path and Path(progress_path).exists():
        text = Path(progress_path).read_text(encoding="utf-8")
        sentinel = "<!-- AGENT PROGRESS BELOW"
        if sentinel in text:
            return text.split(sentinel)[0].strip()
        return text.strip()

    return ""


def _load_iteration_context(state_path: str | None) -> str:
    """Load recent iteration history for context."""
    if not state_path or not Path(state_path).exists():
        return ""
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return ""

    parts = []
    if state.get("primary_metric"):
        parts.append(f"Primary metric: {state['primary_metric']}")
    bl = state.get("baseline")
    if bl and bl.get("metrics"):
        parts.append(f"Baseline: {json.dumps(bl['metrics'])}")
    best = state.get("best")
    if best and best.get("metrics"):
        parts.append(f"Best so far (iter {best.get('iteration', '?')}): "
                      f"{json.dumps(best['metrics'])}")
    for it in state.get("iterations", [])[-5:]:
        parts.append(f"Iter {it['id']}: {it.get('change_summary', '')} "
                      f"-> {json.dumps(it.get('metrics', {}))} "
                      f"| {it.get('feedback', '')}")
    return "\n".join(parts)


# ── Claude worker for idea generation ─────────────────────────────────

def _build_idea_prompt(papers: list[dict], goal: str,
                       iteration_context: str) -> str:
    """Build a prompt for the Claude worker to digest papers and propose ideas."""
    parts = []

    parts.append(
        "You are a research advisor. You have been given a batch of recently "
        "published papers. Your job is to:\n"
        "1. Identify the most interesting trends and techniques in these papers.\n"
        "2. Propose 3-5 concrete, actionable research ideas that could advance "
        "the user's goal.\n"
    )

    if goal:
        parts.append(f"## User's Research Goal\n\n{goal}\n")

    if iteration_context:
        parts.append(f"## Previous Experiment Context\n\n{iteration_context}\n")

    parts.append("## Recent Papers\n")

    # Include papers — limit to top ~50 to stay within context
    for i, p in enumerate(papers[:50], 1):
        parts.append(f"### [{i}] {p['title']}")
        if p.get("authors"):
            parts.append(f"Authors: {p['authors']}")
        if p.get("abstract"):
            parts.append(f"Abstract: {p['abstract']}")
        if p.get("url"):
            parts.append(f"URL: {p['url']}")
        parts.append("")

    parts.append("""\
## Instructions

Based on the papers above and the user's research goal, produce:

1. **Trend Digest** — A brief summary (3-5 bullet points) of the most notable
   trends, methods, or findings in this batch of papers.

2. **Research Ideas** — 3-5 concrete research ideas. For each idea:
   - A clear, specific title
   - Which papers inspired it (by number)
   - What the hypothesis is
   - What changes would be needed in code
   - Expected impact (why this could help the user's goal)
   - Estimated difficulty (low / medium / high)
   - A pilot experiment design: the cheapest possible test to check if the idea
     has signal before committing to a full run. Include what to run (e.g. fewer
     epochs, smaller data subset), estimated GPU-hours, and a clear success
     criterion (what result would confirm promise vs. discard).

Return ONLY valid JSON with this structure. No markdown fences, no commentary.

{
  "trend_digest": [
    "Trend 1: ...",
    "Trend 2: ..."
  ],
  "ideas": [
    {
      "id": 1,
      "title": "Short descriptive title",
      "inspired_by": [1, 5, 12],
      "hypothesis": "What you expect this to achieve",
      "approach": "Concrete description of what to implement",
      "expected_impact": "Why this could improve the metric",
      "difficulty": "low|medium|high",
      "relevant_papers": ["Paper Title 1", "Paper Title 2"],
      "pilot_design": {
        "experiment": "Minimal test to check signal (e.g. train 5 epochs on 10% data)",
        "gpu_hours": 0.5,
        "success_criterion": "What result would confirm the idea has promise"
      }
    }
  ]
}

Return ONLY the JSON, nothing else.""")

    return "\n".join(parts)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes."""
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def _extract_json_object(text: str) -> dict | None:
    """Extract a JSON object from worker output."""
    text = _strip_ansi(text).strip()

    # Direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try markdown fences
    for pattern in [r"```json\s*\n(.*?)\n```",
                    r"```\s*\n(.*?)\n```",
                    r"(\{[\s\S]*\"ideas\"[\s\S]*\})"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                continue
    return None


def _project_tag(state_path: str | None) -> str:
    """Derive a short project tag."""
    if state_path and Path(state_path).exists():
        try:
            state = json.loads(Path(state_path).read_text(encoding="utf-8"))
            pdir = state.get("project_dir", "")
            if pdir:
                return Path(pdir).name.lower().replace(" ", "-")[:20]
        except (json.JSONDecodeError, IOError):
            pass
    return "default"


def generate_ideas(papers: list[dict], goal: str,
                   iteration_context: str,
                   output_path: str,
                   state_path: str | None = None,
                   timeout: int = DEFAULT_TIMEOUT) -> dict | None:
    """Send papers to a Claude worker to digest and propose research ideas."""
    tag = _project_tag(state_path)
    prompt = _build_idea_prompt(papers, goal, iteration_context)

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    prompt_file = WORKSPACE / f"{tag}_ideas.prompt"
    done_marker = WORKSPACE / f"{tag}_ideas.done"
    err_file = WORKSPACE / f"{tag}_ideas.err"
    worker_out = WORKSPACE / f"{tag}_ideas.output"

    for f in [worker_out, done_marker, err_file]:
        f.unlink(missing_ok=True)

    prompt_file.write_text(prompt, encoding="utf-8")

    cmd = (
        f"claude -p --verbose --dangerously-skip-permissions "
        f"< {shlex.quote(str(prompt_file))} "
        f"> {shlex.quote(str(worker_out))} "
        f"2> {shlex.quote(str(err_file))}; "
        f"echo $? > {shlex.quote(str(done_marker))}"
    )

    print("Launching idea generation worker...", file=sys.stderr)

    clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    subprocess.Popen(
        ["bash", "-c", cmd],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=clean_env,
    )
    print("Worker launched as background process", file=sys.stderr)

    # Poll for completion
    start_time = time.time()
    while not done_marker.exists():
        elapsed = time.time() - start_time
        if elapsed > timeout:
            print(f"Timeout after {timeout}s waiting for idea worker",
                  file=sys.stderr)
            return None
        time.sleep(POLL_INTERVAL)
        if int(elapsed) % 30 < POLL_INTERVAL and elapsed > POLL_INTERVAL:
            print(f"  Digesting papers... ({int(elapsed)}s)", file=sys.stderr)

    exit_code = done_marker.read_text(encoding="utf-8").strip()
    if exit_code != "0":
        err_text = err_file.read_text(encoding="utf-8") if err_file.exists() else "unknown"
        print(f"Worker exited with code {exit_code}: {err_text[:500]}",
              file=sys.stderr)

    if not worker_out.exists() or worker_out.stat().st_size == 0:
        print("No output produced by idea worker", file=sys.stderr)
        return None

    raw = worker_out.read_text(encoding="utf-8")
    ideas = _extract_json_object(raw)

    if ideas is not None:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(ideas, f, indent=2, ensure_ascii=False)
            f.write("\n")
        n_ideas = len(ideas.get("ideas", []))
        print(f"Generated {n_ideas} research ideas -> {output_path}",
              file=sys.stderr)
        return ideas
    else:
        print("Could not parse ideas JSON from worker output", file=sys.stderr)
        print(f"Raw (first 500 chars): {raw[:500]}", file=sys.stderr)
        return None


# ── Main pipeline ─────────────────────────────────────────────────────

def run_discovery(categories: str, days: int = 3,
                  state_path: str | None = None,
                  progress_path: str | None = None,
                  papers_output: str = "results/recent_papers.json",
                  ideas_output: str = "results/ideas.json",
                  fetch_only: bool = False,
                  s2_query: str | None = None,
                  timeout: int = DEFAULT_TIMEOUT) -> dict | None:
    """Full idea discovery pipeline: fetch papers → generate ideas."""

    print(f"=== Idea Discovery: {categories} (last {days} days) ===",
          file=sys.stderr)

    # Resolve category aliases
    resolved = []
    for cat in categories.split(","):
        cat = cat.strip()
        resolved.append(CATEGORY_ALIASES.get(cat, cat))
    cats = ",".join(resolved)

    # Phase 1: Fetch papers
    papers = fetch_arxiv_rss(cats, days=days)

    # Optionally supplement with Semantic Scholar
    if s2_query:
        current_year = datetime.now().year
        s2_papers = fetch_semantic_scholar_trending(
            s2_query, limit=20, year_min=current_year - 1)
        papers.extend(s2_papers)
        papers = _dedup_papers(papers)

    if not papers:
        print("No papers found. Check your categories and network.",
              file=sys.stderr)
        return None

    # Save fetched papers
    papers_out = Path(papers_output).resolve()
    papers_out.parent.mkdir(parents=True, exist_ok=True)
    with open(papers_out, "w", encoding="utf-8") as f:
        json.dump(papers, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Saved {len(papers)} papers -> {papers_output}", file=sys.stderr)

    if fetch_only:
        return {"papers_count": len(papers), "papers_file": papers_output}

    # Phase 2: Generate ideas via Claude worker
    goal = _load_goal(state_path, progress_path)
    iteration_context = _load_iteration_context(state_path)

    if not goal:
        print("Warning: No research goal found. Ideas will be generic.",
              file=sys.stderr)

    ideas = generate_ideas(
        papers, goal, iteration_context,
        output_path=ideas_output,
        state_path=state_path,
        timeout=timeout,
    )

    return ideas


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Idea discovery: fetch recent papers and propose research ideas.",
        epilog="""\
Examples:
  # Fetch recent CV + medical imaging papers, generate ideas
  python idea_discovery.py --categories cs.CV,eess.IV --days 3

  # With project context
  python idea_discovery.py --categories cs.CV --days 7 --state state.json

  # Use category aliases
  python idea_discovery.py --categories medical-imaging --days 3

  # Also search Semantic Scholar for a specific topic
  python idea_discovery.py --categories cs.CV --days 3 --s2-query "medical image segmentation"

  # Just fetch papers, no idea generation
  python idea_discovery.py --categories cs.CV --days 3 --fetch-only

Available category aliases:
  medical-imaging  -> eess.IV+cs.CV
  computer-vision  -> cs.CV
  machine-learning -> cs.LG+stat.ML
  ai               -> cs.AI
  nlp              -> cs.CL
  robotics         -> cs.RO
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--categories", required=True,
                        help="arXiv categories (comma-separated, e.g. cs.CV,eess.IV) "
                             "or aliases (e.g. medical-imaging)")
    parser.add_argument("--days", type=int, default=3,
                        help="How many days back to fetch (default: 3)")
    parser.add_argument("--state", default=None,
                        help="Path to state.json for project context")
    parser.add_argument("--progress", default=None,
                        help="Path to progress.md for research goal")
    parser.add_argument("--papers-output", default="results/recent_papers.json",
                        help="Output path for fetched papers")
    parser.add_argument("--ideas-output", default="results/ideas.json",
                        help="Output path for generated ideas")
    parser.add_argument("--fetch-only", action="store_true",
                        help="Only fetch papers, skip idea generation")
    parser.add_argument("--s2-query", default=None,
                        help="Additional Semantic Scholar search query")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Timeout in seconds (default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args()

    result = run_discovery(
        categories=args.categories,
        days=args.days,
        state_path=args.state,
        progress_path=args.progress,
        papers_output=args.papers_output,
        ideas_output=args.ideas_output,
        fetch_only=args.fetch_only,
        s2_query=args.s2_query,
        timeout=args.timeout,
    )

    if result:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
