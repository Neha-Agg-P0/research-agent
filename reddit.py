import asyncio
import os
import httpx
from typing import List, Dict, Any

REDDIT_HEADERS = {"User-Agent": "RedditResearchAgent/1.0 (research tool)"}
REDDIT_BASE = "https://www.reddit.com"


def _has_oauth() -> bool:
    return bool(os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET"))


# ── PRAW (OAuth) path ─────────────────────────────────────────────────────────

def _praw_fetch_sync(query: str, subreddits: List[str], limit: int) -> List[Dict[str, Any]]:
    """Synchronous PRAW fetch — called via run_in_executor to avoid blocking."""
    import praw

    reddit = praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent="RedditResearchAgent/1.0",
    )

    all_posts: List[Dict[str, Any]] = []
    for sub_name in subreddits:
        try:
            for submission in reddit.subreddit(sub_name).search(
                query, limit=limit, sort="relevance", time_filter="year"
            ):
                all_posts.append({
                    "id": submission.id,
                    "title": submission.title,
                    "subreddit": submission.subreddit.display_name,
                    "author": str(submission.author) if submission.author else "[deleted]",
                    "score": submission.score,
                    "upvote_ratio": submission.upvote_ratio,
                    "num_comments": submission.num_comments,
                    "url": f"https://reddit.com{submission.permalink}",
                    "selftext": (submission.selftext or "")[:800],
                    "created_utc": submission.created_utc,
                    "is_self": submission.is_self,
                    "top_comments": [],
                })
        except Exception as exc:
            print(f"[praw] r/{sub_name}: {exc}")

    all_posts.sort(key=lambda x: x["score"], reverse=True)

    # Fetch top comments for the highest-scoring posts
    for post in all_posts[:8]:
        try:
            submission = reddit.submission(id=post["id"])
            submission.comment_sort = "top"
            submission.comments.replace_more(limit=0)
            comments = []
            for comment in list(submission.comments)[:5]:
                body = getattr(comment, "body", "")
                if body and body not in ("[deleted]", "[removed]"):
                    comments.append(body[:400])
            post["top_comments"] = comments[:3]
        except Exception:
            pass

    return all_posts


# ── Public JSON API (fallback, no credentials) ────────────────────────────────

async def _public_fetch_posts(
    client: httpx.AsyncClient, query: str, subreddit: str, limit: int
) -> List[Dict[str, Any]]:
    url = f"{REDDIT_BASE}/r/{subreddit}/search.json"
    params = {"q": query, "restrict_sr": 1, "sort": "relevance", "limit": limit, "t": "year"}
    try:
        r = await client.get(url, params=params, headers=REDDIT_HEADERS, timeout=15.0)
        r.raise_for_status()
        posts = []
        for child in r.json().get("data", {}).get("children", []):
            p = child.get("data", {})
            posts.append({
                "id": p.get("id", ""),
                "title": p.get("title", ""),
                "subreddit": p.get("subreddit", subreddit),
                "author": p.get("author", "[unknown]"),
                "score": p.get("score", 0),
                "upvote_ratio": p.get("upvote_ratio", 0.5),
                "num_comments": p.get("num_comments", 0),
                "url": f"{REDDIT_BASE}{p.get('permalink', '')}",
                "selftext": (p.get("selftext") or "")[:800],
                "created_utc": p.get("created_utc", 0),
                "is_self": p.get("is_self", True),
                "top_comments": [],
            })
        return posts
    except Exception as exc:
        print(f"[public] r/{subreddit}: {exc}")
        return []


async def _public_fetch_comments(
    client: httpx.AsyncClient, post_id: str, subreddit: str
) -> List[str]:
    url = f"{REDDIT_BASE}/r/{subreddit}/comments/{post_id}.json"
    try:
        r = await client.get(url, headers=REDDIT_HEADERS, timeout=15.0)
        r.raise_for_status()
        data = r.json()
        comments = []
        if len(data) > 1:
            for child in data[1].get("data", {}).get("children", [])[:5]:
                body = (child.get("data") or {}).get("body", "")
                if body and body not in ("[deleted]", "[removed]"):
                    comments.append(body[:400])
        return comments[:3]
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


# ── Public entry point ────────────────────────────────────────────────────────

async def fetch_reddit_data(
    query: str, subreddits: List[str], limit: int = 25
) -> List[Dict[str, Any]]:
    if _has_oauth():
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _praw_fetch_sync, query, subreddits, limit)
    return await _fetch_public(query, subreddits, limit)
