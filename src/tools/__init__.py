"""Tools package — exposes all tools to agents.

Modules:
- tools: read_file, edit_file, bash_exec, load_context_files
- web_search: web_search, web_fetch
- mcp_manager: MCP server management (list_mcp_servers, get_available_mcp_tools, format_mcp_context)
"""

from src.tools.mcp_manager import (
    list_mcp_servers_tool,
    get_available_mcp_tools,
    format_mcp_context,
    load_mcp_config,
)

__all__ = [
    "list_mcp_servers_tool",
    "get_available_mcp_tools",
    "format_mcp_context",
    "load_mcp_config",
]
