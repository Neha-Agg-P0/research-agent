import asyncio
import os
import httpx
from typing import List, Dict, Any

REDDIT_BASE = "https://www.reddit.com"
OAUTH_BASE = "https://oauth.reddit.com"
USER_AGENT = "RedditResearchAgent/1.0"


def _has_oauth() -> bool:
    return bool(os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET"))


async def _get_oauth_token(client: httpx.AsyncClient) -> str:
    """Exchange client credentials for a bearer token (application-only OAuth)."""
    r = await client.post(
        f"{REDDIT_BASE}/api/v1/access_token",
        auth=(os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": USER_AGENT},
        timeout=10.0,
    )
    r.raise_for_status()
    return r.json()["access_token"]


async def _oauth_fetch_posts(
    client: httpx.AsyncClient, token: str, query: str, subreddit: str, limit: int
) -> List[Dict[str, Any]]:
    headers = {"Authorization": f"bearer {token}", "User-Agent": USER_AGENT}
    params = {"q": query, "restrict_sr": 1, "sort": "relevance", "limit": limit, "t": "year"}
    try:
        r = await client.get(
            f"{OAUTH_BASE}/r/{subreddit}/search", params=params, headers=headers, timeout=15.0
        )
        r.raise_for_status()
        posts = []
        for child in r.json().get("data", {}).get("children", []):
            p = child.get("data", {})
            posts.append(_shape_post(p, subreddit))
        return posts
    except Exception as exc:
        print(f"[oauth] r/{subreddit}: {exc}")
        return []


async def _oauth_fetch_comments(
    client: httpx.AsyncClient, token: str, post_id: str, subreddit: str
) -> List[str]:
    headers = {"Authorization": f"bearer {token}", "User-Agent": USER_AGENT}
    try:
        r = await client.get(
            f"{OAUTH_BASE}/r/{subreddit}/comments/{post_id}",
            params={"limit": 5, "depth": 1, "sort": "top"},
            headers=headers,
            timeout=15.0,
        )
        r.raise_for_status()
        data = r.json()
        return _extract_comments(data)
    except Exception:
        return []


async def _fetch_with_oauth(
    query: str, subreddits: List[str], limit: int
) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        token = await _get_oauth_token(client)
        batches = await asyncio.gather(
            *[_oauth_fetch_posts(client, token, query, sub, limit) for sub in subreddits]
        )
        all_posts = [p for batch in batches for p in batch]
        all_posts.sort(key=lambda x: x["score"], reverse=True)

        comment_results = await asyncio.gather(
            *[_oauth_fetch_comments(client, token, p["id"], p["subreddit"]) for p in all_posts[:8]]
        )
        for post, comments in zip(all_posts[:8], comment_results):
            post["top_comments"] = comments

    return all_posts


# ── Public JSON API (fallback, no credentials) ────────────────────────────────

async def _public_fetch_posts(
    client: httpx.AsyncClient, query: str, subreddit: str, limit: int
) -> List[Dict[str, Any]]:
    headers = {"User-Agent": USER_AGENT}
    params = {"q": query, "restrict_sr": 1, "sort": "relevance", "limit": limit, "t": "year"}
    try:
        r = await client.get(
            f"{REDDIT_BASE}/r/{subreddit}/search.json", params=params, headers=headers, timeout=15.0
        )
        r.raise_for_status()
        posts = []
        for child in r.json().get("data", {}).get("children", []):
            posts.append(_shape_post(child.get("data", {}), subreddit))
        return posts
    except Exception as exc:
        print(f"[public] r/{subreddit}: {exc}")
        return []


async def _public_fetch_comments(
    client: httpx.AsyncClient, post_id: str, subreddit: str
) -> List[str]:
    headers = {"User-Agent": USER_AGENT}
    try:
        r = await client.get(
            f"{REDDIT_BASE}/r/{subreddit}/comments/{post_id}.json", headers=headers, timeout=15.0
        )
        r.raise_for_status()
        return _extract_comments(r.json())
    except Exception:
        return []


async def _fetch_public(
    query: str, subreddits: List[str], limit: int
) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        batches = await asyncio.gather(
            *[_public_fetch_posts(client, query, sub, limit) for sub in subreddits]
        )
        all_posts = [p for batch in batches for p in batch]
        all_posts.sort(key=lambda x: x["score"], reverse=True)

        comment_results = await asyncio.gather(
            *[_public_fetch_comments(client, p["id"], p["subreddit"]) for p in all_posts[:8]]
        )
        for post, comments in zip(all_posts[:8], comment_results):
            post["top_comments"] = comments

    return all_posts


# ── Shared helpers ────────────────────────────────────────────────────────────

def _shape_post(p: dict, fallback_subreddit: str) -> Dict[str, Any]:
    return {
        "id": p.get("id", ""),
        "title": p.get("title", ""),
        "subreddit": p.get("subreddit", fallback_subreddit),
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


def _extract_comments(data: list) -> List[str]:
    comments = []
    if len(data) > 1:
        for child in data[1].get("data", {}).get("children", [])[:5]:
            body = (child.get("data") or {}).get("body", "")
            if body and body not in ("[deleted]", "[removed]"):
                comments.append(body[:400])
    return comments[:3]


# ── Public entry point ────────────────────────────────────────────────────────

async def fetch_reddit_data(
    query: str, subreddits: List[str], limit: int = 25
) -> List[Dict[str, Any]]:
    if _has_oauth():
        return await _fetch_with_oauth(query, subreddits, limit)
    return await _fetch_public(query, subreddits, limit)
