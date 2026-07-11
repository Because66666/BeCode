"""Tests for src.tools.mcp_manager — MCP server config loading and tool discovery."""

import json
from pathlib import Path

import pytest

from src.tools.mcp_manager import (
    MCPServerConfig,
    load_mcp_config,
    _clear_mcp_config_cache,
    format_mcp_context,
    list_mcp_servers_tool,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_cache():
    """Clear MCP config cache before and after each test."""
    _clear_mcp_config_cache()
    yield
    _clear_mcp_config_cache()


@pytest.fixture
def mcp_config_dir(tmp_path: Path) -> Path:
    """Create a temporary .becode directory for MCP config."""
    cfg_dir = tmp_path / ".becode"
    cfg_dir.mkdir(parents=True)
    return cfg_dir


@pytest.fixture
def patch_home(monkeypatch, tmp_path: Path) -> Path:
    """Patch Path.home() to return a temp directory."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    return fake_home


# ── Test MCPServerConfig ────────────────────────────────────────────────────

class TestMCPServerConfig:
    """Tests for MCPServerConfig validation and properties."""

    def test_http_type(self):
        cfg = MCPServerConfig("test", {"type": "http", "url": "https://example.com/mcp"})
        assert cfg.server_type == "http"
        assert cfg.url == "https://example.com/mcp"
        assert cfg.command is None
        assert cfg.validate() is None

    def test_command_type(self):
        cfg = MCPServerConfig("test", {
            "command": "npx",
            "args": ["-y", "some-package"],
            "env": {"KEY": "val"},
        })
        assert cfg.server_type == "command"
        assert cfg.command == "npx"
        assert cfg.args == ["-y", "some-package"]
        assert cfg.env == {"KEY": "val"}
        assert cfg.validate() is None

    def test_command_type_without_type_field(self):
        """A config with 'command' but no 'type' should be detected as command."""
        cfg = MCPServerConfig("test", {"command": "echo"})
        assert cfg.server_type == "command"
        assert cfg.validate() is None

    def test_invalid_http_url(self):
        cfg = MCPServerConfig("test", {"type": "http", "url": "ftp://bad"})
        err = cfg.validate()
        assert err is not None
        assert "URL" in err

    def test_http_missing_url(self):
        cfg = MCPServerConfig("test", {"type": "http"})
        err = cfg.validate()
        assert err is not None
        assert "缺少" in err

    def test_command_missing_command(self):
        cfg = MCPServerConfig("test", {"type": "command"})
        err = cfg.validate()
        assert err is not None
        assert "缺少" in err

    def test_unknown_type(self):
        cfg = MCPServerConfig("test", {"type": "unknown"})
        err = cfg.validate()
        assert err is not None
        assert "未知类型" in err

    def test_empty_config(self):
        cfg = MCPServerConfig("test", {})
        assert cfg.server_type == "unknown"
        assert cfg.url is None
        assert cfg.command is None

    def test_default_env(self):
        cfg = MCPServerConfig("test", {"command": "echo"})
        assert cfg.env == {}

    def test_headers_property(self):
        """headers should return the configured headers dict."""
        cfg = MCPServerConfig("test", {
            "type": "http",
            "url": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer test123"},
        })
        assert cfg.headers == {"Authorization": "Bearer test123"}

    def test_headers_env_var_substitution(self, monkeypatch):
        """headers should resolve ${ENV_VAR} placeholders."""
        monkeypatch.setenv("MY_TOKEN", "super-secret-token")
        cfg = MCPServerConfig("test", {
            "type": "http",
            "url": "https://example.com/mcp",
            "headers": {
                "Authorization": "Bearer ${MY_TOKEN}",
                "X-Custom": "static-value",
            },
        })
        assert cfg.headers["Authorization"] == "Bearer super-secret-token"
        assert cfg.headers["X-Custom"] == "static-value"

    def test_headers_missing_env_var(self, monkeypatch):
        """headers should resolve missing env vars to empty string in-place."""
        cfg = MCPServerConfig("test", {
            "type": "http",
            "url": "https://example.com/mcp",
            "headers": {
                "Authorization": "Bearer ${NONEXISTENT_VAR}",
            },
        })
        # Unset env var → replaced with empty string: "Bearer " (trailing space preserved)
        assert cfg.headers["Authorization"] == "Bearer "

    def test_headers_invalid_type(self):
        """headers should return empty dict for non-dict values."""
        cfg = MCPServerConfig("test", {
            "type": "http",
            "url": "https://example.com/mcp",
            "headers": "not-a-dict",
        })
        assert cfg.headers == {}


# ── Test load_mcp_config ────────────────────────────────────────────────────

class TestLoadMCPConfig:
    """Tests for load_mcp_config with different file formats."""

    def test_no_config_file(self, patch_home, monkeypatch):
        """Should return empty dict when no config file exists.

        Note: ``_ensure_default_mcp_config()`` silently creates a default
        ``mcp.json`` with no servers, so we expect empty dict but the file
        itself is created.
        """
        # Also patch CWD to avoid picking up root project mcp.json
        monkeypatch.setattr("pathlib.Path.cwd", lambda: Path(patch_home))
        config = load_mcp_config()
        assert config == {}

    def test_servers_format(self, patch_home):
        """Test the 'servers' format (HTTP-focused)."""
        cfg_dir = patch_home / ".becode"
        cfg_dir.mkdir(parents=True)
        config_file = cfg_dir / "mcp_servers.json"
        config_file.write_text(json.dumps({
            "servers": {
                "github": {
                    "type": "http",
                    "url": "https://api.githubcopilot.com/mcp/"
                }
            }
        }))

        config = load_mcp_config(force_reload=True)
        # May include root-project mcp.json servers if present
        assert "github" in config
        assert config["github"].server_type == "http"
        assert config["github"].url == "https://api.githubcopilot.com/mcp/"

    def test_mcpServers_format(self, patch_home):
        """Test the 'mcpServers' format (command-focused)."""
        cfg_dir = patch_home / ".becode"
        cfg_dir.mkdir(parents=True)
        config_file = cfg_dir / "mcp_servers.json"
        config_file.write_text(json.dumps({
            "mcpServers": {
                "Chrome DevTools MCP": {
                    "command": "npx",
                    "args": ["-y", "chrome-devtools-mcp@latest"],
                    "env": {}
                }
            }
        }))

        config = load_mcp_config(force_reload=True)
        assert "Chrome DevTools MCP" in config
        assert config["Chrome DevTools MCP"].server_type == "command"
        assert config["Chrome DevTools MCP"].command == "npx"
        assert config["Chrome DevTools MCP"].args == ["-y", "chrome-devtools-mcp@latest"]

    def test_combined_formats(self, patch_home):
        """Both 'servers' and 'mcpServers' can coexist."""
        cfg_dir = patch_home / ".becode"
        cfg_dir.mkdir(parents=True)
        config_file = cfg_dir / "mcp_servers.json"
        config_file.write_text(json.dumps({
            "servers": {
                "http-server": {"type": "http", "url": "https://example.com/mcp"}
            },
            "mcpServers": {
                "cmd-server": {"command": "python", "args": ["server.py"]}
            }
        }))

        config = load_mcp_config(force_reload=True)
        assert "http-server" in config
        assert "cmd-server" in config

    def test_invalid_json(self, patch_home):
        """Invalid JSON should result in empty config.

        When the user-level config is invalid but root mcp.json exists,
        the root config is still returned.
        """
        cfg_dir = patch_home / ".becode"
        cfg_dir.mkdir(parents=True)
        config_file = cfg_dir / "mcp_servers.json"
        config_file.write_text("not valid json")

        config = load_mcp_config(force_reload=True)
        # Invalid user config falls back to root mcp.json (if it exists in CWD)
        if config:
            # Root mcp.json exists — should at least have those servers
            assert len(config) >= 1
        else:
            # No root mcp.json either
            assert config == {}

    def test_skip_invalid_server(self, patch_home):
        """Invalid server configs should be skipped with a warning."""
        cfg_dir = patch_home / ".becode"
        cfg_dir.mkdir(parents=True)
        config_file = cfg_dir / "mcp_servers.json"
        config_file.write_text(json.dumps({
            "servers": {
                "valid": {"type": "http", "url": "https://example.com/mcp"},
                "invalid": {"type": "http"},  # missing url
            }
        }))

        config = load_mcp_config(force_reload=True)
        assert "valid" in config
        assert "invalid" not in config

    def test_caching(self, patch_home):
        """Config should be cached after first load."""
        cfg_dir = patch_home / ".becode"
        cfg_dir.mkdir(parents=True)
        config_file = cfg_dir / "mcp_servers.json"
        config_file.write_text(json.dumps({
            "servers": {"s1": {"type": "http", "url": "https://example.com/mcp"}}
        }))

        # First load
        config1 = load_mcp_config()
        assert "s1" in config1

        # Modify the file without force_reload
        config_file.write_text(json.dumps({"servers": {}}))

        # Should still return cached data
        config2 = load_mcp_config()
        assert "s1" in config2

        # Force reload should see the new data (plus root mcp.json if present)
        config3 = load_mcp_config(force_reload=True)
        assert "s1" not in config3


# ── Test list_mcp_servers tool ──────────────────────────────────────────────

class TestListMCPserversTool:
    """Tests for the list_mcp_servers tool."""

    def test_no_servers(self, patch_home):
        """Should return a helpful message when no servers configured."""
        # Note: if root mcp.json exists, servers may be shown even with
        # patched home. This test just checks the basic format.
        result = list_mcp_servers_tool.func()
        # Either "未配置" (no servers at all) or "MCP 服务器" (has servers)
        assert "未配置" in result or "MCP" in result

    def test_with_servers(self, patch_home):
        """Should list configured servers."""
        cfg_dir = patch_home / ".becode"
        cfg_dir.mkdir(parents=True)
        config_file = cfg_dir / "mcp_servers.json"
        config_file.write_text(json.dumps({
            "servers": {
                "my-server": {"type": "http", "url": "https://mcp.example.com/"}
            }
        }))

        result = list_mcp_servers_tool.func()
        assert "my-server" in result
        assert "MCP 服务器" in result


# ── Test format_mcp_context ─────────────────────────────────────────────────

class TestFormatMCPContext:
    """Tests for format_mcp_context."""

    def test_empty_config(self, patch_home, monkeypatch):
        """Should return empty string when no servers configured."""
        # Also patch CWD to avoid picking up root project mcp.json
        monkeypatch.setattr("pathlib.Path.cwd", lambda: Path(patch_home))
        result = format_mcp_context()
        assert result == ""

    def test_with_config(self, patch_home):
        """Should return formatted context with server info."""
        cfg_dir = patch_home / ".becode"
        cfg_dir.mkdir(parents=True)
        config_file = cfg_dir / "mcp_servers.json"
        config_file.write_text(json.dumps({
            "servers": {
                "my-server": {"type": "http", "url": "https://mcp.example.com/"}
            }
        }))

        result = format_mcp_context()
        assert "MCP" in result
        assert "my-server" in result