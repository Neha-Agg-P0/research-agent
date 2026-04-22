import asyncio
import httpx
from typing import List, Dict, Any

REDDIT_HEADERS = {"User-Agent": "RedditResearchAgent/1.0 (research tool)"}
REDDIT_BASE = "https://www.reddit.com"


async def _fetch_subreddit_posts(
    client: httpx.AsyncClient, query: str, subreddit: str, limit: int
) -> List[Dict[str, Any]]:
    url = f"{REDDIT_BASE}/r/{subreddit}/search.json"
    params = {"q": query, "restrict_sr": 1, "sort": "relevance", "limit": limit, "t": "year"}
    try:
        r = await client.get(url, params=params, headers=REDDIT_HEADERS, timeout=15.0)
        r.raise_for_status()
        children = r.json().get("data", {}).get("children", [])
        posts = []
        for child in children:
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
        print(f"[reddit] r/{subreddit} fetch failed: {exc}")
        return []


async def _fetch_post_comments(
    client: httpx.AsyncClient, post_id: str, subreddit: str
) -> List[str]:
    url = f"{REDDIT_BASE}/r/{subreddit}/comments/{post_id}.json"
    try:
        r = await client.get(url, headers=REDDIT_HEADERS, timeout=15.0)
        r.raise_for_status()
        data = r.json()
        if len(data) < 2:
            return []
        comments = []
        for child in data[1].get("data", {}).get("children", [])[:5]:
            body = (child.get("data") or {}).get("body", "")
            if body and body not in ("[deleted]", "[removed]"):
                comments.append(body[:400])
        return comments
    except Exception:
        return []


async def fetch_reddit_data(
    query: str, subreddits: List[str], limit: int = 25
) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        post_tasks = [_fetch_subreddit_posts(client, query, sub, limit) for sub in subreddits]
        results = await asyncio.gather(*post_tasks)

        all_posts: List[Dict[str, Any]] = []
        for batch in results:
            all_posts.extend(batch)

        all_posts.sort(key=lambda x: x["score"], reverse=True)

        # Fetch comments for the top 8 posts to stay within rate limits
        top_posts = all_posts[:8]
        comment_tasks = [
            _fetch_post_comments(client, p["id"], p["subreddit"]) for p in top_posts
        ]
        comment_results = await asyncio.gather(*comment_tasks)
        for post, comments in zip(top_posts, comment_results):
            post["top_comments"] = comments

    return all_posts
