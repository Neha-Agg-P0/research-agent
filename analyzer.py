import json
import anthropic
from typing import List, Dict, Any

_client = anthropic.Anthropic()

_ANALYSIS_TOOL = {
    "name": "save_analysis",
    "description": "Save structured analysis of Reddit posts",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall_sentiment": {
                "type": "string",
                "enum": ["positive", "negative", "neutral", "mixed"],
                "description": "Overall sentiment across all posts",
            },
            "sentiment_score": {
                "type": "number",
                "description": "Aggregate sentiment score from -1.0 (very negative) to 1.0 (very positive)",
            },
            "summary": {
                "type": "string",
                "description": "2-3 sentence overview of what the Reddit community is saying about this topic",
            },
            "themes": {
                "type": "array",
                "description": "3 to 6 major recurring themes found in the posts",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
                        "frequency": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                    "required": ["name", "description", "sentiment", "frequency"],
                },
            },
            "key_insights": {
                "type": "array",
                "description": "3 to 5 sharp, actionable insights from the data",
                "items": {"type": "string"},
            },
            "post_sentiments": {
                "type": "array",
                "description": "Per-post sentiment (1-indexed, matching input order)",
                "items": {
                    "type": "object",
                    "properties": {
                        "post_index": {"type": "integer"},
                        "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
                        "sentiment_score": {"type": "number"},
                    },
                    "required": ["post_index", "sentiment", "sentiment_score"],
                },
            },
        },
        "required": [
            "overall_sentiment",
            "sentiment_score",
            "summary",
            "themes",
            "key_insights",
            "post_sentiments",
        ],
    },
}

_SYSTEM_PROMPT = (
    "You are an expert Reddit research analyst. "
    "Given a set of Reddit posts and comments, you extract themes, measure sentiment, "
    "and surface actionable insights. Be precise, specific, and objective. "
    "Always call the save_analysis tool with your structured findings."
)


def _build_content(posts: List[Dict[str, Any]], query: str) -> str:
    lines = [f"Research query: {query}", f"Total posts: {len(posts)}", ""]
    for i, p in enumerate(posts[:25], 1):
        lines.append(f"=== Post {i} ===")
        lines.append(f"Title: {p['title']}")
        lines.append(f"Subreddit: r/{p['subreddit']}  Score: {p['score']}  Comments: {p['num_comments']}")
        if p.get("selftext"):
            lines.append(f"Body: {p['selftext']}")
        if p.get("top_comments"):
            lines.append("Top comments:")
            for c in p["top_comments"][:3]:
                lines.append(f"  • {c}")
        lines.append("")
    return "\n".join(lines)


def analyze_content(posts: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    content = _build_content(posts, query)

    response = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        tools=[_ANALYSIS_TOOL],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": content}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "save_analysis":
            return block.input

    # Fallback if tool wasn't called
    return {
        "overall_sentiment": "neutral",
        "sentiment_score": 0.0,
        "summary": "Analysis could not be completed.",
        "themes": [],
        "key_insights": [],
        "post_sentiments": [],
    }
