"""Tests for src.tools.web_search — web_search, web_fetch, Bing HTML parsing."""

from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from src.tools.web_search import web_search, web_fetch, _parse_bing_html


# LangChain @tool wraps functions — unwrap with .func
def _call(t, /, *args, **kwargs):
    return t.func(*args, **kwargs)


# ── Shared test HTML samples ─────────────────────────────────────────

BING_HTML_SAMPLE = """
<html><body>
<li class="b_algo">
  <a href="https://example.com/page1">Example Title 1</a>
  <p>This is a snippet for result 1.</p>
</li>
<li class="b_algo">
  <a href="https://example.com/page2">Example Title 2</a>
  <p>Snippet for result 2.</p>
</li>
</body></html>
"""

BING_HTML_NO_RESULTS = "<html><body>No results found</body></html>"


class TestParseBingHtml:
    """Verify _parse_bing_html extracts results correctly."""

    def test_parse_standard_results(self):
        results = _parse_bing_html(BING_HTML_SAMPLE, max_results=5)
        assert len(results) == 2
        assert results[0]["title"] == "Example Title 1"
        assert results[0]["url"] == "https://example.com/page1"
        assert results[0]["snippet"] == "This is a snippet for result 1."
        assert results[1]["title"] == "Example Title 2"

    def test_parse_deduplicates(self):
        html = BING_HTML_SAMPLE + BING_HTML_SAMPLE  # duplicate content
        results = _parse_bing_html(html, max_results=5)
        assert len(results) == 2  # deduplicated

    def test_parse_no_results(self):
        results = _parse_bing_html(BING_HTML_NO_RESULTS, max_results=5)
        assert results == []

    def test_parse_respects_max_results(self):
        # Create 5 results
        items = ""
        for i in range(5):
            items += f"""
<li class="b_algo">
  <a href="https://example.com/{i}">Title {i}</a>
  <p>Snippet {i}.</p>
</li>"""
        html = f"<html><body>{items}</body></html>"
        results = _parse_bing_html(html, max_results=3)
        assert len(results) == 3


class TestWebSearch:
    """Verify web_search tool (with mocked requests)."""

    @patch("src.tools.web_search.requests.get")
    def test_search_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = BING_HTML_SAMPLE
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = _call(web_search, "test query")
        assert "搜索结果" in result
        assert "Example Title 1" in result
        assert "example.com" in result

    @patch("src.tools.web_search.requests.get")
    def test_search_no_results(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = BING_HTML_NO_RESULTS
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = _call(web_search, "nonexistent")
        assert "未找到" in result

    @patch("src.tools.web_search.requests.get")
    def test_search_timeout(self, mock_get):
        mock_get.side_effect = __import__("requests").exceptions.Timeout("timeout")
        result = _call(web_search, "test")
        assert "超时" in result

    @patch("src.tools.web_search.requests.get")
    def test_search_connection_error(self, mock_get):
        mock_get.side_effect = __import__("requests").exceptions.ConnectionError("no connection")
        result = _call(web_search, "test")
        assert "连接失败" in result or "不可达" in result


class TestWebFetch:
    """Verify web_fetch tool (with mocked requests)."""

    @patch("src.tools.web_search.requests.get")
    def test_fetch_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<html><head><title>Test Page</title></head><body><p>Hello world</p></body></html>"
        mock_resp.text = "<html><body><p>Hello world</p></body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = _call(web_fetch, "https://example.com")
        assert "Test Page" in result
        assert "Hello world" in result

    @patch("src.tools.web_search.requests.get")
    def test_fetch_json(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"key": "value"}'
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = _call(web_fetch, "https://api.example.com/data")
        assert "json" in result
        assert '"key": "value"' in result or "key" in result

    def test_fetch_invalid_url(self):
        result = _call(web_fetch, "ftp://example.com")
        assert "不支持" in result

    def test_fetch_invalid_url_no_netloc(self):
        result = _call(web_fetch, "not-a-url")
        # urlparse("not-a-url") has scheme="" and netloc="" so the scheme check triggers
        assert "不支持" in result or "无效" in result

    @patch("src.tools.web_search.requests.get")
    def test_fetch_timeout(self, mock_get):
        mock_get.side_effect = __import__("requests").exceptions.Timeout("timeout")
        result = _call(web_fetch, "https://example.com")
        assert "超时" in result

    @patch("src.tools.web_search.requests.get")
    def test_fetch_large_content(self, mock_get):
        """Content exceeding MAX_FETCH_SIZE should be rejected."""
        mock_resp = MagicMock()
        mock_resp.content = b"x" * 600_000  # > 500KB
        mock_resp.headers = {}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = _call(web_fetch, "https://example.com/large")
        assert "过大" in result or "超过安全限制" in result
