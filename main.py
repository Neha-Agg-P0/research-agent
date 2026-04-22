import json
import asyncio
import os
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

if not os.getenv("ANTHROPIC_API_KEY"):
    raise RuntimeError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")

from reddit import fetch_reddit_data
from analyzer import analyze_content

app = FastAPI(title="Reddit Research Agent")


class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    subreddits: List[str] = Field(..., min_length=1, max_length=10)
    limit: int = Field(default=25, ge=5, le=50)


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


@app.post("/api/research")
async def research(req: ResearchRequest):
    subreddits = [s.strip().lstrip("r/") for s in req.subreddits if s.strip()]
    if not subreddits:
        raise HTTPException(status_code=400, detail="At least one subreddit required")

    async def stream():
        yield _sse("progress", {"step": 1, "message": f"Fetching posts from {len(subreddits)} subreddit(s)…"})

        try:
            posts = await fetch_reddit_data(req.query, subreddits, req.limit)
        except Exception as exc:
            yield _sse("error", {"message": f"Reddit fetch failed: {exc}"})
            return

        if not posts:
            yield _sse("error", {"message": "No posts found. Try a different query or subreddits."})
            return

        yield _sse("progress", {"step": 2, "message": f"Found {len(posts)} posts. Analyzing with Claude…"})

        try:
            # Run synchronous Claude call in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            analysis = await loop.run_in_executor(None, analyze_content, posts, req.query)
        except Exception as exc:
            yield _sse("error", {"message": f"Analysis failed: {exc}"})
            return

        yield _sse("results", {"posts": posts, "analysis": analysis})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the frontend — must come after API routes
app.mount("/", StaticFiles(directory="static", html=True), name="static")
