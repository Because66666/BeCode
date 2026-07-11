"""MCP Server Manager — connects to MCP servers and exposes their tools as LangChain tools.

Supports two transport types:
  - HTTP (Streamable HTTP): Connect via URL.
  - Command (stdio): Spawn a subprocess and connect via stdio.

Configuration is read from ``~/.becode/mcp.json`` (primary) with fallback to
``~/.becode/mcp_servers.json`` (legacy).  Two supported formats:

Format 1 (servers — HTTP focused):
  {
    "servers": {
      "server-name": {
        "type": "http",
        "url": "https://...",
        "headers": {
          "Authorization": "Bearer ${GITHUB_TOKEN}"
        }
      }
    }
  }

Format 2 (mcpServers — command focused):
  {
    "mcpServers": {
      "server-name": {
        "command": "npx",
        "args": ["-y", "some-mcp-server"],
        "env": {"KEY": "value"}
      }
    }
  }

Both formats can be combined in a single file.

If a root project ``mcp.json`` exists (at the current working directory), it
is also loaded and merged with the user-level config (project config takes
precedence on conflict).

On first run, a default ``~/.becode/mcp.json`` is created silently.

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - MCP SDK v2 (mcp==2.0.0b1) 用于客户端连接。   ║
║  - HTTP 类型支持 headers 配置项和 \$ 环境变量   ║
║    替换（如 Authorization: Bearer \${GITHUB_TOKEN}）。║
║  - Command 类型使用 stdio_client() 连接。        ║
║  - MCP 工具包装为 LangChain StructuredTool。     ║
║  - 配置文件: ~/.becode/mcp.json (主) /           ║
║    ~/.becode/mcp_servers.json (兼容旧版)。        ║
║  - 同时会加载项目根目录 mcp.json 并合并。         ║
║  - list_mcp_servers 工具让 Agent 可见所有已      ║
║    配置的 MCP 服务器及其工具列表。               ║
╚══════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────────────

_MCP_CONFIG_CACHE: dict[str, Any] | None = None
"""Cached MCP config, refreshed by load_mcp_config()."""


# ── Config types ───────────────────────────────────────────────────────────

class MCPServerConfig:
    """Represents a single MCP server configuration."""

    def __init__(self, name: str, config_dict: dict[str, Any]) -> None:
        self.name = name
        self.raw = config_dict

    @property
    def server_type(self) -> str:
        """Return 'http' or 'command'."""
        if "type" in self.raw:
            return self.raw["type"]
        if "command" in self.raw:
            return "command"
        return "unknown"

    @property
    def url(self) -> str | None:
        return self.raw.get("url")

    @property
    def command(self) -> str | None:
        return self.raw.get("command")

    @property
    def args(self) -> list[str]:
        return self.raw.get("args", [])

    @property
    def env(self) -> dict[str, str]:
        return self.raw.get("env", {})

    @property
    def headers(self) -> dict[str, str]:
        """Return custom HTTP headers for this server.

        Reads from the ``headers`` key in the raw config.  Supports
        ``${ENV_VAR}`` substitution inside any string value.
        """
        raw_headers = self.raw.get("headers", {})
        if not isinstance(raw_headers, dict):
            return {}
        resolved: dict[str, str] = {}
        for key, val in raw_headers.items():
            if val is None:
                continue
            val_str = str(val)
            # Replace all ${ENV_VAR} placeholders with environment variable values
            resolved[key] = re.sub(
                r"\$\{(\w+)\}",
                lambda m: os.environ.get(m.group(1), ""),
                val_str,
            )
        return {k: v for k, v in resolved.items() if v}

    def validate(self) -> str | None:
        """Return error message if invalid, or None."""
        if self.server_type == "http":
            if not self.url:
                return f"MCP 服务器 [{self.name}]: HTTP 类型缺少 'url'"
            if not self.url.startswith(("http://", "https://")):
                return f"MCP 服务器 [{self.name}]: URL 必须以 http:// 或 https:// 开头"
        elif self.server_type == "command":
            if not self.command:
                return f"MCP 服务器 [{self.name}]: 命令类型缺少 'command'"
        else:
            return f"MCP 服务器 [{self.name}]: 未知类型 (需要 'type: http' 或 'command' 字段)"
        return None


# ── Default MCP config template ────────────────────────────────────────────

_DEFAULT_MCP_CONFIG = {
    "mcpServers": {},
    "_note": "在此处添加 MCP 服务器配置。格式参考: https://modelcontextprotocol.io"
}


def _ensure_default_mcp_config(config_dir: Path) -> Path:
    """Silently create a default ``mcp.json`` if neither ``mcp.json`` nor
    ``mcp_servers.json`` exists.

    Returns the path to the config file to use (prefers ``mcp.json``).
    """
    mcp_json = config_dir / "mcp.json"
    mcp_servers_json = config_dir / "mcp_servers.json"

    if mcp_json.exists():
        return mcp_json
    if mcp_servers_json.exists():
        # Legacy format exists — keep using it
        return mcp_servers_json

    # Neither exists — silently create mcp.json
    mcp_json.write_text(json.dumps(_DEFAULT_MCP_CONFIG, ensure_ascii=False, indent=2))
    return mcp_json


# ── Config loading ─────────────────────────────────────────────────────────

def get_mcp_config_path() -> Path:
    """Return the MCP config file path, ensuring the directory exists.

    Returns the path to the primary config file (``mcp.json``), falling back
    to legacy ``mcp_servers.json`` if only that exists.  Creates a default
    ``mcp.json`` if neither exists.

    The path is resolved at call time (not import time) so that
    monkeypatching ``Path.home()`` in tests works correctly.
    """
    config_dir = Path.home() / ".becode"
    config_dir.mkdir(parents=True, exist_ok=True)
    return _ensure_default_mcp_config(config_dir)


def _load_json_file(filepath: Path) -> dict:
    """Load and parse a JSON file, returning an empty dict on failure."""
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load MCP config %s: %s", filepath, exc)
        return {}


def _merge_mcp_raw(raw_from_user: dict, raw_from_root: dict) -> dict:
    """Merge root project mcp.json into user config.

    Project config takes precedence on key conflict within each section.
    """
    merged = dict(raw_from_user)
    for key in ("servers", "mcpServers"):
        user_section = merged.get(key, {})
        root_section = raw_from_root.get(key, {})
        if isinstance(user_section, dict) and isinstance(root_section, dict):
            # Merge: root project servers take precedence
            combined = dict(root_section)
            combined.update(user_section)
            merged[key] = combined
        elif isinstance(root_section, dict) and not isinstance(user_section, dict):
            merged[key] = root_section
    return merged


def _get_root_mcp_config() -> dict:
    """Try to load ``mcp.json`` from the current working directory.

    Returns an empty dict if not found.
    """
    root_mcp = Path.cwd() / "mcp.json"
    if root_mcp.exists():
        logger.info("Found root project mcp.json: %s", root_mcp)
        return _load_json_file(root_mcp)
    return {}


def _parse_servers_from_raw(raw: dict) -> dict[str, MCPServerConfig]:
    """Parse server configurations from a raw JSON dict.

    Supports both ``servers`` and ``mcpServers`` keys.
    """
    servers: dict[str, MCPServerConfig] = {}
    for key in ("servers", "mcpServers"):
        section = raw.get(key, {})
        if not isinstance(section, dict):
            continue
        for name, cfg in section.items():
            if not isinstance(cfg, dict):
                continue
            server_cfg = MCPServerConfig(name, cfg)
            err = server_cfg.validate()
            if err:
                logger.warning("Skipping MCP server config: %s", err)
                continue
            servers[name] = server_cfg
    return servers


def load_mcp_config(force_reload: bool = False) -> dict[str, MCPServerConfig]:
    """Load all MCP server configurations from the config file(s).

    Load order:
      1. User-level config from ``~/.becode/mcp.json`` (or legacy
         ``~/.becode/mcp_servers.json``).
      2. Project-level config from root ``mcp.json`` (if exists).
      3. Merge: project servers take precedence on name conflict.

    Args:
        force_reload: If True, reload from disk instead of using cache.

    Returns:
        A dict of {server_name: MCPServerConfig}, or an empty dict if no
        valid servers are configured.
    """
    global _MCP_CONFIG_CACHE

    if not force_reload and _MCP_CONFIG_CACHE is not None:
        return _MCP_CONFIG_CACHE

    config_path = get_mcp_config_path()

    if not config_path.exists():
        logger.info("MCP config file not found: %s", config_path)
        _MCP_CONFIG_CACHE = {}
        return {}

    # ── Load user-level config ──────────────────────────────────────────
    raw_user = _load_json_file(config_path)

    # ── Load & merge root project mcp.json ──────────────────────────────
    raw_root = _get_root_mcp_config()
    if raw_root:
        raw_merged = _merge_mcp_raw(raw_user, raw_root)
    else:
        raw_merged = raw_user

    servers = _parse_servers_from_raw(raw_merged)

    _MCP_CONFIG_CACHE = servers
    logger.info("Loaded %d MCP server config(s): %s", len(servers), list(servers.keys()))
    return servers


def _clear_mcp_config_cache() -> None:
    """Clear the cached MCP config (used in tests)."""
    global _MCP_CONFIG_CACHE
    _MCP_CONFIG_CACHE = None


# ── MCP Client connection helpers ─────────────────────────────────────────

async def _connect_http(url: str, headers: dict[str, str] | None = None) -> Any:
    """Connect to an HTTP MCP server and return the Client.

    Args:
        url: The MCP server endpoint URL.
        headers: Optional HTTP headers to include in every request
            (e.g. ``{"Authorization": "Bearer <token>"}``).

    Returns:
        An entered ``mcp.Client`` instance.
    """
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    if headers:
        # Create a custom httpx client with the extra headers, then pass it
        # to streamable_http_client so every HTTP request carries them.
        import httpx

        http_client = httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
        )
        transport = streamable_http_client(url, http_client=http_client)
        # Client accepts a Transport tuple directly
        client = Client(transport)
    else:
        client = Client(url)
    return await client.__aenter__()


async def _connect_command(command: str, args: list[str], env: dict[str, str]) -> Any:
    """Connect to a command-based MCP server and return the Client."""
    from mcp import Client
    from mcp.client.stdio import stdio_client, StdioServerParameters

    params = StdioServerParameters(
        command=command,
        args=args,
        env=env or None,
    )
    transport = stdio_client(params)
    client = Client(transport)
    return await client.__aenter__()


async def _connect_server(config: MCPServerConfig) -> Any:
    """Connect to an MCP server based on its config and return the Client."""
    if config.server_type == "http":
        return await _connect_http(config.url, headers=config.headers)
    elif config.server_type == "command":
        return await _connect_command(config.command, config.args, config.env)
    else:
        raise ValueError(f"Unsupported MCP server type: {config.server_type}")


# ── Tool name sanitization ─────────────────────────────────────────────────

def _sanitize_tool_name(name: str) -> str:
    """Sanitize a tool name to match ``^[a-zA-Z0-9_-]+$``.

    Replaces any character that is not alphanumeric, underscore, or hyphen
    with an underscore.
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


# ── Tool discovery & wrapping ──────────────────────────────────────────────

async def _discover_tools(config: MCPServerConfig) -> list[dict[str, Any]]:
    """Connect to an MCP server and discover its tools.

    Returns a list of tool dicts with keys: name, description, input_schema.
    The client is properly closed after discovery.
    """
    client = None
    try:
        client = await _connect_server(config)
        result = await client.list_tools()
        tools = []
        for tool in result.tools:
            tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.input_schema,
            })
        return tools
    finally:
        if client is not None:
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass


def _make_mcp_tool_fn(server_name: str, tool_info: dict[str, Any],
                      config: MCPServerConfig) -> callable:
    """Create a synchronous wrapper function for an MCP tool call.

    The returned function, when called, will:
      1. Connect to the MCP server.
      2. Call the tool with the provided arguments.
      3. Disconnect.
      4. Return the result as a string.
    """
    tool_name = tool_info["name"]

    def tool_fn(**kwargs: Any) -> str:
        """Call an MCP tool synchronously.

        Connects to the MCP server, calls the tool, returns the result.
        """
        try:
            result = asyncio.run(_call_mcp_tool_async(
                config=config,
                tool_name=tool_name,
                arguments=kwargs,
            ))
            return result
        except Exception as exc:
            logger.exception("MCP tool [%s/%s] failed", server_name, tool_name)
            return f"❌ MCP 工具 [{server_name}/{tool_name}] 调用失败: {exc}"

    # Set a meaningful name and docstring (sanitized for LLM API compliance)
    tool_fn.__name__ = _sanitize_tool_name(f"mcp_{server_name}_{tool_name}")
    tool_fn.__doc__ = tool_info.get("description") or f"MCP tool: {server_name}/{tool_name}"
    return tool_fn


async def _call_mcp_tool_async(config: MCPServerConfig, tool_name: str,
                                arguments: dict[str, Any]) -> str:
    """Connect to an MCP server, call a tool, and return the result as string."""
    client = None
    try:
        client = await _connect_server(config)
        result = await client.call_tool(tool_name, arguments)
        # Convert result to string
        if hasattr(result, "structured_content") and result.structured_content:
            return json.dumps(result.structured_content, ensure_ascii=False, default=str)
        if hasattr(result, "content") and result.content:
            # content may be a list of TextContent or similar
            parts = []
            for item in result.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
                elif hasattr(item, "data"):
                    parts.append(str(item.data))
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return json.dumps(result, ensure_ascii=False, default=str)
    finally:
        if client is not None:
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass


# ── Agent-facing functions ─────────────────────────────────────────────────

def get_available_mcp_tools() -> list[StructuredTool]:
    """Discover all MCP servers and wrap their tools as LangChain tools.

    This function:
      1. Loads MCP config.
      2. For each configured server, connects and discovers tools.
      3. Wraps each discovered tool as a ``StructuredTool``.
      4. Returns the full list of wrapped tools.

    Returns:
        A list of ``StructuredTool`` instances (may be empty).
    """
    servers = load_mcp_config()
    if not servers:
        return []

    langchain_tools: list[StructuredTool] = []

    for server_name, config in servers.items():
        try:
            tools_info = asyncio.run(_discover_tools(config))
        except Exception as exc:
            logger.warning("Failed to discover tools from MCP server [%s]: %s",
                           server_name, exc)
            continue

        for tool_info in tools_info:
            tool_name = tool_info.get("name", "unknown")
            description = tool_info.get("description", "")
            input_schema = tool_info.get("input_schema", {})

            # Build argument schema from the MCP tool's input schema
            # Convert JSON Schema to a simple dict of {arg_name: type_hint}
            schema = input_schema if isinstance(input_schema, dict) else {}
            properties = schema.get("properties", {})
            required = schema.get("required", [])

            # Create the wrapper function
            fn = _make_mcp_tool_fn(server_name, tool_info, config)

            # Build a StructuredTool (name sanitized for LLM API compliance)
            wrapped_tool = StructuredTool.from_function(
                func=fn,
                name=_sanitize_tool_name(f"mcp_{server_name}_{tool_name}"),
                description=(
                    f"[MCP] [{server_name}] {description}\n\n"
                    f"服务器: {server_name}\n"
                    f"原始工具名: {tool_name}\n"
                    f"参数: {json.dumps(properties, ensure_ascii=False)}"
                ),
            )
            langchain_tools.append(wrapped_tool)
            logger.debug("Wrapped MCP tool: %s/%s", server_name, tool_name)

    return langchain_tools


def format_mcp_context() -> str:
    """Return a formatted string describing all configured MCP servers and their tools.

    This is injected into the agent's system prompt so the agent knows what
    MCP tools are available.
    """
    servers = load_mcp_config()
    if not servers:
        return ""

    lines = ["## 可用的 MCP 服务器"]
    for server_name, config in servers.items():
        if config.server_type == "http":
            conn_info = f"🔗 {config.url}"
            if config.headers:
                masked = {k: "***" for k in config.headers}
                conn_info += f"  |  headers: {json.dumps(masked, ensure_ascii=False)}"
        else:
            conn_info = f"💻 {config.command} {' '.join(config.args)}"

        lines.append(f"")
        lines.append(f"### 📡 {server_name}")
        lines.append(f"   连接方式: {conn_info}")

        # Try to discover tools (best-effort)
        try:
            tools_info = asyncio.run(_discover_tools(config))
        except Exception as exc:
            lines.append(f"   ⚠️  工具发现失败: {exc}")
            continue

        if not tools_info:
            lines.append(f"   (该服务器未提供任何工具)")
            continue

        for tool in tools_info:
            t_name = tool.get("name", "unknown")
            t_desc = tool.get("description", "").strip()
            t_schema = tool.get("input_schema", {})
            params_str = ", ".join(
                f"{k}: {v.get('type', 'any')}"
                for k, v in t_schema.get("properties", {}).items()
            ) if t_schema else "(无参数)"
            desc_line = f" — {t_desc[:120]}" if t_desc else ""
            lines.append(f"   - **{t_name}**({params_str}){desc_line}")

    return "\n".join(lines)


# ── list_mcp_servers tool ──────────────────────────────────────────────────

def _list_mcp_servers_fn() -> str:
    """List all configured MCP servers and their available tools.

    Returns:
        A formatted string with server names, connection info, and tool lists.
    """
    servers = load_mcp_config()
    if not servers:
        return "当前未配置任何 MCP 服务器。请编辑配置文件 `~/.becode/mcp.json` 添加 MCP 服务器。\n\n支持的格式：\n```json\n{\n  \"servers\": {\n    \"server-name\": {\n      \"type\": \"http\",\n      \"url\": \"https://...\"\n    }\n  }\n}\n```\n或\n```json\n{\n  \"mcpServers\": {\n    \"server-name\": {\n      \"command\": \"npx\",\n      \"args\": [\"-y\", \"package\"],\n      \"env\": {}\n    }\n  }\n}\n```\n\n你也可以在项目根目录放置 `mcp.json` 文件，其中的配置会自动合并。"

    result = format_mcp_context()
    return result or "已配置的 MCP 服务器无可用工具。"


list_mcp_servers_tool = StructuredTool.from_function(
    func=_list_mcp_servers_fn,
    name="list_mcp_servers",
    description="List all configured MCP (Model Context Protocol) servers and their available tools. "
                "Use this to discover what external capabilities are available. "
                "Returns server names, connection types (HTTP/command), and their tool lists.",
)
