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
        },
        "mode": "auto"
      }
    }
  }

``mode`` can be ``"auto"`` (negotiate latest protocol version),
``"legacy"`` (use the legacy 2024-11-05 handshake), or a specific
version string like ``"2026-07-28"``.  Defaults to ``"auto"``.

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
║  - HTTP 类型支持 headers 配置项和 ${ENV_VAR} 环境变量   ║
║    替换（如 Authorization: Bearer ${GITHUB_TOKEN}）。║
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
from pydantic import BaseModel, Field, create_model

logger = logging.getLogger(__name__)


# ── V2026 protocol compatibility patch ─────────────────────────────────────

def _patch_v2026_list_tools_result() -> None:
    """Patch ``mcp_types.v2026_07_28.ListToolsResult`` to make fields that
    some servers (e.g. GitHub Copilot MCP) omit in their responses optional.

    The v2026 ``ListToolsResult`` model requires ``resultType``, ``cacheScope``,
    and ``ttlMs`` fields, but some MCP servers (notably GitHub Copilot) do not
    include these in their ``tools/list`` response.  This patch adds defaults
    so the Pydantic validation passes.

    The patch is idempotent — subsequent calls are no-ops.
    """
    if getattr(_patch_v2026_list_tools_result, "_applied", False):
        return

    try:
        from mcp_types import v2026_07_28 as v2026

        ltr = v2026.ListToolsResult

        # Set defaults on the required fields that some servers may omit
        ltr.model_fields["result_type"].default = "complete"
        ltr.model_fields["cache_scope"].default = "private"
        ltr.model_fields["ttl_ms"].default = 0

        # Rebuild the model so the compiled validator picks up the new defaults
        ltr.model_rebuild(force=True)

        _patch_v2026_list_tools_result._applied = True
        logger.debug("Patched v2026 ListToolsResult for protocol compatibility")
    except ImportError:
        logger.debug("mcp_types.v2026_07_28 not available, skip patch")
    except Exception as exc:
        logger.warning("Failed to patch v2026 ListToolsResult: %s", exc)


# Apply the patch at module import time
_patch_v2026_list_tools_result()


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

    @property
    def mode(self) -> str:
        """Return the protocol version mode.

        Reads from the ``mode`` key in the raw config.
        Defaults to ``"auto"`` (negotiate latest version).
        Can be set to a specific version string like ``"2024-11-05"``
        for servers that don't fully support the latest protocol.
        """
        return self.raw.get("mode", "auto")

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

async def _connect_http(url: str, headers: dict[str, str] | None = None,
                         mode: str = "auto") -> Any:
    """Connect to an HTTP MCP server and return the Client.

    Args:
        url: The MCP server endpoint URL.
        headers: Optional HTTP headers to include in every request
            (e.g. ``{"Authorization": "Bearer <token>"}``).
        mode: Protocol version mode. ``"auto"`` negotiates the latest
            version.  A specific version string (e.g. ``"2024-11-05"``)
            forces that version.  Defaults to ``"auto"``.

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
        client = Client(transport, mode=mode)
    else:
        client = Client(url, mode=mode)
    return await client.__aenter__()


async def _connect_command(command: str, args: list[str], env: dict[str, str],
                            mode: str = "auto") -> Any:
    """Connect to a command-based MCP server and return the Client."""
    from mcp import Client
    from mcp.client.stdio import stdio_client, StdioServerParameters

    params = StdioServerParameters(
        command=command,
        args=args,
        env=env or None,
    )
    transport = stdio_client(params)
    client = Client(transport, mode=mode)
    return await client.__aenter__()


async def _connect_server(config: MCPServerConfig, *,
                          forced_mode: str | None = None) -> Any:
    """Connect to an MCP server based on its config and return the Client.

    Args:
        config: The server configuration.
        forced_mode: If set, overrides the config's mode setting.

    Returns:
        An entered ``mcp.Client`` instance.
    """
    mode = forced_mode if forced_mode is not None else config.mode
    if config.server_type == "http":
        return await _connect_http(config.url, headers=config.headers, mode=mode)
    elif config.server_type == "command":
        return await _connect_command(config.command, config.args, config.env, mode=mode)
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

    If the initial connection fails due to a protocol version mismatch
    (e.g. the server doesn't fully support the latest MCP protocol version),
    automatically retries with an older protocol version (``"2024-11-05"``).

    Returns a list of tool dicts with keys: name, description, input_schema.
    The client is properly closed after discovery.
    """
    client = None
    try:
        client = await _connect_server(config)
        try:
            result = await client.list_tools()
        except Exception as exc:
            # Check if this is a validation error related to protocol version
            exc_str = str(exc)
            if ("ListToolsResult" in exc_str and "resultType" in exc_str) or \
               ("ValidationError" in exc_str and "resultType" in exc_str):
                logger.warning(
                    "Protocol version mismatch for [%s]: %s. Retrying with mode=legacy",
                    config.name, exc,
                )
                # Close the current client and reconnect with legacy protocol version
                await client.__aexit__(None, None, None)
                client = None
                client = await _connect_server(config, forced_mode="legacy")
                result = await client.list_tools()
            else:
                raise
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


# ── JSON Schema → Pydantic args_schema conversion ───────────────────────────

_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _json_schema_type_to_python(js_type: str, schema: dict[str, Any]) -> type:
    """Convert a JSON Schema type to a Python type.

    Handles basic types and container types (array with items).
    Falls back to ``str`` for unknown types.
    """
    if js_type == "array":
        items = schema.get("items", {})
        if isinstance(items, dict) and "type" in items:
            item_type = _json_schema_type_to_python(items["type"], items)
            return list[item_type]  # e.g. list[str]
        return list
    return _JSON_TYPE_MAP.get(js_type, str)


def _create_args_schema(tool_info: dict[str, Any]) -> type[BaseModel] | None:
    """Dynamically create a Pydantic model from an MCP tool's ``input_schema``.

    Converts JSON Schema ``properties`` into Pydantic model fields so that
    ``StructuredTool.from_function()`` has an explicit ``args_schema``.  This
    is critical because without it, LangChain auto-generates a schema with a
    single ``kwargs: dict`` field from the ``**kwargs`` function signature,
    which causes the LLM's tool-call arguments to be silently dropped.

    Returns:
        A Pydantic model class, or ``None`` if the tool has no properties.
    """
    input_schema = tool_info.get("input_schema", {})
    if not isinstance(input_schema, dict):
        return None

    properties = input_schema.get("properties", {})
    if not isinstance(properties, dict) or not properties:
        return None

    required_list: list[str] = input_schema.get("required", [])
    if not isinstance(required_list, list):
        required_list = []

    fields: dict[str, tuple[type, Any]] = {}
    for param_name, param_schema in properties.items():
        if not isinstance(param_schema, dict):
            continue

        js_type = param_schema.get("type", "string")
        python_type = _json_schema_type_to_python(js_type, param_schema)

        # Build a rich Field description that includes any JSON Schema
        # metadata useful for the LLM (description, enum values, etc.)
        desc_parts: list[str] = []
        raw_desc = param_schema.get("description", "")
        if raw_desc:
            desc_parts.append(raw_desc)

        enum_vals = param_schema.get("enum")
        if enum_vals and isinstance(enum_vals, list):
            desc_parts.append(f"可选值: {', '.join(str(v) for v in enum_vals)}")

        field_description = " | ".join(desc_parts) if desc_parts else None

        if param_name in required_list:
            fields[param_name] = (python_type, Field(description=field_description))
        else:
            fields[param_name] = (
                Optional[python_type],
                Field(default=None, description=field_description),
            )

    if not fields:
        return None

    # Sanitize the model name to avoid Pydantic warnings
    raw_name = tool_info.get("name", "tool")
    model_name = re.sub(r"[^a-zA-Z0-9_]", "_", f"MCP_{raw_name}_args")
    # Ensure it doesn't start with a digit
    if model_name and model_name[0].isdigit():
        model_name = f"Arg_{model_name}"

    return create_model(model_name, **fields)


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
            # Strip None values — the MCP server may reject them, and the
            # Pydantic args_schema sets default=None for optional fields.
            filtered = {k: v for k, v in kwargs.items() if v is not None}
            result = asyncio.run(_call_mcp_tool_async(
                config=config,
                tool_name=tool_name,
                arguments=filtered,
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
    """Connect to an MCP server, call a tool, and return the result as string.

    For HTTP servers using the v2026 protocol, this method calls ``list_tools()``
    first to populate the session's ``_x_mcp_header_maps``, which are required
    for the server to correctly route ``Mcp-Param-*`` headers.
    """
    client = None
    try:
        client = await _connect_server(config)
        # Call list_tools first to populate the session's header maps
        # (required for v2026 `Mcp-Param-*` header mobility feature).
        try:
            await client.list_tools()
        except Exception:
            # If list_tools fails, we still try to call the tool anyway
            pass
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
            properties = input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}

            # Create a proper Pydantic args_schema from the tool's input_schema
            # This is CRITICAL: without it, StructuredTool.from_function
            # auto-generates a schema with a single ``kwargs: dict`` field
            # from the ``**kwargs`` function signature, causing the LLM's
            # tool-call arguments to be silently dropped at runtime.
            args_schema = _create_args_schema(tool_info)

            # Create the wrapper function
            fn = _make_mcp_tool_fn(server_name, tool_info, config)

            # Build a StructuredTool (name sanitized for LLM API compliance)
            wrapped_tool = StructuredTool.from_function(
                func=fn,
                name=_sanitize_tool_name(f"mcp_{server_name}_{tool_name}"),
                args_schema=args_schema,
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
