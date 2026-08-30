"""``web_search`` -- keyless DuckDuckGo-backed security-focused web search.

The tool keeps the same contract as the old Perplexity backend (a ``query`` in,
a JSON string with ``content`` out) but needs no API key and no third-party
vendor: it queries DuckDuckGo's HTML endpoint, parses the result links and
snippets, and fetches short excerpts from the top hits. No PERPLEXITY_API_KEY
is required, so the tool is live in every scan by default (previously it
returned "not configured" unless the operator set the key).
"""

from __future__ import annotations

import asyncio
import html as html_mod
import json
import logging
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urlparse, urlunsplit

import requests
from agents import RunContextWrapper, function_tool


logger = logging.getLogger(__name__)

_DDG_SEARCH_URL = "https://html.duckduckgo.com/html/"
_DDG_TIMEOUT = 20  # per-request; search + up to _DDG_FETCH_TOP result fetches
_DDG_FETCH_TOP = 3  # top-N links to fetch and excerpt
_DDG_EXCERPT_CHARS = 1500
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class _ResultParser(HTMLParser):
    """Collect DDG HTML result blocks: title + href for result__a anchors, and
    the following result__snippet text."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._cur: dict[str, str] | None = None
        self._in_title = False
        self._in_snippet = False
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        cls = dict(attrs).get("class", "") or ""
        classes = cls.split()
        if tag == "a" and "result__a" in classes:
            self._cur = {"href": dict(attrs).get("href") or "", "title": ""}
            self._in_title = True
            self._buf = []
        elif tag == "a" and "result__snippet" in classes:
            self._in_snippet = True
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_title and self._cur is not None:
            self._cur["title"] += data
        elif self._in_snippet:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title and self._cur is not None:
            title = html_mod.unescape(self._cur["title"]).strip()
            if title:
                self.results.append(self._cur)
            self._cur = None
            self._in_title = False
        elif tag == "a" and self._in_snippet:
            snippet = html_mod.unescape("".join(self._buf)).strip()
            if snippet and self.results:
                self.results[-1]["snippet"] = snippet
            self._in_snippet = False


def _decode_ddg_href(href: str) -> str:
    """DDG wraps result links in a redirect: //duckduckgo.com/l/?uddg=<url>. Pull
    the target URL out (unquoting only the uddg value so the target's own query
    string survives), or return the href as-is if it is not a redirect."""
    match = re.search(r"[?&]uddg=([^&]+)", href)
    if not match:
        return href
    return unquote(match.group(1))


def _strip_fragment(url: str) -> str:
    parts = urlparse(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _fetch_excerpt(url: str) -> str:
    """Fetch a result page and return a short plain-text excerpt. Best-effort:
    any failure returns an empty string so one dead link never kills the tool."""
    if not url.startswith(("http://", "https://")):
        return ""
    try:
        with requests.get(
            url, headers={"User-Agent": _UA}, timeout=_DDG_TIMEOUT
        ) as response:
            response.raise_for_status()
    except requests.RequestException:
        return ""
    text = response.text
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = text.replace("\ufeff", "")  # stray BOM / zero-width chars from pages
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_DDG_EXCERPT_CHARS]


def _do_search(query: str) -> dict[str, Any]:  # noqa: PLR0911 - each error class needs its own sanitized return
    if not query or not query.strip():
        return {"success": False, "error": "Query cannot be empty"}

    logger.info("web_search query (len=%d): %s", len(query), query[:120])

    try:
        with requests.post(
            _DDG_SEARCH_URL,
            data={"q": query},
            headers={"User-Agent": _UA},
            timeout=_DDG_TIMEOUT,
        ) as response:
            response.raise_for_status()
            page = response.text
    except requests.exceptions.Timeout:
        logger.warning("web_search timed out")
        return {
            "success": False,
            "error": "Web search timed out. Try again or shorten the query",
        }
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        logger.exception("web_search HTTP error status=%s", status)
        if status is not None and 400 <= status < 500:
            return {
                "success": False,
                "error": (
                    "Web search rejected the query. Refine it "
                    "(more specific, shorter, no unusual characters) and retry"
                ),
            }
        return {
            "success": False,
            "error": "Web search service is unavailable. Try again later",
        }
    except requests.exceptions.RequestException:
        logger.exception("web_search network error")
        return {
            "success": False,
            "error": "Web search network error. Try again later",
        }
    except Exception:
        logger.exception("web_search failed")
        return {
            "success": False,
            "error": "Web search failed unexpectedly",
        }

    parser = _ResultParser()
    try:
        parser.feed(page)
    except Exception:
        logger.exception("web_search response shape unexpected")
        return {
            "success": False,
            "error": "Web search returned an unexpected response. Try again",
        }

    if not parser.results:
        return {
            "success": True,
            "query": query,
            "content": f"No results found for: {query}",
        }

    return {
        "success": True,
        "query": query,
        "content": _build_results_content(query, parser.results),
    }


def _build_results_content(query: str, results: list[dict[str, str]]) -> str:
    """Render parsed DDG results into a numbered research text block, fetching a
    short excerpt from the top few links."""
    lines: list[str] = [f"Results for: {query}"]
    for i, result in enumerate(results, start=1):
        target = _strip_fragment(_decode_ddg_href(result.get("href", "")))
        lines.append(f"\n{i}. {result.get('title', '(no title)')}")
        if target:
            lines.append(f"   URL: {target}")
        if result.get("snippet"):
            lines.append(f"   Snippet: {result['snippet']}")
        if target and i <= _DDG_FETCH_TOP:
            excerpt = _fetch_excerpt(target)
            if excerpt:
                lines.append(f"   Excerpt: {excerpt}")
    return "\n".join(lines)


@function_tool(timeout=330)
async def web_search(ctx: RunContextWrapper, query: str) -> str:
    """Real-time web search via DuckDuckGo — your primary research tool.

    No API key is required; the tool is live in every scan.

    Use it liberally for anything that's not in your training data:

    - Current CVEs, advisories, and 0-days for a specific
      service/version (``OpenSSH 9.6 RCE``, ``Jenkins 2.401.3 auth
      bypass``).
    - Latest WAF / EDR bypass techniques (``Cloudflare WAF SQLi
      bypass 2025``, ``CrowdStrike Falcon evasion``).
    - Tool documentation, flag references, payload galleries.
    - Target reconnaissance / OSINT (company tech stack, leaked
      credentials, exposed assets).
    - Cloud-provider misconfiguration patterns
      (Azure/AWS/GCP-specific attack paths).
    - Bug-bounty writeups and security research papers.
    - Compliance frameworks and CWE/CVSS guidance.
    - Picking the right Python lib / Kali tool for a job (``best 2025
      lib for JWT alg-confusion``).
    - When stuck — looking up the exact error message, ``Access
      denied`` quirks, kernel-specific local-privesc exploits.

    Be specific: include version numbers, error messages, target
    technology, and the exact problem you're stuck on. The more context
    in the query, the more actionable the answer. Vague queries get
    generic answers.

    Returns the top results as a numbered list with title, URL, snippet,
    and a short excerpt fetched from the first few hits.

    **Good example queries** (each is a full sentence, names a
    version/product, and asks one concrete thing):

    - ``"Found OpenSSH 7.4 on port 22 — any known RCE or privesc for
      this exact version?"``
    - ``"Cloudflare WAF is blocking my sqlmap on a login form — what
      bypass techniques work in 2025?"``
    - ``"Target runs WordPress 5.8.3 + WooCommerce 6.1.1 — current
      RCE chains for this combo?"``
    - ``"Low-priv shell on Ubuntu 20.04 kernel 5.4.0-74-generic — what
      local privesc exploits hit this kernel?"``
    - ``"Compromised domain user on Windows Server 2019 AD — quietest
      paths to Domain Admin without tripping EDR?"``
    - ``"'Access denied' uploading a webshell to IIS 10.0 — alternate
      Windows IIS upload bypass techniques?"``
    - ``"Discovered Jenkins 2.401.3 on staging — current authn-bypass
      and RCE exploits for this version?"``
    - ``"Best 2025 Python lib for JWT algorithm-confusion + weak-secret
      cracking?"``

    Args:
        query: The search query — a full sentence with version numbers,
            target tech, and the specific question. Treat it like a
            ticket title for a senior security engineer.
    """
    result = await asyncio.to_thread(_do_search, query)
    return json.dumps(result, ensure_ascii=False, default=str)
