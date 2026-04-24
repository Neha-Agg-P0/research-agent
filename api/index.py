import json
import asyncio
import re
from typing import Dict, List, Tuple

import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

from connectors import (
    fetch_rss, fetch_google_news, fetch_page, fetch_indeed, ConnectorResult
)
from analyzer import analyze_content

app = FastAPI(title="FA Research Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── Source registry ──────────────────────────────────────────────────────────
#
# tier 1 = durable (RSS / open HTTP) — product works on these alone
# tier 2 = conditional (scrape, platform-governed, frequently blocked)

SOURCES = [
    # ── Tier 1: RSS ───────────────────────────────────────────────────────────
    {"id": "kitces",       "name": "Kitces",           "tier": 1, "type": "rss",
     "url": "https://www.kitces.com/feed/",
     "themes": ["industry", "technology", "growth"]},

    {"id": "thinkadvisor", "name": "ThinkAdvisor",     "tier": 1, "type": "rss",
     "url": "https://www.thinkadvisor.com/feed/",
     "themes": ["industry", "talent", "growth"]},

    {"id": "investmentnews","name": "InvestmentNews",  "tier": 1, "type": "rss",
     "url": "https://www.investmentnews.com/feed",
     "themes": ["industry", "technology", "talent"]},

    {"id": "riabiz",       "name": "RIABiz",           "tier": 1, "type": "rss",
     "url": "https://riabiz.com/feed",
     "themes": ["industry", "talent"]},

    {"id": "wealthmgmt",   "name": "WealthManagement", "tier": 1, "type": "rss",
     "url": "https://www.wealthmanagement.com/rss.xml",
     "themes": ["industry"]},

    {"id": "finplanning",  "name": "Financial Planning","tier": 1, "type": "rss",
     "url": "https://www.financial-planning.com/feed",
     "themes": ["industry", "growth"]},

    {"id": "famag",        "name": "FA Magazine",       "tier": 1, "type": "rss",
     "url": "https://www.fa-mag.com/rss",
     "themes": ["growth", "industry"]},

    {"id": "techcrunch",   "name": "TechCrunch Fintech","tier": 1, "type": "rss",
     "url": "https://techcrunch.com/category/fintech/feed/",
     "themes": ["technology"]},

    {"id": "tearsheet",    "name": "Tearsheet",         "tier": 1, "type": "rss",
     "url": "https://tearsheet.co/feed/",
     "themes": ["technology"]},

    {"id": "xypn",         "name": "XYPN",              "tier": 1, "type": "rss",
     "url": "https://www.xyplanningnetwork.com/feed/",
     "themes": ["growth"]},

    {"id": "fpa",          "name": "FPA",               "tier": 1, "type": "rss",
     "url": "https://www.financialplanningassociation.org/learning/publications/journal/feed",
     "themes": ["growth"]},

    # ── Tier 2: conditional ───────────────────────────────────────────────────
    {"id": "kitces_map",   "name": "Kitces Tech Map",   "tier": 2, "type": "page",
     "url": "https://www.kitces.com/technology-map/",
     "page_title": "Kitces Financial Advisor Technology Map",
     "themes": ["technology"]},

    {"id": "indeed",       "name": "Indeed Jobs",       "tier": 2, "type": "indeed",
     "themes": ["talent"]},
]

# Google News query templates per theme (run dynamically against query)
GN_TEMPLATES: Dict[str, List[str]] = {
    "industry": [
        "{q} financial advisor wirehouse RIA \"broker dealer\"",
        "{q} wealth management firm merger acquisition consolidation",
        "{q} Cerulli financial advisor benchmark",
    ],
    "technology": [
        "{q} financial advisor technology fintech wealthtech platform",
        "{q} advisor software AI automation",
    ],
    "talent": [
        "{q} financial advisor hiring recruiting breakaway transition",
    ],
    "growth": [
        "{q} financial advisor practice management growth",
        "{q} advisor client acquisition business development",
        "{q} Cerulli Schwab Fidelity RIA benchmarking study",
    ],
}

VALID_THEMES = {"industry", "technology", "talent", "growth"}


class ResearchRequest(BaseModel):
    query:  str        = Field(..., min_length=1, max_length=200)
    themes: List[str]  = Field(default=["industry", "technology", "talent", "growth"])


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


# ─── Planner + orchestrator ───────────────────────────────────────────────────

async def fetch_all(query: str, themes: List[str]) -> Tuple[List[Dict], List[Dict]]:
    """
    Returns (articles, failed_sources).
    Degrades gracefully — a useful result is returned even if many sources fail.
    """
    tasks = []
    seen_urls: set = set()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        # Unfiltered base search — captures direct company / product name hits
        tasks.append(fetch_google_news(client, "gn_base", query, "general"))

        for src in SOURCES:
            relevant_themes = [t for t in src["themes"] if t in themes]
            if not relevant_themes:
                continue
            theme = relevant_themes[0]

            if src["type"] == "rss":
                url = src["url"]
                if url not in seen_urls:
                    seen_urls.add(url)
                    tasks.append(fetch_rss(client, src["id"], src["name"], url, theme))

            elif src["type"] == "page":
                tasks.append(fetch_page(
                    client, src["id"], src["name"], src["url"],
                    theme, src.get("page_title", src["name"])
                ))

            elif src["type"] == "indeed" and "talent" in themes:
                tasks.append(fetch_indeed(client, src["id"], query))

        # Google News per theme — run in parallel with static sources
        for theme in themes:
            for i, tmpl in enumerate(GN_TEMPLATES.get(theme, [])):
                gid = f"gn_{theme}_{i}"
                tasks.append(fetch_google_news(client, gid, tmpl.format(q=query), theme))

        results: List[ConnectorResult] = await asyncio.gather(*tasks)

    # Separate health report from articles
    failed = [
        {"source": r.source_name, "error": r.error_type, "msg": r.error_msg[:120]}
        for r in results if not r.success and r.articles == []
    ]

    all_articles = [a for r in results for a in r.articles]

    # Deduplicate by normalized title prefix
    seen_titles: set = set()
    unique: List[Dict] = []
    for a in all_articles:
        key = re.sub(r"[^a-z0-9]", "", a["title"].lower())[:50]
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(a)

    return unique[:60], failed


# ─── Endpoint ─────────────────────────────────────────────────────────────────

@app.post("/api/research")
async def research(req: ResearchRequest):
    themes = [t for t in req.themes if t in VALID_THEMES]

    async def stream():
        if not themes:
            yield _sse("error", {"message": "Select at least one theme."})
            return

        yield _sse("progress", {"step": 1, "message": "Searching across sources…"})
        try:
            articles, failed = await fetch_all(req.query, themes)
        except Exception as e:
            yield _sse("error", {"message": f"Fetch failed: {e}"})
            return

        if not articles:
            fail_summary = ", ".join(f"{f['source']} ({f['error']})" for f in failed[:5])
            yield _sse("error", {
                "message": f"No results found — all {len(failed)} sources failed. Try a broader query.",
                "failed_sources": failed,
                "detail": fail_summary,
            })
            return

        n_ok = len({a["source"] for a in articles})
        yield _sse("progress", {
            "step": 2,
            "message": f"Found {len(articles)} articles from {n_ok} sources — analyzing with Claude…"
        })

        try:
            loop = asyncio.get_event_loop()
            analysis = await loop.run_in_executor(
                None, analyze_content, articles, req.query, themes
            )
            yield _sse("results", {
                "articles":      articles,
                "analysis":      analysis,
                "failed_sources": failed,
            })
        except Exception as e:
            yield _sse("error", {"message": f"Analysis failed: {e}"})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/debug")
async def debug():
    """Test outbound connectivity and individual sources — visible at /api/debug"""
    import sys
    report = {"python": sys.version, "sources": {}}

    test_urls = [
        ("httpbin",      "https://httpbin.org/get"),
        ("kitces",       "https://www.kitces.com/feed/"),
        ("thinkadvisor", "https://www.thinkadvisor.com/feed/"),
        ("investmentnews","https://www.investmentnews.com/feed"),
        ("google_news",  "https://news.google.com/rss/search?q=financial+advisor&hl=en-US"),
    ]

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for name, url in test_urls:
            try:
                r = await client.get(url, headers={"User-Agent": "FAResearchAgent/1.0"}, timeout=8.0)
                report["sources"][name] = {
                    "status": r.status_code,
                    "ok": r.status_code < 400,
                    "bytes": len(r.content),
                }
            except Exception as e:
                report["sources"][name] = {"ok": False, "error": type(e).__name__, "detail": str(e)[:200]}

    return report
