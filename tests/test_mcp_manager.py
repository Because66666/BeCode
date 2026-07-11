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


# ── Test load_mcp_config ────────────────────────────────────────────────────

class TestLoadMCPConfig:
    """Tests for load_mcp_config with different file formats."""

    def test_no_config_file(self, patch_home):
        """Should return empty dict when no config file exists."""
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
        assert len(config) == 1
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
        assert len(config) == 1
        name = list(config.keys())[0]
        assert "Chrome" in name
        assert config[name].server_type == "command"
        assert config[name].command == "npx"
        assert config[name].args == ["-y", "chrome-devtools-mcp@latest"]

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
        assert len(config) == 2
        assert "http-server" in config
        assert "cmd-server" in config

    def test_invalid_json(self, patch_home):
        """Invalid JSON should result in empty config."""
        cfg_dir = patch_home / ".becode"
        cfg_dir.mkdir(parents=True)
        config_file = cfg_dir / "mcp_servers.json"
        config_file.write_text("not valid json")

        config = load_mcp_config(force_reload=True)
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
        assert len(config) == 1
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
        assert len(config1) == 1

        # Modify the file without force_reload
        config_file.write_text(json.dumps({"servers": {}}))

        # Should still return cached data
        config2 = load_mcp_config()
        assert len(config2) == 1

        # Force reload should see the new data
        config3 = load_mcp_config(force_reload=True)
        assert len(config3) == 0


# ── Test list_mcp_servers tool ──────────────────────────────────────────────

class TestListMCPserversTool:
    """Tests for the list_mcp_servers tool."""

    def test_no_servers(self, patch_home):
        """Should return a helpful message when no servers configured."""
        result = list_mcp_servers_tool.func()
        assert "未配置" in result
        assert "mcp_servers.json" in result

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

    def test_empty_config(self, patch_home):
        """Should return empty string when no servers configured."""
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