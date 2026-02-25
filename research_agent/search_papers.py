#!/usr/bin/env python3
"""Search for academic papers via Semantic Scholar + arXiv APIs.

Pure Python, no external dependencies. Both APIs are free and need no auth.
Returns structured JSON that the Claude session can evaluate for relevance.

Usage:
    python research_agent/search_papers.py "query terms" output.json
    python research_agent/search_papers.py "query" output.json --limit 10 --year-min 2022
    python research_agent/search_papers.py "query" output.json --state state.json

Output:
    Writes JSON array to output.json with fields:
        title, authors, year, abstract, url, arxiv_id, citations, source
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


# ── Semantic Scholar ─────────────────────────────────────────────────

S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,abstract,year,citationCount,url,authors,externalIds"
S2_RECOMMEND = "https://api.semanticscholar.org/recommendations/v1/papers"


def _s2_request(url: str, timeout: int = 15) -> dict | None:
    """Make a GET request to Semantic Scholar, return parsed JSON or None."""
    req = urllib.request.Request(url, headers={"User-Agent": "research-agent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        print(f"  S2 request failed: {e}", file=sys.stderr)
        return None


def _s2_paper(raw: dict) -> dict:
    """Normalize a Semantic Scholar paper record."""
    authors = raw.get("authors") or []
    author_str = authors[0].get("name", "") if authors else ""
    if len(authors) > 1:
        author_str += " et al."

    arxiv_id = ""
    ext = raw.get("externalIds") or {}
    if ext.get("ArXiv"):
        arxiv_id = re.sub(r"v\d+$", "", ext["ArXiv"])

    return {
        "title": raw.get("title", ""),
        "authors": author_str,
        "year": raw.get("year"),
        "abstract": (raw.get("abstract") or "")[:500],
        "url": raw.get("url", ""),
        "arxiv_id": arxiv_id,
        "citations": raw.get("citationCount", 0),
        "source": "semantic_scholar",
    }


def search_semantic_scholar(query: str, limit: int = 10,
                            year_min: int | None = None) -> list[dict]:
    """Search Semantic Scholar by keyword."""
    params = {"query": query, "limit": limit, "fields": S2_FIELDS}
    if year_min:
        params["year"] = f"{year_min}-"
    url = f"{S2_SEARCH}?{urllib.parse.urlencode(params)}"

    print(f"  S2 search: {query}", file=sys.stderr)
    data = _s2_request(url)
    if not data or "data" not in data:
        return []

    return [_s2_paper(p) for p in data["data"] if p.get("title")]


def recommend_semantic_scholar(arxiv_id: str, limit: int = 5) -> list[dict]:
    """Get recommended papers based on an arXiv ID (Semantic Scholar API)."""
    # First resolve the paper ID
    resolve_url = f"https://api.semanticscholar.org/graph/v1/paper/ArXiv:{arxiv_id}"
    resolve_url += f"?fields=paperId"
    data = _s2_request(resolve_url)
    if not data or "paperId" not in data:
        print(f"  Could not resolve arXiv:{arxiv_id}", file=sys.stderr)
        return []

    paper_id = data["paperId"]
    rec_url = f"{S2_RECOMMEND}?from=single-paper&paperId={paper_id}"
    rec_url += f"&fields={S2_FIELDS}&limit={limit}"
    print(f"  S2 recommendations for {arxiv_id}", file=sys.stderr)
    rec_data = _s2_request(rec_url)
    if not rec_data or "recommendedPapers" not in rec_data:
        return []

    return [_s2_paper(p) for p in rec_data["recommendedPapers"] if p.get("title")]


# ── arXiv ────────────────────────────────────────────────────────────

ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}


def search_arxiv(query: str, limit: int = 10) -> list[dict]:
    """Search arXiv by keyword."""
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": limit,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    print(f"  arXiv search: {query}", file=sys.stderr)

    req = urllib.request.Request(url, headers={"User-Agent": "research-agent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read().decode()
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  arXiv request failed: {e}", file=sys.stderr)
        return []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        return []

    papers = []
    for entry in root.findall("atom:entry", ARXIV_NS):
        title_el = entry.find("atom:title", ARXIV_NS)
        title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else ""
        if not title:
            continue

        abstract_el = entry.find("atom:summary", ARXIV_NS)
        abstract = abstract_el.text.strip().replace("\n", " ")[:500] if abstract_el is not None and abstract_el.text else ""

        authors_els = entry.findall("atom:author/atom:name", ARXIV_NS)
        authors = [a.text for a in authors_els if a.text]
        author_str = authors[0] if authors else ""
        if len(authors) > 1:
            author_str += " et al."

        published = entry.find("atom:published", ARXIV_NS)
        year = None
        if published is not None and published.text:
            year = int(published.text[:4])

        # Extract arXiv ID from the entry id URL
        id_el = entry.find("atom:id", ARXIV_NS)
        arxiv_id = ""
        entry_url = ""
        if id_el is not None and id_el.text:
            entry_url = id_el.text
            m = re.search(r"(\d{4}\.\d{4,5})", id_el.text)
            if m:
                arxiv_id = m.group(1)

        papers.append({
            "title": title,
            "authors": author_str,
            "year": year,
            "abstract": abstract,
            "url": entry_url,
            "arxiv_id": arxiv_id,
            "citations": 0,  # arXiv doesn't provide citation counts
            "source": "arxiv",
        })

    return papers


# ── Deduplication & context enrichment ────────────────────────────────

def _dedup(papers: list[dict]) -> list[dict]:
    """Deduplicate by normalized title, keeping the one with more info."""
    seen: dict[str, dict] = {}
    for p in papers:
        key = re.sub(r"\W+", " ", p["title"].lower()).strip()
        if key not in seen or p["citations"] > seen[key]["citations"]:
            seen[key] = p
    return list(seen.values())


def _enrich_from_state(state_path: str | None) -> list[str]:
    """Extract extra search terms from state.json context."""
    if not state_path or not Path(state_path).exists():
        return []
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return []

    extra = []
    # Add terms from recent iterations' papers
    for it in state.get("iterations", [])[-5:]:
        for paper in it.get("papers_referenced", []):
            extra.append(paper)
    return extra


# ── Main search pipeline ─────────────────────────────────────────────

def run_search(query: str, output_path: str, limit: int = 10,
               year_min: int | None = None, state_path: str | None = None,
               related_to: str | None = None) -> list[dict]:
    """Run combined search across Semantic Scholar + arXiv."""
    print(f"Searching: {query}", file=sys.stderr)
    all_papers: list[dict] = []

    # 1. Semantic Scholar keyword search
    s2_papers = search_semantic_scholar(query, limit=limit, year_min=year_min)
    all_papers.extend(s2_papers)

    # Brief pause to avoid rate limits
    time.sleep(1)

    # 2. arXiv keyword search
    arxiv_papers = search_arxiv(query, limit=limit)
    all_papers.extend(arxiv_papers)

    # 3. Recommendations based on a related paper (if provided)
    if related_to:
        time.sleep(1)
        rec_papers = recommend_semantic_scholar(related_to, limit=5)
        all_papers.extend(rec_papers)

    # 4. Deduplicate and sort by citations
    papers = _dedup(all_papers)
    papers.sort(key=lambda p: (p.get("citations", 0), p.get("year") or 0), reverse=True)

    # 5. Write output
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(papers, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Found {len(papers)} papers (S2: {len(s2_papers)}, "
          f"arXiv: {len(arxiv_papers)}) -> {output_path}", file=sys.stderr)
    return papers


def main():
    parser = argparse.ArgumentParser(
        description="Search for academic papers via Semantic Scholar + arXiv. "
                    "Pure Python, no API keys needed.",
        epilog="""Examples:
  python search_papers.py "Householder orthogonal adapters ViT" results.json
  python search_papers.py "medical image segmentation SAM adapter" results.json --limit 15
  python search_papers.py "nullspace projection PEFT" results.json --year-min 2023
  python search_papers.py "Gram matrix" results.json --related-to 2304.12620
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", help="Search query terms")
    parser.add_argument("output", help="Output JSON file path")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max results per source (default: 10)")
    parser.add_argument("--year-min", type=int, default=None,
                        help="Only papers from this year onward (S2 only)")
    parser.add_argument("--state", default=None,
                        help="Path to state.json for context enrichment")
    parser.add_argument("--related-to", default=None,
                        help="arXiv ID to get related paper recommendations")
    args = parser.parse_args()

    papers = run_search(
        args.query, args.output,
        limit=args.limit, year_min=args.year_min,
        state_path=args.state, related_to=args.related_to,
    )

    # Also print to stdout for immediate use
    json.dump(papers, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
