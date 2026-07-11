"""MCP Server Manager — connects to MCP servers and exposes their tools as LangChain tools.

Supports two transport types:
  - HTTP (Streamable HTTP): Connect via URL.
  - Command (stdio): Spawn a subprocess and connect via stdio.

Configuration is read from ``~/.becode/mcp_servers.json`` with two supported formats:

Format 1 (servers — HTTP focused):
  {
    "servers": {
      "server-name": {
        "type": "http",
        "url": "https://..."
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

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - MCP SDK v2 (mcp==2.0.0b1) 用于客户端连接。   ║
║  - HTTP 类型使用 Client(url) 直接连接。          ║
║  - Command 类型使用 stdio_client() 连接。        ║
║  - MCP 工具包装为 LangChain StructuredTool。     ║
║  - 配置存储在 ~/.becode/mcp_servers.json。       ║
║  - list_mcp_servers 工具让 Agent 可见所有已      ║
║    配置的 MCP 服务器及其工具列表。               ║
╚══════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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


# ── Config loading ─────────────────────────────────────────────────────────

def get_mcp_config_path() -> Path:
    """Return the MCP config file path, ensuring the directory exists.

    The path is resolved at call time (not import time) so that
    monkeypatching ``Path.home()`` in tests works correctly.
    """
    config_dir = Path.home() / ".becode"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "mcp_servers.json"


def load_mcp_config(force_reload: bool = False) -> dict[str, MCPServerConfig]:
    """Load all MCP server configurations from the config file.

    Args:
        force_reload: If True, reload from disk instead of using cache.

    Returns:
        A dict of {server_name: MCPServerConfig}, or an empty dict if the
        config file doesn't exist or contains no valid servers.
    """
    global _MCP_CONFIG_CACHE

    if not force_reload and _MCP_CONFIG_CACHE is not None:
        return _MCP_CONFIG_CACHE

    config_path = get_mcp_config_path()

    if not config_path.exists():
        logger.info("MCP config file not found: %s", config_path)
        # Return a default empty config
        _MCP_CONFIG_CACHE = {}
        return {}

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load MCP config: %s", exc)
        _MCP_CONFIG_CACHE = {}
        return {}

    servers: dict[str, MCPServerConfig] = {}

    # Format 1: {"servers": {"name": {"type": "http", "url": "..."}}}
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

    _MCP_CONFIG_CACHE = servers
    logger.info("Loaded %d MCP server config(s): %s", len(servers), list(servers.keys()))
    return servers


def _clear_mcp_config_cache() -> None:
    """Clear the cached MCP config (used in tests)."""
    global _MCP_CONFIG_CACHE
    _MCP_CONFIG_CACHE = None


# ── MCP Client connection helpers ─────────────────────────────────────────

async def _connect_http(url: str) -> Any:
    """Connect to an HTTP MCP server and return the Client."""
    from mcp import Client
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
    transport = await stdio_client(params).__aenter__()
    read_stream, write_stream = transport
    client = Client(read_stream, write_stream)
    return await client.__aenter__()


async def _connect_server(config: MCPServerConfig) -> Any:
    """Connect to an MCP server based on its config and return the Client."""
    if config.server_type == "http":
        return await _connect_http(config.url)
    elif config.server_type == "command":
        return await _connect_command(config.command, config.args, config.env)
    else:
        raise ValueError(f"Unsupported MCP server type: {config.server_type}")


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
                "input_schema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
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

    # Set a meaningful name and docstring
    tool_fn.__name__ = f"mcp_{server_name}_{tool_name}"
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

            # Build a StructuredTool
            wrapped_tool = StructuredTool.from_function(
                func=fn,
                name=f"mcp_{server_name}_{tool_name}",
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
        return "当前未配置任何 MCP 服务器。请编辑配置文件 `~/.becode/mcp_servers.json` 添加 MCP 服务器。\n\n支持的格式：\n```json\n{\n  \"servers\": {\n    \"server-name\": {\n      \"type\": \"http\",\n      \"url\": \"https://...\"\n    }\n  }\n}\n```\n或\n```json\n{\n  \"mcpServers\": {\n    \"server-name\": {\n      \"command\": \"npx\",\n      \"args\": [\"-y\", \"package\"],\n      \"env\": {}\n    }\n  }\n}\n```"

    result = format_mcp_context()
    return result or "已配置的 MCP 服务器无可用工具。"


list_mcp_servers_tool = StructuredTool.from_function(
    func=_list_mcp_servers_fn,
    name="list_mcp_servers",
    description="List all configured MCP (Model Context Protocol) servers and their available tools. "
                "Use this to discover what external capabilities are available. "
                "Returns server names, connection types (HTTP/command), and their tool lists.",
)
