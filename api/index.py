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

# ─── Lens registry ────────────────────────────────────────────────────────────

LENS_NAMES = {
    "data":       "Data & Insights",
    "growth":     "Growth & Benchmarks",
    "technology": "Technology & AI",
    "operations": "Operations & Efficiency",
    "hnw":        "HNW Capabilities",
    "investor":   "Investor Strategy",
}
VALID_LENSES = set(LENS_NAMES.keys())

SEGMENT_KEYWORDS = {
    "solo":       '"solo advisor" OR "sole practitioner" OR "single advisor"',
    "lead":       '"lead advisor" OR "advisor team" OR "growing practice"',
    "ensemble":   '"ensemble firm" OR "ensemble practice" OR "multi-partner"',
    "enterprise": '"enterprise RIA" OR "large RIA" OR "multi-advisor"',
}

# ─── Source registry ──────────────────────────────────────────────────────────

SOURCES = [
    {"id": "kitces",       "name": "Kitces",            "tier": 1, "type": "rss",
     "url": "https://www.kitces.com/feed/",
     "lenses": ["technology", "growth"]},

    {"id": "thinkadvisor", "name": "ThinkAdvisor",      "tier": 1, "type": "rss",
     "url": "https://www.thinkadvisor.com/rss/news",
     "lenses": ["data", "investor", "hnw"]},

    {"id": "investmentnews","name": "InvestmentNews",   "tier": 1, "type": "rss",
     "url": "https://www.investmentnews.com/rss/news",
     "lenses": ["data", "technology", "growth"]},

    {"id": "riabiz",       "name": "RIABiz",            "tier": 1, "type": "rss",
     "url": "https://riabiz.com/articles.rss",
     "lenses": ["data", "operations"]},

    {"id": "wealthmgmt",   "name": "WealthManagement",  "tier": 1, "type": "rss",
     "url": "https://www.wealthmanagement.com/rss.xml",
     "lenses": ["hnw", "investor", "data"]},

    {"id": "finplanning",  "name": "Financial Planning", "tier": 1, "type": "rss",
     "url": "https://www.financial-planning.com/feed",
     "lenses": ["growth", "operations", "hnw"]},

    {"id": "famag",        "name": "FA Magazine",        "tier": 1, "type": "rss",
     "url": "https://www.fa-mag.com/rss",
     "lenses": ["growth", "data"]},

    {"id": "techcrunch",   "name": "TechCrunch Fintech", "tier": 1, "type": "rss",
     "url": "https://techcrunch.com/category/fintech/feed/",
     "lenses": ["technology"]},

    {"id": "tearsheet",    "name": "Tearsheet",          "tier": 1, "type": "rss",
     "url": "https://tearsheet.co/feed/",
     "lenses": ["technology"]},

    {"id": "xypn",         "name": "XYPN",               "tier": 1, "type": "rss",
     "url": "https://www.xyplanningnetwork.com/feed/",
     "lenses": ["growth", "operations"]},

    {"id": "fpa",          "name": "FPA",                "tier": 1, "type": "rss",
     "url": "https://www.financialplanningassociation.org/learning/publications/journal/feed",
     "lenses": ["growth"]},

    {"id": "kitces_map",   "name": "Kitces Tech Map",    "tier": 2, "type": "page",
     "url": "https://www.kitces.com/technology-map/",
     "page_title": "Kitces Financial Advisor Technology Map",
     "lenses": ["technology"]},

    {"id": "indeed",       "name": "Indeed Jobs",        "tier": 2, "type": "indeed",
     "lenses": ["data", "growth", "technology"]},
]

# ─── Google News query templates per lens ─────────────────────────────────────

GN_TEMPLATES: Dict[str, List[str]] = {
    "data": [
        "{q} financial advisor data analytics benchmark research",
        "{q} RIA practice analytics Cerulli research data products insights",
    ],
    "growth": [
        "{q} financial advisor growth program coaching benchmarking study",
        "{q} Cerulli Schwab Fidelity RIA benchmarking advisor practice management",
        "{q} advisor client acquisition business development practice growth",
    ],
    "technology": [
        "{q} financial advisor technology fintech wealthtech AI platform",
        "{q} advisor software CRM planning automation BD custodian technology",
        "{q} wealthtech startup advisor tool integration partnership",
    ],
    "operations": [
        "{q} financial advisor operations efficiency back-office workflow automation",
        "{q} advisor compliance rebalancing billing reporting operational efficiency",
    ],
    "hnw": [
        "{q} financial advisor high-net-worth HNW alternatives estate planning tax",
        "{q} advisor ultra-high-net-worth family office trust services custodian",
        "{q} alternatives access private equity HNW advisor capabilities",
    ],
    "investor": [
        "{q} investor demand financial advisor retirement income planning",
        "{q} client expectations advisor ESG values-based investing generational wealth",
        "{q} investor survey consumer research financial advisor demand",
    ],
}


class ResearchRequest(BaseModel):
    query:   str       = Field(..., min_length=1, max_length=200)
    lenses:  List[str] = Field(default=list(LENS_NAMES.keys()))
    segment: str       = Field(default="all")


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


# ─── Orchestrator ─────────────────────────────────────────────────────────────

async def fetch_all(
    query: str, lenses: List[str], segment: str
) -> Tuple[List[Dict], List[Dict]]:
    tasks = []
    seen_urls: set = set()
    seg_suffix = f" {SEGMENT_KEYWORDS[segment]}" if segment in SEGMENT_KEYWORDS else ""

    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks.append(fetch_google_news(client, "gn_base", query, "general"))

        for src in SOURCES:
            relevant = [l for l in src.get("lenses", []) if l in lenses]
            if not relevant:
                continue
            lens = relevant[0]
            if src["type"] == "rss":
                url = src["url"]
                if url not in seen_urls:
                    seen_urls.add(url)
                    tasks.append(fetch_rss(client, src["id"], src["name"], url, lens))
            elif src["type"] == "page":
                tasks.append(fetch_page(
                    client, src["id"], src["name"], src["url"],
                    lens, src.get("page_title", src["name"])
                ))
            elif src["type"] == "indeed":
                tasks.append(fetch_indeed(client, src["id"], query))

        for lens in lenses:
            for i, tmpl in enumerate(GN_TEMPLATES.get(lens, [])):
                gid = f"gn_{lens}_{i}"
                tasks.append(fetch_google_news(client, gid, tmpl.format(q=query) + seg_suffix, lens))

        results: List[ConnectorResult] = await asyncio.gather(*tasks)

    failed = [
        {"source": r.source_name, "error": r.error_type, "msg": r.error_msg[:120]}
        for r in results if not r.success and r.articles == []
    ]
    all_articles = [a for r in results for a in r.articles]

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
    active_lenses = [l for l in req.lenses if l in VALID_LENSES]
    segment = req.segment if req.segment in SEGMENT_KEYWORDS or req.segment == "all" else "all"

    async def stream():
        if not active_lenses:
            yield _sse("error", {"message": "Select at least one lens."})
            return

        yield _sse("progress", {"step": 1, "message": "Searching across sources…"})
        try:
            articles, failed = await fetch_all(req.query, active_lenses, segment)
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
            fut = loop.run_in_executor(
                None, analyze_content, articles, req.query, active_lenses, segment
            )
            # Send SSE keepalives every 8s so the connection doesn't idle-timeout
            while not fut.done():
                yield ": keepalive\n\n"
                try:
                    await asyncio.wait_for(asyncio.shield(fut), timeout=8.0)
                    break
                except asyncio.TimeoutError:
                    pass
            analysis = await fut
            yield _sse("results", {
                "articles":       articles,
                "analysis":       analysis,
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
    import sys, xml.etree.ElementTree as ET, re as _re
    report = {"python": sys.version, "sources": {}}

    test_urls = [
        ("httpbin",       "https://httpbin.org/get",                                                          False),
        ("kitces",        "https://www.kitces.com/feed/",                                                     True),
        ("thinkadvisor",  "https://www.thinkadvisor.com/rss/news",                                            True),
        ("investmentnews","https://www.investmentnews.com/rss/news",                                          True),
        ("riabiz",        "https://riabiz.com/articles.rss",                                                  True),
        ("google_news",   "https://news.google.com/rss/search?q=financial+advisor&hl=en-US&gl=US&ceid=US:en", True),
    ]

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for name, url, parse in test_urls:
            try:
                r = await client.get(url, headers={"User-Agent": "FAResearchAgent/1.0"}, timeout=10.0)
                entry: dict = {
                    "status":       r.status_code,
                    "ok":           r.status_code < 400,
                    "bytes":        len(r.content),
                    "content_type": r.headers.get("content-type", "?"),
                    "preview":      r.text[:200],
                }
                if parse and r.status_code < 400:
                    try:
                        clean = _re.sub(r'xmlns[^=]*="[^"]*"', "", r.text)
                        clean = _re.sub(r'<(/?)([a-zA-Z0-9_-]+):([a-zA-Z0-9_-]+)', r'<\1\3', clean)
                        root  = ET.fromstring(clean)
                        items = root.findall(".//item")
                        entry["items_found"] = len(items)
                        if items:
                            entry["first_title"] = (items[0].findtext("title") or "")[:80]
                    except ET.ParseError as pe:
                        entry["parse_error"] = str(pe)[:200]
                report["sources"][name] = entry
            except Exception as e:
                report["sources"][name] = {"ok": False, "error": type(e).__name__, "detail": str(e)[:200]}

    return report
