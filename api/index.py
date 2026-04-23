import json
import asyncio
import os
from typing import List, Dict, Any

import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

from analyzer import analyze_content

app = FastAPI(title="Reddit Research Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

REDDIT_BASE = "https://www.reddit.com"
OAUTH_BASE = "https://oauth.reddit.com"
USER_AGENT = "RedditResearchAgent/1.0"


class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    subreddits: List[str] = Field(..., min_length=1)
    limit: int = Field(default=25, ge=5, le=50)


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def _shape(p: dict, fallback: str) -> Dict[str, Any]:
    return {
        "id": p.get("id", ""),
        "title": p.get("title", ""),
        "subreddit": p.get("subreddit", fallback),
        "author": p.get("author", "[unknown]"),
        "score": p.get("score", 0),
        "upvote_ratio": p.get("upvote_ratio", 0.5),
        "num_comments": p.get("num_comments", 0),
        "url": f"{REDDIT_BASE}{p.get('permalink', '')}",
        "selftext": (p.get("selftext") or "")[:800],
        "created_utc": p.get("created_utc", 0),
        "is_self": p.get("is_self", True),
        "top_comments": [],
    }


async def _fetch_posts(client: httpx.AsyncClient, headers: dict,
                       query: str, subreddit: str, limit: int, oauth: bool) -> List[Dict]:
    base = OAUTH_BASE if oauth else REDDIT_BASE
    url = f"{base}/r/{subreddit}/search" + ("" if oauth else ".json")
    params = {"q": query, "restrict_sr": 1, "sort": "relevance", "limit": limit, "t": "year"}
    try:
        r = await client.get(url, params=params, headers=headers, timeout=15.0)
        r.raise_for_status()
        return [_shape(c["data"], subreddit) for c in r.json().get("data", {}).get("children", [])]
    except Exception as e:
        print(f"[reddit] r/{subreddit}: {e}")
        return []


async def _fetch_comments(client: httpx.AsyncClient, headers: dict,
                          post_id: str, subreddit: str, oauth: bool) -> List[str]:
    base = OAUTH_BASE if oauth else REDDIT_BASE
    url = f"{base}/r/{subreddit}/comments/{post_id}" + ("" if oauth else ".json")
    try:
        r = await client.get(url, headers=headers, timeout=15.0)
        r.raise_for_status()
        data = r.json()
        comments = []
        for child in (data[1].get("data", {}).get("children", []) if len(data) > 1 else [])[:5]:
            body = (child.get("data") or {}).get("body", "")
            if body and body not in ("[deleted]", "[removed]"):
                comments.append(body[:400])
        return comments[:3]
    except Exception:
        return []


async def fetch_reddit(query: str, subreddits: List[str], limit: int) -> List[Dict]:
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    oauth = bool(client_id and client_secret)

    async with httpx.AsyncClient() as client:
        if oauth:
            r = await client.post(
                f"{REDDIT_BASE}/api/v1/access_token",
                auth=(client_id, client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": USER_AGENT},
                timeout=10.0,
            )
            token = r.json()["access_token"]
            headers = {"Authorization": f"bearer {token}", "User-Agent": USER_AGENT}
        else:
            headers = {"User-Agent": USER_AGENT}

        batches = await asyncio.gather(
            *[_fetch_posts(client, headers, query, sub, limit, oauth) for sub in subreddits]
        )
        all_posts = [p for batch in batches for p in batch]
        all_posts.sort(key=lambda x: x["score"], reverse=True)

        comment_results = await asyncio.gather(
            *[_fetch_comments(client, headers, p["id"], p["subreddit"], oauth) for p in all_posts[:8]]
        )
        for post, comments in zip(all_posts[:8], comment_results):
            post["top_comments"] = comments

    return all_posts


@app.post("/api/research")
async def research(req: ResearchRequest):
    subreddits = [s.strip().lstrip("r/") for s in req.subreddits if s.strip()]

    async def stream():
        yield _sse("progress", {"step": 1, "message": f"Fetching posts from {len(subreddits)} subreddit(s)…"})
        try:
            posts = await fetch_reddit(req.query, subreddits, req.limit)
        except Exception as e:
            yield _sse("error", {"message": f"Reddit fetch failed: {e}"})
            return

        if not posts:
            yield _sse("error", {"message": "No posts found. Try a different query or subreddits."})
            return

        yield _sse("progress", {"step": 2, "message": f"Found {len(posts)} posts. Analyzing with Claude…"})
        try:
            loop = asyncio.get_event_loop()
            analysis = await loop.run_in_executor(None, analyze_content, posts, req.query)
            yield _sse("results", {"posts": posts, "analysis": analysis})
        except Exception as e:
            yield _sse("error", {"message": f"Analysis failed: {e}"})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health():
    return {"status": "ok"}
