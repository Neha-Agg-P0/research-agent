"""
Connector abstraction layer.

Each connector:
  - Returns ConnectorResult (never raises)
  - Classifies failures into ErrorType (not raw exceptions)
  - Tracks circuit breaker state in process memory
  - Supports ETag conditional requests for RSS (reduces bandwidth)
  - Only retries RETRYABLE errors (timeout, rate-limit, 5xx)
"""

import asyncio
import re
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import httpx


# ─── Error taxonomy ───────────────────────────────────────────────────────────

class ErrorType(str, Enum):
    AUTH_ERROR         = "AUTH_ERROR"
    RATE_LIMITED       = "RATE_LIMITED"
    PERMISSION_DENIED  = "PERMISSION_DENIED"
    NOT_FOUND          = "NOT_FOUND"
    UPSTREAM_FAILURE   = "TEMPORARY_UPSTREAM_FAILURE"
    INVALID_RESPONSE   = "INVALID_RESPONSE"
    TIMEOUT            = "TIMEOUT"
    UNSUPPORTED_SOURCE = "UNSUPPORTED_SOURCE"


RETRYABLE = {ErrorType.TIMEOUT, ErrorType.RATE_LIMITED, ErrorType.UPSTREAM_FAILURE}


# ─── Result type ─────────────────────────────────────────────────────────────

@dataclass
class ConnectorResult:
    source_id:  str
    source_name: str
    theme:      str
    articles:   List[Dict]          = field(default_factory=list)
    success:    bool                = True
    error_type: Optional[ErrorType] = None
    error_msg:  str                 = ""


# ─── Circuit breaker (in-process — survives warm invocations) ─────────────────

_circuit: Dict[str, dict] = {}
_OPEN_AFTER   = 3    # failures before opening
_RESET_AFTER  = 600  # seconds before allowing one probe


def _circuit_open(source_id: str) -> bool:
    s = _circuit.get(source_id)
    if not s:
        return False
    if s["open"] and (time.monotonic() - s["ts"]) > _RESET_AFTER:
        s["open"] = False
        s["n"] = 0
    return s.get("open", False)


def _fail(source_id: str, count: int = 1):
    s = _circuit.setdefault(source_id, {"n": 0, "open": False, "ts": 0.0})
    s["n"] += count
    s["ts"] = time.monotonic()
    if s["n"] >= _OPEN_AFTER:
        s["open"] = True


def _ok(source_id: str):
    _circuit.pop(source_id, None)


# ─── ETag + content cache (in-process) ───────────────────────────────────────

_etags:    Dict[str, str]        = {}  # url → ETag value
_cached:   Dict[str, List[Dict]] = {}  # url → last-good articles


# ─── Shared helpers ───────────────────────────────────────────────────────────

UA = "FAResearchAgent/1.0"


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def _classify_http(exc: Exception, status: int = 0) -> ErrorType:
    if isinstance(exc, httpx.TimeoutException):
        return ErrorType.TIMEOUT
    if status in (401, 403):
        return ErrorType.PERMISSION_DENIED
    if status == 429:
        return ErrorType.RATE_LIMITED
    if status == 404:
        return ErrorType.NOT_FOUND
    if status >= 500:
        return ErrorType.UPSTREAM_FAILURE
    if isinstance(exc, ET.ParseError):
        return ErrorType.INVALID_RESPONSE
    return ErrorType.UPSTREAM_FAILURE


def _parse_rss(xml_text: str, source_name: str, theme: str) -> List[Dict]:
    items: List[Dict] = []
    clean = re.sub(r'xmlns[^=]*="[^"]*"', "", xml_text)
    root  = ET.fromstring(clean)          # raises ET.ParseError on bad XML
    for item in root.findall(".//item")[:8]:
        title = _strip_tags(item.findtext("title", ""))
        link  = (item.findtext("link", "") or "").strip()
        desc  = _strip_tags(item.findtext("description", ""))[:500]
        pub   = item.findtext("pubDate", "")
        if title and link:
            items.append({
                "title": title, "source": source_name,
                "url": link, "published": pub,
                "summary": desc, "theme": theme,
            })
    return items


async def _retry(fn, source_id: str, source_name: str, theme: str,
                 max_retries: int = 1) -> ConnectorResult:
    """Retry only RETRYABLE errors. Exponential backoff + jitter."""
    backoffs = [1.0, 3.0, 8.0]
    last: Optional[ConnectorResult] = None
    for attempt in range(max_retries + 1):
        last = await fn()
        if last.success or last.error_type not in RETRYABLE:
            return last
        if attempt < max_retries:
            delay = backoffs[min(attempt, len(backoffs) - 1)] + random.uniform(0, 0.3)
            await asyncio.sleep(delay)
    return last  # type: ignore[return-value]


# ─── RSS connector ────────────────────────────────────────────────────────────

async def fetch_rss(
    client: httpx.AsyncClient,
    source_id: str,
    source_name: str,
    url: str,
    theme: str,
) -> ConnectorResult:
    if _circuit_open(source_id):
        cached = _cached.get(url, [])
        return ConnectorResult(
            source_id, source_name, theme,
            articles=cached,
            success=bool(cached),
            error_type=ErrorType.UNSUPPORTED_SOURCE,
            error_msg="circuit open — serving stale cache" if cached else "circuit open — no cache",
        )

    headers: Dict[str, str] = {"User-Agent": UA}
    if url in _etags:
        headers["If-None-Match"] = _etags[url]

    async def _attempt() -> ConnectorResult:
        try:
            r = await client.get(url, headers=headers, timeout=6.0)

            if r.status_code == 304:
                return ConnectorResult(source_id, source_name, theme,
                                       articles=_cached.get(url, []))

            r.raise_for_status()

            if etag := r.headers.get("etag"):
                _etags[url] = etag

            articles = _parse_rss(r.text, source_name, theme)
            _cached[url] = articles
            _ok(source_id)
            return ConnectorResult(source_id, source_name, theme, articles=articles)

        except ET.ParseError as e:
            _fail(source_id)
            return ConnectorResult(source_id, source_name, theme, success=False,
                                   error_type=ErrorType.INVALID_RESPONSE, error_msg=str(e))
        except httpx.TimeoutException as e:
            _fail(source_id)
            return ConnectorResult(source_id, source_name, theme, success=False,
                                   error_type=ErrorType.TIMEOUT, error_msg=str(e))
        except httpx.HTTPStatusError as e:
            err = _classify_http(e, e.response.status_code)
            _fail(source_id)
            return ConnectorResult(source_id, source_name, theme, success=False,
                                   error_type=err, error_msg=str(e))
        except Exception as e:
            _fail(source_id)
            return ConnectorResult(source_id, source_name, theme, success=False,
                                   error_type=ErrorType.UPSTREAM_FAILURE, error_msg=str(e))

    return await _retry(_attempt, source_id, source_name, theme)


# ─── Google News connector ────────────────────────────────────────────────────

async def fetch_google_news(
    client: httpx.AsyncClient,
    source_id: str,
    query: str,
    theme: str,
) -> ConnectorResult:
    if _circuit_open(source_id):
        return ConnectorResult(source_id, "Google News", theme, success=False,
                               error_type=ErrorType.UNSUPPORTED_SOURCE, error_msg="circuit open")

    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"

    async def _attempt() -> ConnectorResult:
        try:
            r = await client.get(url, headers={"User-Agent": UA}, timeout=6.0)
            r.raise_for_status()
            articles = _parse_rss(r.text, "Google News", theme)
            # Promote real publisher name from <source> tag
            try:
                root = ET.fromstring(re.sub(r'xmlns[^=]*="[^"]*"', "", r.text))
                for i, item in enumerate(root.findall(".//item")[:8]):
                    if i < len(articles) and (src := item.findtext("source", "")):
                        articles[i]["source"] = src
            except Exception:
                pass
            _ok(source_id)
            return ConnectorResult(source_id, "Google News", theme, articles=articles)
        except httpx.TimeoutException as e:
            _fail(source_id)
            return ConnectorResult(source_id, "Google News", theme, success=False,
                                   error_type=ErrorType.TIMEOUT, error_msg=str(e))
        except httpx.HTTPStatusError as e:
            err = _classify_http(e, e.response.status_code)
            _fail(source_id)
            return ConnectorResult(source_id, "Google News", theme, success=False,
                                   error_type=err, error_msg=str(e))
        except Exception as e:
            _fail(source_id)
            return ConnectorResult(source_id, "Google News", theme, success=False,
                                   error_type=ErrorType.UPSTREAM_FAILURE, error_msg=str(e))

    return await _retry(_attempt, source_id, "Google News", theme)


# ─── Page scrape connector ────────────────────────────────────────────────────

async def fetch_page(
    client: httpx.AsyncClient,
    source_id: str,
    source_name: str,
    url: str,
    theme: str,
    title: str,
) -> ConnectorResult:
    if _circuit_open(source_id):
        cached = _cached.get(url, [])
        return ConnectorResult(source_id, source_name, theme,
                               articles=cached, success=bool(cached),
                               error_type=ErrorType.UNSUPPORTED_SOURCE,
                               error_msg="circuit open")

    async def _attempt() -> ConnectorResult:
        try:
            r = await client.get(url, headers={"User-Agent": UA}, timeout=8.0)
            r.raise_for_status()
            text = re.sub(r"\s+", " ", _strip_tags(r.text))[:3000]
            articles = [{"title": title, "source": source_name, "url": url,
                         "published": "", "summary": text, "theme": theme}]
            _cached[url] = articles
            _ok(source_id)
            return ConnectorResult(source_id, source_name, theme, articles=articles)
        except httpx.TimeoutException as e:
            _fail(source_id)
            return ConnectorResult(source_id, source_name, theme, success=False,
                                   error_type=ErrorType.TIMEOUT, error_msg=str(e))
        except httpx.HTTPStatusError as e:
            err = _classify_http(e, e.response.status_code)
            _fail(source_id)
            return ConnectorResult(source_id, source_name, theme, success=False,
                                   error_type=err, error_msg=str(e))
        except Exception as e:
            _fail(source_id)
            return ConnectorResult(source_id, source_name, theme, success=False,
                                   error_type=ErrorType.UPSTREAM_FAILURE, error_msg=str(e))

    return await _retry(_attempt, source_id, source_name, theme)


# ─── Indeed jobs connector ────────────────────────────────────────────────────

async def fetch_indeed(
    client: httpx.AsyncClient,
    source_id: str,
    query: str,
) -> ConnectorResult:
    """
    Indeed blocks cloud IPs with PERMISSION_DENIED — non-retryable.
    Three fast failures force circuit open so we stop wasting time.
    """
    if _circuit_open(source_id):
        return ConnectorResult(source_id, "Indeed Jobs", "talent", success=False,
                               error_type=ErrorType.UNSUPPORTED_SOURCE, error_msg="circuit open")

    url = (f"https://www.indeed.com/rss"
           f"?q={quote_plus(query + ' financial advisor')}&l=United+States&sort=date")

    try:
        r = await client.get(url, headers={"User-Agent": UA}, timeout=6.0)
        r.raise_for_status()
        articles = _parse_rss(r.text, "Indeed Jobs", "talent")
        _ok(source_id)
        return ConnectorResult(source_id, "Indeed Jobs", "talent", articles=articles)
    except httpx.HTTPStatusError as e:
        err = _classify_http(e, e.response.status_code)
        if err == ErrorType.PERMISSION_DENIED:
            _fail(source_id, count=_OPEN_AFTER)  # fast-trip circuit
        else:
            _fail(source_id)
        return ConnectorResult(source_id, "Indeed Jobs", "talent", success=False,
                               error_type=err, error_msg=str(e))
    except Exception as e:
        _fail(source_id)
        return ConnectorResult(source_id, "Indeed Jobs", "talent", success=False,
                               error_type=ErrorType.UPSTREAM_FAILURE, error_msg=str(e))
