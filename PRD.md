# FA Research Agent — Product Requirements Document

**Version:** 1.0  
**Status:** Working prototype — active development  
**Last updated:** April 2026

---

## 1. Product Vision

A strategy intelligence tool that compresses 3 hours of external research into a 3-minute brief — helping internal teams at advisor-serving firms structure their thinking on new programs, products, and strategies.

The agent doesn't just aggregate news. It answers a specific question with a direct, opinionated response backed by cited sources, segmented by advisor type, and flagged for competitive implications.

---

## 2. Primary Users

**Who:** Strategy, Growth, Product, and Advisor-Facing Program Leaders at firms that serve financial advisors.

**Their firms:** Broker-dealers, custodians, TAMPs, and RIA platforms — organizations like LPL Financial, Commonwealth Financial Network, Raymond James, Osaic, Schwab Advisor Services, Fidelity Institutional, Pershing.

**They are not:** Financial advisors themselves. The user is one step removed — they build programs and products FOR advisors.

### Primary Personas

**The Program Builder**
VP or Director of Advisor Programs. Running a query like: *"What growth coaching programs are competitors offering, and what segment gaps exist?"* Output feeds a business case for a new program launch.

**The Product Strategist**
Head of Product or Chief Strategy Officer. Running queries like: *"What AI tools are advisors adopting fastest, and where is the white space for our platform?"* Output feeds a product roadmap decision.

**The Competitive Intelligence Analyst**
Growth or strategy team member doing weekly market scanning. Running: *"What has LPL, Commonwealth, or Farther announced in the last 30 days?"* Output feeds a competitive brief.

---

## 3. Problem Statement

Internal teams at advisor-serving firms need external market intelligence to make good decisions about what to build next. Today this research is:

- **Manual and slow** — analyst spends hours searching industry publications, firm websites, conference coverage
- **Fragmented** — Kitces, InvestmentNews, ThinkAdvisor, Schwab studies, LinkedIn announcements all need to be checked separately
- **Generic** — Google surfaces consumer content and generic business articles alongside FA-specific signal
- **Unsegmented** — findings aren't broken down by advisor type (solo vs ensemble vs enterprise), so broad claims miss the nuance that matters for program design

The result: strategy decisions are made with incomplete external context, or research takes so long it doesn't get done.

---

## 4. Goals

### Must achieve
- Answer a specific FA industry question with a direct, opinionated response — not a list of links
- Cite every claim with a clickable source link
- Surface segment breakdown (solo / lead / ensemble / enterprise / RIA) when relevant
- Flag competitor moves by name
- Identify white space: what advisors need that no one offers, and what competitors don't provide that we could

### Should achieve
- Surface benchmark data (Cerulli, Schwab RIA Benchmarking, Fidelity, InvestmentNews) prominently — these are authoritative
- Filter out generic business content before it reaches Claude
- Format output as a one-pager brief usable in a strategy meeting

### Out of scope (v1)
- Real-time alerts / notifications
- CRM or workflow integration
- User accounts / saved searches
- Advisor-facing version of the tool

---

## 5. The Six Strategic Lenses

These are the query categories the tool must be excellent at. They replace generic themes.

### Lens 1 — Data & Insights
*"What data products and analytics do advisors need? What exists vs what's white space?"*

Outputs: competitive map of existing data products, segment-specific gaps, white space flags, source links.

### Lens 2 — Growth & Benchmarks
*"What growth programs and benchmark studies exist? What are competitors offering?"*

Outputs: program inventory by competitor, benchmark study highlights (Cerulli, Schwab, etc.), gap analysis by segment.

### Lens 3 — Technology & AI
*"What tools and AI use cases are advisors adopting? What are BDs and custodians building or partnering on?"*

Outputs: tool landscape by Kitces category, adoption signals, competitor technology moves, emerging startups.

### Lens 4 — Operations & Efficiency
*"What operational solutions are advisors using? What's back-office vs front-office?"*

Outputs: efficiency tool landscape, segment-specific pain points (solo efficiency ≠ enterprise efficiency), competitor operational support programs.

### Lens 5 — HNW Capabilities
*"What capabilities are being built for advisors serving high-net-worth clients?"*

Outputs: alternative investment access, tax/estate tools, trust services, custodian HNW programs, competitor HNW plays.

### Lens 6 — Investor Strategy
*"What are end-clients demanding from their advisors right now?"*

Outputs: consumer demand signals, retirement income trends, ESG/values-based investing, digital advice expectations, generational wealth transfer.

---

## 6. Segment Framework

Every output should be tagged to relevant segments. The same question has a different answer for a solo advisor vs an enterprise firm.

| Segment | AUM range | Key signal |
|---------|-----------|------------|
| Solo | <$50M | Efficiency, turnkey solutions, time |
| Lead Advisor | $50–250M | Growth, client acquisition, team |
| Ensemble | $250M–$2B | Practice management, succession, shared infra |
| Enterprise | $2B+ | Technology, M&A, talent, institutional |
| RIA | All sizes | Independence, custodian services, compliance |

---

## 7. Competitive Intelligence Requirements

### Tier 1 — Always flag
LPL Financial, Commonwealth, Raymond James, Osaic, Schwab Advisor Services, Fidelity Institutional, Pershing

### Tier 2 — Flag when active
Farther, Altruist, Carson Group, Dynasty Financial Partners, CI Financial, Focus Financial, Hightower, Cetera

### What to flag
- New program or product announcements
- Technology partnerships or acquisitions
- Advisor recruiting or retention moves
- Study or benchmark publications
- Leadership changes with strategic implications

---

## 8. White Space Definition

White space = either or both of:
- **(A) Unmet advisor demand** — advisors are asking for something that no one currently offers well
- **(B) Competitive gap** — something a firm could offer that competitors don't

Signal sources for unmet demand: advisor councils, conference content (Schwab IMPACT, FPA, XYPN FinCon), survey data, community forums (XYPN, FPA), Kitces reader surveys.

---

## 9. Output Format — One-Pager Brief

The output for every query should be structured as a brief a leader could bring to a strategy meeting:

```
DIRECT ANSWER
3-6 numbered claims that directly answer the query.
Each claim: one sentence, specific, backed by [Source] citation link.

SEGMENT BREAKDOWN  
How the answer differs by solo / lead / ensemble / enterprise / RIA.
Only include segments where the answer is meaningfully different.

COMPETITOR MOVES
Named firms doing something relevant. One line each. Linked source.

WHITE SPACE
What advisors need that isn't being met.
What no competitor currently offers well.

BENCHMARK DATA
Any Cerulli, Schwab, Fidelity, or other authoritative data points.
Quoted specifically with source.

SOURCE ARTICLES
6-8 clickable links with one-sentence relevance note each.
```

---

## 10. Source Architecture

### Tier 1 — Always query (durable, open)
Kitces, ThinkAdvisor, InvestmentNews, RIABiz, WealthManagement.com, Financial Planning magazine, FA Magazine, TechCrunch Fintech, Tearsheet, XYPN, FPA, Google News (FA-filtered)

### Tier 2 — Query when available (conditional)
Kitces Technology Map (page scrape), Indeed Jobs (talent signal), Reddit FA communities (when credentials available)

### Relevance gate
Before passing to Claude: filter out articles with no FA-specific signal. Discard generic business/management content, consumer personal finance, and stock market commentary.

---

## 11. Success Metrics

- Query to brief in under 60 seconds
- Every claim in the Direct Answer has a working source link
- Segment breakdown present on queries where it's relevant
- Competitor moves flagged by firm name, not generically
- Zero generic business articles (MIT Sloan, HBR) appearing in citations

---

## 12. Roadmap

### Now (v1 — working prototype)
- 6 strategic lenses as query themes
- Direct answer with inline citations
- One-pager brief output format
- Relevance pre-filter
- context.md domain grounding

### Next (v2)
- Segment filter in UI — run query specifically for "ensemble" or "RIA" segment
- Competitor filter — "show me only moves by LPL and Commonwealth"
- Saved queries / weekly brief digest
- White space explicit flag in output ("No major BD currently offers this")

### Later (v3)
- Structured competitive database — track competitor programs over time
- Alert when a watched firm announces something
- Export to PDF / slide deck format
- Multi-user with saved context per firm/team
