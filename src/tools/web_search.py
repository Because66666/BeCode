"""Web search and web page fetch tools for agents.

Provides two tools:
1. web_search  — search the web using Bing (free, no API key needed, HTML scraping).
2. web_fetch   — fetch a web page and extract its readable text content.

Both tools are wrapped as LangChain @tool decorators so they can be
registered directly into the agent's tool list.

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - web_search: 基于 Bing 搜索, HTML scraping,   ║
║    解析 li.b_algo 结果                           ║
║  - web_fetch: 基于 requests+BeautifulSoup 的     ║
║    网页内容提取                                   ║
║  - 注册在 src/tools/web_search.py 中             ║
║  - 工具返回值长度限制: 所有工具的返回值若超过     ║
║    MAX_TOOL_OUTPUT_LENGTH(=40000) 字符，会被强制   ║
║    替换为提示消息「命令返回长度超过10ktoken，     ║
║    请检查后重试」。_apply_output_limit() 为辅助     ║
║    函数，封装截断逻辑。                           ║
╚══════════════════════════════════════════════════╝
"""

import logging
import re
import time
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────
REQUEST_TIMEOUT = 15  # seconds
MAX_FETCH_SIZE = 500_000  # bytes — safety limit
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
BING_SEARCH_URL = "https://www.bing.com/search"


# ── Tool output length constraint ────────────────────────────────────

MAX_TOOL_OUTPUT_LENGTH = 40000
_TOOL_OUTPUT_TOO_LONG_MSG = "命令返回长度超过10ktoken，请检查后重试"


def _apply_output_limit(result: str) -> str:
    """Enforce a maximum character length on tool return values.

    If the result string exceeds ``MAX_TOOL_OUTPUT_LENGTH`` characters, it is
    replaced with a fixed prompt asking the agent to retry with a narrower
    scope.
    """
    if len(result) > MAX_TOOL_OUTPUT_LENGTH:
        return _TOOL_OUTPUT_TOO_LONG_MSG
    return result


# ── Tool 1: web_search (Bing) ─────────────────────────────────────────


def _parse_bing_html(html: str, max_results: int) -> list[dict[str, str]]:
    """Parse Bing search result HTML and return a list of {title, snippet, url}.

    Mimics the reference TypeScript implementation using BeautifulSoup.
    """
    results: list[dict[str, str]] = []
    soup = BeautifulSoup(html, "html.parser")

    # 1. Extract li.b_algo blocks (standard Bing result containers)
    for li in soup.select("li.b_algo"):
        link = li.select_one("a")
        if not link:
            continue
        href = link.get("href", "").strip()
        title = link.get_text(strip=True)
        if not title and not href:
            continue
        # snippet -> first <p> inside the result block
        snippet_tag = li.select_one("p")
        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
        results.append({"title": title, "snippet": snippet, "url": href})

    # 2. Fallback: if b_algo didn't match, extract all external links
    if not results:
        seen_urls: set[str] = set()
        for a in soup.select('a[href^="http"]'):
            href = a.get("href", "").strip()
            title = a.get_text(strip=True)
            if (
                title
                and href
                and "bing.com" not in href
                and "go.microsoft.com" not in href
                and href not in seen_urls
            ):
                seen_urls.add(href)
                results.append({"title": title, "snippet": "", "url": href})

    # 3. Deduplicate by URL
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for r in results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)

    return unique[:max_results]


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for information.

    Uses Bing search engine (no API key required, HTML scraping). Returns a
    list of search result titles, snippets, and URLs.

    Args:
        query: The search query string.
        max_results: Max number of results to return (1–20, default 5).

    Returns:
        A formatted string of search results, or an error message.
    """
    max_results = max(1, min(max_results, 20))  # clamp

    params = {"q": query}
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    try:
        resp = requests.get(
            BING_SEARCH_URL,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return _apply_output_limit(f"⏱️ Bing 搜索请求超时 (>{REQUEST_TIMEOUT}s): {query[:80]}")
    except requests.exceptions.HTTPError as e:
        return _apply_output_limit(f"Bing 搜索失败: HTTP {e.response.status_code} — {query[:80]}")
    except requests.exceptions.ConnectionError:
        return _apply_output_limit(f"连接失败 (DNS 解析或网络不可达): {query[:80]}")
    except Exception as exc:
        logger.warning("Bing search failed: %s", exc)
        # Retry once after a short delay
        try:
            time.sleep(1)
            resp = requests.get(
                BING_SEARCH_URL,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            resp.raise_for_status()
        except Exception as exc2:
            return _apply_output_limit(f"搜索失败 (Bing 不可达): {exc2}")

    html = resp.text
    results = _parse_bing_html(html, max_results)

    if not results:
        return _apply_output_limit(f"未找到与「{query}」相关的结果。")

    lines = [f"## 搜索结果 (Bing): 「{query}」\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "").strip()
        snippet = r.get("snippet", "").strip()
        url = r.get("url", "").strip()
        lines.append(f"### {i}. {title}")
        if snippet:
            snippet_short = snippet[:300] + ("..." if len(snippet) > 300 else "")
            lines.append(f"   {snippet_short}")
        if url:
            lines.append(f"   🔗 {url}")
        lines.append("")

    return _apply_output_limit("\n".join(lines).strip())


# ── Tool 2: web_fetch ─────────────────────────────────────────────────


@tool
def web_fetch(url: str, max_chars: int = 5000) -> str:
    """Fetch a web page and extract its readable text content.

    Downloads the HTML of the given URL, parses it with BeautifulSoup,
    removes scripts/styles/nav elements, and returns the main text.

    Args:
        url: The full URL to fetch (must start with http:// or https://).
        max_chars: Max characters of text to return (default 5000, max 50000).

    Returns:
        The extracted text content, or an error message.
    """
    # ── Validate URL ──────────────────────────────────────────────────
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return _apply_output_limit(f"错误: 不支持的协议「{parsed.scheme}」，仅支持 http/https")
    if not parsed.netloc:
        return _apply_output_limit(f"错误: 无效的 URL: {url}")

    max_chars = max(500, min(max_chars, 50_000))  # clamp

    # ── Fetch ─────────────────────────────────────────────────────────
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return _apply_output_limit(f"⏱️ 请求超时 (>{REQUEST_TIMEOUT}s): {url[:100]}")
    except requests.exceptions.HTTPError as e:
        return _apply_output_limit(f"HTTP 错误: {e.response.status_code} — {url[:100]}")
    except requests.exceptions.ConnectionError:
        return _apply_output_limit(f"连接失败 (DNS 解析或网络不可达): {url[:100]}")
    except Exception as e:
        return _apply_output_limit(f"请求失败: {e}")

    # ── Safety: check content size ────────────────────────────────────
    content_bytes = resp.content
    if len(content_bytes) > MAX_FETCH_SIZE:
        return _apply_output_limit(
            f"页面过大 ({len(content_bytes) / 1024:.0f} KB)，"
            f"超过安全限制 ({MAX_FETCH_SIZE / 1024:.0f} KB)"
        )

    # ── Parse ─────────────────────────────────────────────────────────
    try:
        content_type = resp.headers.get("content-type", "").lower()
        if "json" in content_type:
            # Return raw JSON text (truncated)
            raw = resp.text[:max_chars]
            return _apply_output_limit(f"🔗 {url}\n\n```json\n{raw}\n```")

        soup = BeautifulSoup(resp.content, "html.parser")
    except Exception as e:
        return _apply_output_limit(f"解析 HTML 失败: {e}")

    # ── Remove unwanted elements ──────────────────────────────────────
    for tag in ("script", "style", "nav", "footer", "header", "aside", "noscript"):
        for element in soup.find_all(tag):
            element.decompose()

    # ── Extract text ──────────────────────────────────────────────────
    text = soup.get_text(separator="\n", strip=True)

    # ── Clean up whitespace ───────────────────────────────────────────
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse excessive newlines
    text = re.sub(r"[ \t]+", " ", text)     # collapse horizontal whitespace

    # ── Truncate ──────────────────────────────────────────────────────
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n... (内容截断)"

    # ── Build title line ──────────────────────────────────────────────
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    header = f"🔗 {url}"
    if title:
        header += f"\n📄 {title}"

    return _apply_output_limit(f"{header}\n\n{text}".strip())


# ── Convenience: list of all web tools ────────────────────────────────

WEB_TOOLS = [web_search, web_fetch]