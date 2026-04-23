import anthropic
from typing import Dict, List

_client = anthropic.Anthropic()

_SYSTEM_PROMPT = """You are a senior financial services industry analyst covering the wealth management and financial advisory ecosystem. You track wirehouses (Merrill Lynch, Morgan Stanley, Wells Fargo Advisors, UBS), independent RIAs, broker-dealers, and the full spectrum of advisor-facing technology and growth programs.

You analyze content through four lenses:

INDUSTRY & FIRMS — firm strategy, M&A/consolidation, channel dynamics (wirehouse vs RIA vs BD), regulatory changes, competitive moves, market share shifts.

ADVISOR TECHNOLOGY — fintech and wealthtech products built for advisors: CRM, financial planning software, portfolio management, compliance, AI tools (e.g. Zocks AI, Jump AI, Finny), client engagement, document automation. Reference Kitces Technology Map categories when relevant.

TALENT & HIRING — advisor movement and recruiting, breakaway trends, headcount signals, firm growth or contraction, compensation trends.

GROWTH & PROGRAMS — advisor practice growth: client acquisition tools, marketing programs, coaching, succession planning, custodian and broker-dealer support programs, XYPN and FPA resources. Flag Cerulli, Schwab RIA Benchmarking, Fidelity, and InvestmentNews benchmark data explicitly — these carry high evidential weight.

Rules:
- Be specific. Cite source names and numbers when present.
- Flag Cerulli and other benchmark data prominently.
- Only analyze themes present in the active theme list.
- If a theme has no relevant content, omit it from theme_analysis.
- Surface concrete signal, not general observations."""

_TOOL = {
    "name": "save_analysis",
    "description": "Save structured FA industry intelligence",
    "input_schema": {
        "type": "object",
        "required": [
            "overall_sentiment", "sentiment_score", "executive_summary",
            "theme_analysis", "companies_and_products",
            "benchmark_data", "hiring_signal", "top_articles",
        ],
        "properties": {
            "overall_sentiment": {
                "type": "string",
                "enum": ["positive", "negative", "neutral", "mixed"],
            },
            "sentiment_score": {
                "type": "number",
                "description": "-1.0 (very negative) to 1.0 (very positive)",
            },
            "executive_summary": {
                "type": "string",
                "description": "2-3 sentence intelligence brief — what does this query reveal right now?",
            },
            "theme_analysis": {
                "type": "array",
                "description": "One entry per active theme that has relevant content",
                "items": {
                    "type": "object",
                    "required": ["theme", "headline", "insights", "sentiment"],
                    "properties": {
                        "theme": {
                            "type": "string",
                            "enum": ["industry", "technology", "talent", "growth"],
                        },
                        "headline": {
                            "type": "string",
                            "description": "One sharp sentence — the single most important finding for this theme",
                        },
                        "insights": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "3-5 specific findings; cite source names and numbers where available",
                        },
                        "sentiment": {
                            "type": "string",
                            "enum": ["positive", "negative", "neutral", "mixed"],
                        },
                    },
                },
            },
            "companies_and_products": {
                "type": "array",
                "description": "All notable firms, products, and startups mentioned",
                "items": {
                    "type": "object",
                    "required": ["name", "type", "context", "sentiment"],
                    "properties": {
                        "name": {"type": "string"},
                        "type": {
                            "type": "string",
                            "description": "wirehouse / RIA / broker-dealer / fintech / startup / custodian / association / other",
                        },
                        "product_category": {
                            "type": "string",
                            "description": "For fintechs: AI / CRM / planning / portfolio / compliance / marketing / other",
                        },
                        "context": {
                            "type": "string",
                            "description": "What is happening with this company — be specific",
                        },
                        "sentiment": {
                            "type": "string",
                            "enum": ["positive", "negative", "neutral"],
                        },
                    },
                },
            },
            "benchmark_data": {
                "type": "array",
                "description": "Benchmark stats, market-size figures, or research data points (Cerulli, Schwab, Fidelity, etc.)",
                "items": {
                    "type": "object",
                    "required": ["source", "stat", "significance"],
                    "properties": {
                        "source":       {"type": "string"},
                        "stat":         {"type": "string", "description": "The specific data point"},
                        "significance": {"type": "string"},
                    },
                },
            },
            "hiring_signal": {
                "type": "object",
                "required": ["trend", "notes"],
                "properties": {
                    "trend": {
                        "type": "string",
                        "enum": ["growing", "stable", "contracting", "unknown"],
                    },
                    "hot_roles": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "notes": {"type": "string"},
                },
            },
            "top_articles": {
                "type": "array",
                "description": "6-8 must-read articles — signal not noise",
                "items": {
                    "type": "object",
                    "required": ["article_index", "title", "source", "theme", "why_it_matters"],
                    "properties": {
                        "article_index":  {"type": "integer"},
                        "title":          {"type": "string"},
                        "source":         {"type": "string"},
                        "theme":          {"type": "string"},
                        "why_it_matters": {
                            "type": "string",
                            "description": "One sentence: why should a senior FA industry professional read this?",
                        },
                    },
                },
            },
        },
    },
}


def analyze_content(articles: list, query: str, themes: List[str]) -> Dict:
    lines = [
        f"Research query: {query}",
        f"Active themes: {', '.join(themes)}",
        f"Total articles: {len(articles)}",
        "",
    ]
    for i, a in enumerate(articles[:50], 1):
        lines.append(f"[{i}] [{a.get('theme', '').upper()}] {a.get('source', '')}")
        lines.append(f"Title: {a.get('title', '')}")
        if a.get("published"):
            lines.append(f"Date: {a['published']}")
        if a.get("summary"):
            lines.append(f"Summary: {a['summary']}")
        lines.append("")

    response = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        system=_SYSTEM_PROMPT,
        tools=[_TOOL],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": "\n".join(lines)}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "save_analysis":
            return block.input

    return {
        "overall_sentiment": "neutral", "sentiment_score": 0,
        "executive_summary": "Analysis unavailable.",
        "theme_analysis": [], "companies_and_products": [],
        "benchmark_data": [],
        "hiring_signal": {"trend": "unknown", "notes": ""},
        "top_articles": [],
    }
