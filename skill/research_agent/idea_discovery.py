#!/usr/bin/env python3
"""Idea discovery: pull recent arXiv papers with full text for Agent digestion.

Fetches the latest papers from arXiv RSS feeds (and optionally Semantic Scholar),
ranks them, and returns the top 5 with full text. Idea generation is handled by
the Agent tool in the SKILL.md — this module only does paper fetching.

Usage:
    python -m research_agent.idea_discovery --categories cs.CV,eess.IV --days 3
    python -m research_agent.idea_discovery --categories cs.CV --days 3 \
        --s2-query "medical image segmentation"
    python -m research_agent.idea_discovery --categories cs.CV --days 7 \
        --limit 10 --no-fulltext

Output:
    results/recent_papers.json — top papers with full text
"""

import argparse
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_agent.search_papers import (
    _cache_get, _cache_put, _dedup, _http_get, _rank_papers,
    fetch_fulltext, search_semantic_scholar, MAX_TOTAL_CHARS, TOP_K,
)

ARXIV_RSS_BASE = "https://rss.arxiv.org/rss"

CATEGORY_ALIASES = {
    "medical-imaging": "eess.IV+cs.CV", "computer-vision": "cs.CV",
    "machine-learning": "cs.LG+stat.ML", "ai": "cs.AI", "nlp": "cs.CL", "robotics": "cs.RO",
}


def fetch_arxiv_rss(categories: str, days: int = 3) -> list[dict]:
    cats = categories.replace(",", "+")
    papers = []
    rss_url = f"{ARXIV_RSS_BASE}/{cats}"
    print(f"  Fetching arXiv RSS: {rss_url}", file=sys.stderr)
    cached = _cache_get("rss", rss_url)
    if cached is not None:
        papers.extend(cached)
        print(f"  RSS (cached): {len(cached)} papers", file=sys.stderr)
    else:
        xml_data = _http_get(rss_url, timeout=30)
        if xml_data:
            rss_papers = _parse_rss(xml_data)
            papers.extend(rss_papers)
            _cache_put("rss", rss_url, rss_papers)
            print(f"  RSS: {len(rss_papers)} papers", file=sys.stderr)
        else:
            print("  RSS fetch failed", file=sys.stderr)
    if days > 1:
        time.sleep(3)
        papers.extend(_fetch_arxiv_api(categories, days))
    papers = _dedup_papers(papers)
    print(f"  Total unique papers: {len(papers)}", file=sys.stderr)
    return papers


def _parse_rss(xml_data: str) -> list[dict]:
    papers = []
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        return []
    for item in root.findall(".//item"):
        title_el = item.find("title")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        if not title:
            continue
        title = re.sub(r"^arXiv:\d+\.\d+\s*", "", title).strip().replace("\n", " ")
        desc_el = item.find("description")
        abstract = ""
        if desc_el is not None and desc_el.text:
            abstract = re.sub(r"<[^>]+>", "", desc_el.text.strip()).replace("\n", " ")
        link_el = item.find("link")
        url = link_el.text.strip() if link_el is not None and link_el.text else ""
        arxiv_id = ""
        if url:
            m = re.search(r"(\d{4}\.\d{4,5})", url)
            if m:
                arxiv_id = m.group(1)
        creator_el = item.find("{http://purl.org/dc/elements/1.1/}creator")
        authors = creator_el.text.strip() if creator_el is not None and creator_el.text else ""
        papers.append({"title": title, "authors": authors, "abstract": abstract,
                       "url": url, "arxiv_id": arxiv_id, "citations": 0, "source": "arxiv_rss"})
    return papers


def _fetch_arxiv_api(categories: str, days: int) -> list[dict]:
    import urllib.parse
    cats = [c.strip() for c in categories.replace("+", ",").split(",")]
    cat_query = "+OR+".join(f"cat:{c}" for c in cats)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    params = {"search_query": cat_query, "start": 0,
              "max_results": min(days * 50, 200),
              "sortBy": "submittedDate", "sortOrder": "descending"}
    url = f"https://export.arxiv.org/api/query?{urllib.parse.urlencode(params)}"
    print(f"  Fetching arXiv API (last {days} days)...", file=sys.stderr)
    cached = _cache_get("arxiv_api", url)
    if cached is not None:
        print(f"  arXiv API (cached): {len(cached)} papers", file=sys.stderr)
        return cached
    body = _http_get(url, timeout=30)
    if body is None:
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    papers = []
    cutoff = start.isoformat()
    for entry in root.findall("atom:entry", ns):
        pub_el = entry.find("atom:published", ns)
        if pub_el is not None and pub_el.text and pub_el.text < cutoff:
            continue
        title_el = entry.find("atom:title", ns)
        title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else ""
        if not title:
            continue
        abstract_el = entry.find("atom:summary", ns)
        abstract = abstract_el.text.strip().replace("\n", " ") if abstract_el is not None and abstract_el.text else ""
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
        papers.append({"title": title, "authors": authors, "abstract": abstract,
                       "url": entry_url, "arxiv_id": arxiv_id, "citations": 0, "source": "arxiv_api"})
    print(f"  arXiv API: {len(papers)} papers in date range", file=sys.stderr)
    _cache_put("arxiv_api", url, papers)
    return papers


def _dedup_papers(papers: list[dict]) -> list[dict]:
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    unique = []
    for p in papers:
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


def run_discovery(categories: str, days: int = 3, s2_query: str | None = None,
                  papers_output: str = "results/recent_papers.json",
                  limit: int = TOP_K, fetch_full: bool = True) -> dict | None:
    print(f"=== Idea Discovery: {categories} (last {days} days, top {limit}) ===", file=sys.stderr)
    resolved = [CATEGORY_ALIASES.get(c.strip(), c.strip()) for c in categories.split(",")]
    cats = ",".join(resolved)
    papers = fetch_arxiv_rss(cats, days=days)
    if s2_query:
        time.sleep(1)
        papers.extend(search_semantic_scholar(s2_query, limit=20, year_min=datetime.now().year - 1))
        papers = _dedup_papers(papers)
    if not papers:
        print("No papers found.", file=sys.stderr)
        return None
    papers = _rank_papers(papers)[:limit]
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
    papers_out = Path(papers_output).resolve()
    papers_out.parent.mkdir(parents=True, exist_ok=True)
    with open(papers_out, "w", encoding="utf-8") as f:
        json.dump(papers, f, indent=2, ensure_ascii=False)
        f.write("\n")
    ft_count = sum(1 for p in papers if p.get("fulltext"))
    print(f"Saved {len(papers)} papers ({ft_count} with fulltext) -> {papers_output}", file=sys.stderr)
    return {"papers_count": len(papers), "fulltext_count": ft_count, "papers_file": papers_output}


def main():
    parser = argparse.ArgumentParser(description="Fetch recent papers, rank, return top K with full text.")
    parser.add_argument("--categories", required=True)
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--s2-query", default=None)
    parser.add_argument("--papers-output", default="results/recent_papers.json")
    parser.add_argument("--limit", type=int, default=TOP_K)
    parser.add_argument("--no-fulltext", action="store_true")
    args = parser.parse_args()
    result = run_discovery(categories=args.categories, days=args.days, s2_query=args.s2_query,
                           papers_output=args.papers_output, limit=args.limit, fetch_full=not args.no_fulltext)
    if result:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
