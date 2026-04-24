import os
import re
import anthropic
from typing import Dict, List

_FA_SIGNALS = {
    "financial advisor", "financial adviser", "wealth management", "registered investment",
    "broker-dealer", "broker dealer", "wirehouse", "independent advisor", "advisory firm",
    "ria ", " ria,", "(ria)", "fee-only", "fiduciary", "custodian", "tamp",
    "practice management", "advisor technology", "wealthtech", "lpl", "commonwealth",
    "raymond james", "osaic", "schwab advisor", "fidelity institutional", "pershing",
    "farther", "altruist", "carson group", "dynasty financial", "focus financial",
    "hightower", "cetera", "aum", "assets under management", "cfp", "cerulli",
    "ensemble", "breakaway", "succession planning", "managed accounts",
}

SEGMENT_CONTEXT = {
    "solo":       "Solo advisors (<$50M AUM): single advisor, minimal staff, focused on efficiency and turnkey solutions",
    "lead":       "Lead Advisor practices ($50–250M AUM): primary advisor + 1-2 support staff, focused on growth and client acquisition",
    "ensemble":   "Ensemble firms ($250M–$2B AUM): multi-partner advisory practices focused on succession, practice management, and shared infrastructure",
    "enterprise": "Enterprise firms ($2B+ AUM): large multi-advisor organizations focused on technology platforms, M&A, and institutional capabilities",
}


def _is_fa_relevant(article: dict) -> bool:
    text = (article.get("title", "") + " " + article.get("summary", "")).lower()
    fa_sources = {
        "kitces", "thinkadvisor", "investmentnews", "riabiz", "wealthmanagement",
        "financial planning", "fa magazine", "xypn", "fpa", "tearsheet",
        "indeed", "techcrunch"
    }
    source = article.get("source", "").lower()
    if any(s in source for s in fa_sources):
        return True
    return any(sig in text for sig in _FA_SIGNALS)


def _load_context() -> str:
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "context.md"),
        os.path.join(os.getcwd(), "context.md"),
        "/var/task/context.md",
        "context.md",
    ]
    for path in candidates:
        try:
            with open(path, "r") as f:
                return f.read()
        except Exception:
            continue
    return ""


def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")
    return anthropic.Anthropic(api_key=api_key)


_SYSTEM_PROMPT_BASE = """You are a senior financial services industry analyst. You give direct, confident, opinionated answers — not summaries of what sources say.

Your job:
1. Answer the query directly. Take a position. Make concrete claims.
2. Back every claim with specific article indices from the provided content.
3. Write as if presenting conclusions to a managing partner, not writing a report.

You cover: wirehouses (Merrill Lynch, Morgan Stanley, Wells Fargo Advisors, UBS), independent RIAs, broker-dealers, and advisor-facing technology and growth programs.

Six analysis lenses (only use those relevant to the query):
- DATA & INSIGHTS: benchmark studies, data products, analytics tools available to advisors; white space in data/research offerings vs competitive landscape
- GROWTH & BENCHMARKS: practice growth programs, coaching resources, benchmark studies (Cerulli, Schwab RIA Benchmarking, Fidelity, InvestmentNews, FA Magazine) — flag every competitor program by name
- TECHNOLOGY & AI: advisor tech landscape by Kitces category (CRM, planning, portfolio, compliance, AI meeting notes); adoption signals; BD/custodian technology partnerships; emerging startups (Zocks AI, Jump AI, Finny, etc.)
- OPERATIONS & EFFICIENCY: back-office solutions, workflow automation, compliance monitoring, rebalancing, billing, performance reporting — solo efficiency ≠ enterprise efficiency, flag the difference
- HNW CAPABILITIES: alternatives access (PE, hedge funds, real assets), tax/estate planning, trust services, family office, lending — for advisors serving HNW/UHNW clients; custodian and TAMP HNW programs
- INVESTOR STRATEGY: end-client demand signals — retirement income, ESG/values-based investing, generational wealth transfer, digital advice expectations

Hard rules:
- Every claim in direct_answer must cite article indices. No claim without evidence.
- Be specific: name firms, cite numbers, reference dates when present.
- Prefer concrete over hedged. "AUM growth rate is the #1 tracked KPI" beats "some advisors track AUM."
- If benchmark data exists (Cerulli, Schwab, etc.), surface it — it is authoritative.
- Tag findings to advisor segments (solo/lead/ensemble/enterprise) wherever the answer differs by segment.
- Flag competitor moves by firm name. Generic references ("a major BD") are not acceptable.
- Identify white space explicitly: "No major BD currently offers X" or "Advisors report needing Y but solutions are limited."
- theme_analysis: headline only + max 3 bullet insights per lens. No prose paragraphs.

{segment_instruction}

---

DOMAIN CONTEXT:
{context}"""


_TOOL = {
    "name": "save_analysis",
    "description": "Save structured FA industry intelligence with direct cited answers",
    "input_schema": {
        "type": "object",
        "required": [
            "overall_sentiment", "sentiment_score",
            "direct_answer", "theme_analysis",
            "companies_and_products", "benchmark_data",
            "hiring_signal", "top_articles",
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
            "direct_answer": {
                "type": "array",
                "description": "3-7 direct, opinionated answers to the query. Each claim is a confident statement backed by specific article indices.",
                "items": {
                    "type": "object",
                    "required": ["claim", "evidence_indices"],
                    "properties": {
                        "claim": {"type": "string"},
                        "evidence_indices": {"type": "array", "items": {"type": "integer"}},
                    },
                },
            },
            "theme_analysis": {
                "type": "array",
                "description": "One compact entry per relevant lens",
                "items": {
                    "type": "object",
                    "required": ["theme", "headline", "insights", "sentiment"],
                    "properties": {
                        "theme": {
                            "type": "string",
                            "enum": ["data", "growth", "technology", "operations", "hnw", "investor"],
                        },
                        "headline": {"type": "string"},
                        "insights": {"type": "array", "items": {"type": "string"}},
                        "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral", "mixed"]},
                    },
                },
            },
            "companies_and_products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "type", "context", "sentiment"],
                    "properties": {
                        "name":             {"type": "string"},
                        "type":             {"type": "string"},
                        "product_category": {"type": "string"},
                        "context":          {"type": "string"},
                        "sentiment":        {"type": "string", "enum": ["positive", "negative", "neutral"]},
                    },
                },
            },
            "benchmark_data": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["source", "stat", "significance"],
                    "properties": {
                        "source":       {"type": "string"},
                        "stat":         {"type": "string"},
                        "significance": {"type": "string"},
                    },
                },
            },
            "hiring_signal": {
                "type": "object",
                "required": ["trend", "notes"],
                "properties": {
                    "trend":     {"type": "string", "enum": ["growing", "stable", "contracting", "unknown"]},
                    "hot_roles": {"type": "array", "items": {"type": "string"}},
                    "notes":     {"type": "string"},
                },
            },
            "top_articles": {
                "type": "array",
                "description": "6-8 most relevant articles for this specific query",
                "items": {
                    "type": "object",
                    "required": ["article_index", "title", "source", "theme", "why_it_matters"],
                    "properties": {
                        "article_index":  {"type": "integer"},
                        "title":          {"type": "string"},
                        "source":         {"type": "string"},
                        "theme":          {"type": "string"},
                        "why_it_matters": {"type": "string"},
                    },
                },
            },
        },
    },
}


def analyze_content(articles: list, query: str, lenses: List[str], segment: str = "all") -> Dict:
    relevant = [a for a in articles if _is_fa_relevant(a)]
    filtered_count = len(articles) - len(relevant)
    if not relevant:
        relevant = articles

    context = _load_context()

    segment_instruction = ""
    if segment != "all" and segment in SEGMENT_CONTEXT:
        segment_instruction = (
            f"SEGMENT FOCUS: {SEGMENT_CONTEXT[segment]}. "
            "Prioritize findings relevant to this segment. "
            "Explicitly flag when findings differ meaningfully across segments."
        )

    system_prompt = _SYSTEM_PROMPT_BASE.format(
        segment_instruction=segment_instruction,
        context=context if context else "(no domain context loaded)",
    )

    lines = [
        f"Research query: {query}",
        f"Active lenses: {', '.join(lenses)}",
        f"Segment focus: {segment}",
        f"Total articles: {len(relevant)} (filtered out {filtered_count} non-FA articles)",
        "",
    ]
    for i, a in enumerate(relevant[:50], 1):
        lines.append(f"[{i}] [{a.get('theme', '').upper()}] {a.get('source', '')}")
        lines.append(f"Title: {a.get('title', '')}")
        if a.get("published"):
            lines.append(f"Date: {a['published']}")
        if a.get("summary"):
            lines.append(f"Summary: {a['summary']}")
        lines.append("")

    response = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=system_prompt,
        tools=[_TOOL],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": "\n".join(lines)}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "save_analysis":
            return block.input

    return {
        "overall_sentiment": "neutral", "sentiment_score": 0,
        "direct_answer": [],
        "theme_analysis": [], "companies_and_products": [],
        "benchmark_data": [],
        "hiring_signal": {"trend": "unknown", "notes": ""},
        "top_articles": [],
    }
