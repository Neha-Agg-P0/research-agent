import json
import asyncio
import os
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

if not os.getenv("ANTHROPIC_API_KEY"):
    raise RuntimeError("ANTHROPIC_API_KEY is not set.")

from analyzer import analyze_content

app = FastAPI(title="Reddit Research Agent")


class AnalyzeRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    posts: List[Dict[str, Any]] = Field(..., min_length=1)


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    async def stream():
        yield _sse("progress", {"message": f"Analyzing {len(req.posts)} posts with Claude…"})
        try:
            loop = asyncio.get_event_loop()
            analysis = await loop.run_in_executor(None, analyze_content, req.posts, req.query)
            yield _sse("results", {"analysis": analysis})
        except Exception as exc:
            yield _sse("error", {"message": f"Analysis failed: {exc}"})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
