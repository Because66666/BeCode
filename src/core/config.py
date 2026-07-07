"""Application configuration loaded from .env file.

Data directory: ~/.becode/  — all runtime files (sessions, .env) are stored here.
"""

import os
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# ── Determine the BeCode data directory ────────────────────────────
# All runtime files (sessions, .env) are stored under ~/.becode/
BECODE_HOME = Path.home() / ".becode"
BECODE_HOME.mkdir(parents=True, exist_ok=True)

# The sessions directory is always under BECODE_HOME — not configurable
# via .env (to keep the data directory predictable).
SESSION_DIR = BECODE_HOME / "sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

# Load .env from ~/.becode/.env (create a default one if not present)
env_path = BECODE_HOME / ".env"
if not env_path.exists():
    # First run: try to copy project-root .env, or create default
    project_env = Path(__file__).resolve().parents[2] / ".env"
    if project_env.exists():
        env_path.write_text(project_env.read_text(encoding="utf-8"))
    else:
        env_path.write_text(
            "# BeCode Configuration\n"
            "# Copy this file to ~/.becode/.env and fill in your API credentials.\n"
            "# OpenAI-compatible API (default: https://api.openai.com/v1)\n"
            "OPENAI_API_BASE=https://api.openai.com/v1\n"
            "OPENAI_API_KEY=sk-your-api-key-here\n"
            "OPENAI_MODEL=gpt-4o\n\n"
            "# Agent Workflow\n"
            "MAX_ITERATIONS=10\n"
        )
load_dotenv(env_path)


class Settings(BaseSettings):
    # LLM Configuration
    openai_api_base: str = "https://api.openai.com/v1"
    openai_api_key: str = "sk-your-api-key-here"
    openai_model: str = "gpt-4o"

    # Agent Workflow
    max_iterations: int = 10

    # Log Level (only WARNING and above shown on console)
    log_level: str = "WARNING"

    model_config = {
        "env_file": str(env_path),
        "extra": "ignore",
    }


settings = Settings()
