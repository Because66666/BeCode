"""Tests for src.core.config — Settings, paths, env loading."""

import os
from pathlib import Path

import pytest


class TestSettings:
    """Verify default settings values (env-independent)."""

    def test_settings_has_expected_attrs(self):
        from src.core.config import settings
        assert hasattr(settings, "openai_api_base")
        assert hasattr(settings, "openai_api_key")
        assert hasattr(settings, "openai_model")
        assert hasattr(settings, "max_iterations")
        assert settings.max_iterations > 0

    def test_settings_loaded_from_env(self):
        from src.core.config import settings
        assert settings.openai_api_base.startswith("http")

    def test_max_iterations_default(self):
        from src.core.config import settings
        assert isinstance(settings.max_iterations, int)


class TestPaths:
    """Verify data directory paths."""

    def test_becode_home_is_dot_becode(self):
        from src.core.config import BECODE_HOME
        assert BECODE_HOME.name == ".becode"

    def test_session_dir_is_under_becode_home(self):
        from src.core.config import BECODE_HOME, SESSION_DIR
        assert SESSION_DIR.parent == BECODE_HOME
        assert SESSION_DIR.name == "sessions"

    def test_directories_exist(self):
        from src.core.config import BECODE_HOME, SESSION_DIR
        assert BECODE_HOME.exists()
        assert BECODE_HOME.is_dir()
        assert SESSION_DIR.exists()
        assert SESSION_DIR.is_dir()


class TestEnvFile:
    """Test that .env is created on first run scenarios."""

    def test_env_created_in_becode_home(self):
        from src.core.config import BECODE_HOME
        env_file = BECODE_HOME / ".env"
        assert env_file.exists()
        content = env_file.read_text(encoding="utf-8")
        assert "OPENAI_API_KEY" in content
        assert "OPENAI_MODEL" in content
