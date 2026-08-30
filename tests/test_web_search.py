"""``web_search`` keyless DuckDuckGo backend tests.

The old Perplexity backend returned ``success: False`` with "not configured"
unless PERPLEXITY_API_KEY was set, so web research was dead in every scan that
lacked a key. The DuckDuckGo backend needs no key; these tests pin that contract
and the DDG redirect decoding, offline via monkeypatched HTTP.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Self

import requests

from strix.tools.web_search import tool as ws_module
from strix.tools.web_search.tool import _decode_ddg_href, _do_search, _ResultParser


if TYPE_CHECKING:
    import types

    import pytest


class _FakeResp:
    """requests-styled response with a context-manager body."""

    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: types.TracebackType | None,
    ) -> None:
        return None


_DDG_PAGE = """<html><body>
<div class="result">
  <a rel="nofollow" class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fcve%3Fid%3D1&amp;rut=abc">
     Example CVE page</a>
  <a class="result__snippet">This covers CVE-2024-0001 details.</a>
</div>
<div class="result">
  <a rel="nofollow" class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fsecond.example%2F">Second result</a>
  <a class="result__snippet">Second snippet text.</a>
</div>
</body></html>"""


def _fake_post(*_args: Any, **_kwargs: Any) -> _FakeResp:
    return _FakeResp(_DDG_PAGE)


def _fake_get(*_args: Any, **_kwargs: Any) -> _FakeResp:
    return _FakeResp("<html>noise</html>")


def test_decode_ddg_href_preserves_target_query_string() -> None:
    href = "//duckduckgo.com/l/?uddg=" + "https%3A%2F%2Fexample.com%2Fx%3Fa%3D1%26b%3D2&rut=z"
    assert _decode_ddg_href(href) == "https://example.com/x?a=1&b=2"


def test_decode_ddg_href_passthrough_non_redirect() -> None:
    assert _decode_ddg_href("https://direct.example/path") == "https://direct.example/path"


def test_result_parser_extracts_title_href_snippet() -> None:
    parser = _ResultParser()
    parser.feed(_DDG_PAGE)
    assert len(parser.results) == 2
    first = parser.results[0]
    assert first["title"].strip() == "Example CVE page"
    assert "uddg=" in first["href"]
    assert "CVE-2024-0001" in first["snippet"]


def test_do_search_works_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The keyless contract: no key is consulted, the search goes straight to
    HTTP (the old backend dead-ended because it required PERPLEXITY_API_KEY)."""
    monkeypatch.setattr(requests, "post", _fake_post)
    monkeypatch.setattr(requests, "get", _fake_get)

    result = _do_search("example query")
    assert result["success"] is True
    content = result["content"]
    assert "https://example.com/cve?id=1" in content  # decoded target, query preserved
    assert "CVE-2024-0001" in content
    assert "Excerpt:" in content  # excerpt fetched from the top hit


def test_do_search_empty_query() -> None:
    result = _do_search("   ")
    assert result["success"] is False
    assert "cannot be empty" in result["error"]


def test_web_search_tool_is_keyless_ddg() -> None:
    """The registered tool is the keyless DuckDuckGo backend, not Perplexity."""
    tool = ws_module.web_search
    assert tool.name == "web_search"
    assert "DuckDuckGo" in tool.description
    assert "No API key is required" in tool.description


def test_do_search_result_is_json_serializable() -> None:
    """A success dict round-trips through the tool's JSON serialization path."""
    result = {"success": True, "query": "q", "content": "lines"}
    payload = json.dumps(result, ensure_ascii=False, default=str)
    decoded = json.loads(payload)
    assert {"success", "query", "content"}.issubset(decoded)
