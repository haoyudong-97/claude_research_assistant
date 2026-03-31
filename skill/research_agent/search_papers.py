#!/usr/bin/env python3
"""Search for academic papers via Semantic Scholar + arXiv APIs.

Strategy: cast a wide net (20+ candidates), rank by relevance, keep the top 5,
then fetch the FULL content for each via arXiv HTML. This gives the Agent
complete paper context instead of truncated abstracts.

Pure Python, no external dependencies. Both APIs are free and need no auth.

Usage:
    python -m research_agent.search_papers "query terms" output.json
    python -m research_agent.search_papers "query" output.json --limit 5
    python -m research_agent.search_papers "query" output.json --year-min 2024
    python -m research_agent.search_papers "query" output.json --related-to 2401.12345
    python -m research_agent.search_papers "query" output.json --no-fulltext

Output:
    Writes JSON array to output.json with fields:
        title, authors, year, abstract, url, arxiv_id, citations, source, fulltext
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


# ── Cache ────────────────────────────────────────────────────────────

CACHE_DIR = Path(os.environ.get(
    "RESEARCH_CACHE_DIR",
    Path(__file__).resolve().parent / ".cache",
))
CACHE_TTL = int(os.environ.get("RESEARCH_CACHE_TTL", "900"))  # 15 min default

MAX_FULLTEXT_CHARS = 20_000   # per paper
MAX_TOTAL_CHARS = 100_000     # total output cap (like Claude Code's WebFetch)
TOP_K = 5                     # default number of papers to return


def _cache_key(prefix: str, url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{prefix}_{h}.json"


def _cache_get(prefix: str, url: str) -> dict | list | None:
    p = _cache_key(prefix, url)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > CACHE_TTL:
        p.unlink(missing_ok=True)
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return None


def _cache_put(prefix: str, url: str, data: dict | list) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _cache_key(prefix, url)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ── HTTP helper ──────────────────────────────────────────────────────

def _http_get(url: str, timeout: int = 15) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": "research-agent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  HTTP failed ({url[:80]}): {e}", file=sys.stderr)
        return None


# ── Semantic Scholar ─────────────────────────────────────────────────

S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,abstract,year,citationCount,url,authors,externalIds"
S2_RECOMMEND = "https://api.semanticscholar.org/recommendations/v1/papers"


def _s2_request(url: str) -> dict | None:
    cached = _cache_get("s2", url)
    if cached is not None:
        return cached
    body = _http_get(url)
    if body is None:
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    _cache_put("s2", url, data)
    return data


def _s2_paper(raw: dict) -> dict:
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
        "abstract": raw.get("abstract") or "",
        "url": raw.get("url", ""),
        "arxiv_id": arxiv_id,
        "citations": raw.get("citationCount", 0),
        "source": "semantic_scholar",
    }


def search_semantic_scholar(query: str, limit: int = 20,
                            year_min: int | None = None) -> list[dict]:
    params = {"query": query, "limit": limit, "fields": S2_FIELDS}
    if year_min:
        params["year"] = f"{year_min}-"
    url = f"{S2_SEARCH}?{urllib.parse.urlencode(params)}"
    print(f"  S2 search: {query}", file=sys.stderr)
    data = _s2_request(url)
    if not data or "data" not in data:
        return []
    return [_s2_paper(p) for p in data["data"] if p.get("title")]


def recommend_semantic_scholar(arxiv_id: str, limit: int = 10) -> list[dict]:
    resolve_url = f"https://api.semanticscholar.org/graph/v1/paper/ArXiv:{arxiv_id}"
    resolve_url += "?fields=paperId"
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


def search_arxiv(query: str, limit: int = 20) -> list[dict]:
    params = {
        "search_query": f"all:{query}", "start": 0,
        "max_results": limit, "sortBy": "relevance", "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    print(f"  arXiv search: {query}", file=sys.stderr)

    cached = _cache_get("arxiv", url)
    if cached is not None:
        return cached

    body = _http_get(url)
    if body is None:
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []

    papers = []
    for entry in root.findall("atom:entry", ARXIV_NS):
        title_el = entry.find("atom:title", ARXIV_NS)
        title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else ""
        if not title:
            continue
        abstract_el = entry.find("atom:summary", ARXIV_NS)
        abstract = abstract_el.text.strip().replace("\n", " ") if abstract_el is not None and abstract_el.text else ""
        authors_els = entry.findall("atom:author/atom:name", ARXIV_NS)
        author_names = [a.text for a in authors_els if a.text]
        author_str = author_names[0] if author_names else ""
        if len(author_names) > 1:
            author_str += " et al."
        published = entry.find("atom:published", ARXIV_NS)
        year = int(published.text[:4]) if published is not None and published.text else None
        id_el = entry.find("atom:id", ARXIV_NS)
        arxiv_id, entry_url = "", ""
        if id_el is not None and id_el.text:
            entry_url = id_el.text
            m = re.search(r"(\d{4}\.\d{4,5})", id_el.text)
            if m:
                arxiv_id = m.group(1)
        papers.append({"title": title, "authors": author_str, "year": year,
                       "abstract": abstract, "url": entry_url, "arxiv_id": arxiv_id,
                       "citations": 0, "source": "arxiv"})

    _cache_put("arxiv", url, papers)
    return papers


# ── Full-text fetching ───────────────────────────────────────────────

def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_fulltext(arxiv_id: str) -> str:
    if not arxiv_id:
        return ""
    cached = _cache_get("fulltext", arxiv_id)
    if cached is not None:
        return cached.get("text", "")
    url = f"https://arxiv.org/html/{arxiv_id}"
    print(f"  Fetching fulltext: {url}", file=sys.stderr)
    html = _http_get(url, timeout=30)
    if html is None or len(html) < 500:
        _cache_put("fulltext", arxiv_id, {"text": ""})
        return ""
    text = _strip_html(html)
    if len(text) > MAX_FULLTEXT_CHARS:
        text = text[:MAX_FULLTEXT_CHARS] + "\n\n[...truncated at 20k chars]"
    _cache_put("fulltext", arxiv_id, {"text": text})
    return text


# ── Deduplication & ranking ──────────────────────────────────────────

def _dedup(papers: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for p in papers:
        key = re.sub(r"\W+", " ", p["title"].lower()).strip()
        if key not in seen or p["citations"] > seen[key]["citations"]:
            seen[key] = p
    return list(seen.values())


def _rank_papers(papers: list[dict]) -> list[dict]:
    current_year = time.gmtime().tm_year
    for p in papers:
        cite_score = math.log1p(p.get("citations", 0))
        year = p.get("year") or (current_year - 5)
        recency_score = max(0, (year - (current_year - 5))) / 5
        p["_score"] = cite_score + recency_score * 2
    papers.sort(key=lambda p: p["_score"], reverse=True)
    for p in papers:
        p.pop("_score", None)
    return papers


# ── Main search pipeline ─────────────────────────────────────────────

def run_search(query: str, output_path: str, limit: int = TOP_K,
               year_min: int | None = None, state_path: str | None = None,
               related_to: str | None = None, fetch_full: bool = True) -> list[dict]:
    print(f"Searching: {query} (top {limit})", file=sys.stderr)
    all_papers: list[dict] = []
    fetch_count = max(limit * 4, 20)

    s2_papers = search_semantic_scholar(query, limit=fetch_count, year_min=year_min)
    all_papers.extend(s2_papers)
    time.sleep(1)
    arxiv_papers = search_arxiv(query, limit=fetch_count)
    all_papers.extend(arxiv_papers)
    if related_to:
        time.sleep(1)
        all_papers.extend(recommend_semantic_scholar(related_to, limit=10))

    papers = _dedup(all_papers)
    papers = _rank_papers(papers)
    papers = papers[:limit]
    print(f"  Candidates: {len(all_papers)} -> dedup -> top {len(papers)}", file=sys.stderr)

    if fetch_full:
        for i, p in enumerate(papers):
            if p.get("arxiv_id"):
                time.sleep(1)
                p["fulltext"] = fetch_fulltext(p["arxiv_id"])
                status = f"{len(p['fulltext'])} chars" if p["fulltext"] else "no HTML"
                print(f"  [{i+1}/{len(papers)}] {p['title'][:60]}... ({status})", file=sys.stderr)
            else:
                p["fulltext"] = ""

    total_chars = sum(len(json.dumps(p, ensure_ascii=False)) for p in papers)
    if total_chars > MAX_TOTAL_CHARS:
        for p in reversed(papers):
            if total_chars <= MAX_TOTAL_CHARS:
                break
            ft = p.get("fulltext", "")
            if len(ft) > 1000:
                excess = total_chars - MAX_TOTAL_CHARS
                trim_to = max(1000, len(ft) - excess)
                p["fulltext"] = ft[:trim_to] + "\n\n[...trimmed to fit 100K total cap]"
                total_chars -= (len(ft) - trim_to)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(papers, f, indent=2, ensure_ascii=False)
        f.write("\n")

    ft_count = sum(1 for p in papers if p.get("fulltext"))
    print(f"Found {len(papers)} papers ({ft_count} with fulltext) -> {output_path}", file=sys.stderr)
    return papers


def main():
    parser = argparse.ArgumentParser(
        description="Search for academic papers. Returns top 5 with full text.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query", help="Search query terms")
    parser.add_argument("output", help="Output JSON file path")
    parser.add_argument("--limit", type=int, default=TOP_K)
    parser.add_argument("--year-min", type=int, default=None)
    parser.add_argument("--state", default=None)
    parser.add_argument("--related-to", default=None)
    parser.add_argument("--no-fulltext", action="store_true")
    args = parser.parse_args()
    papers = run_search(args.query, args.output, limit=args.limit, year_min=args.year_min,
                        state_path=args.state, related_to=args.related_to,
                        fetch_full=not args.no_fulltext)
    json.dump(papers, sys.stdout, indent=2, ensure_ascii=False)
    print()

if __name__ == "__main__":
    main()
