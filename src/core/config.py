"""Application configuration loaded from .env file.

Data directory: ~/.becode/  — all runtime files (sessions, .env) are stored here.

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - BECODE_HOME = ~/.becode/                     ║
║  - SESSION_DIR = ~/.becode/sessions/            ║
║  - .env 读取自 ~/.becode/.env，首次运行静默创建  ║
║    (ensure_config() 不再弹出交互式提示)。        ║
║  - 打包 (PyInstaller) 时不包含 .env 文件。       ║
╚══════════════════════════════════════════════════╝
"""

import logging
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

# .env 路径（尚未创建——由 ensure_config() 在 main() 中处理）
env_path = BECODE_HOME / ".env"
# 首次导入时尝试加载（如果存在的话），避免 import 时因缺失而中断
load_dotenv(env_path)


# ── Default .env template ─────────────────────────────────────────

_DEFAULT_ENV_TEMPLATE = """\
# BeCode Configuration
# 请在此文件中填写你的 API 凭据。
#
# OpenAI-compatible API (default: https://api.openai.com/v1)
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=gpt-4o

# Agent Workflow
MAX_ITERATIONS=10

# Context Compression (Token 数)
MAX_CONTEXT_LENGTH=1000000

# GitHub Token (用于 GitHub MCP 服务器认证)
# 生成方式: https://github.com/settings/tokens (需要 copilot 权限)
# 或通过 `gh auth token` 获取
GITHUB_TOKEN=
"""


def ensure_config():
    """确保 ~/.becode/.env 存在；若缺失则静默创建默认模板。

    该函数静默操作，不会弹出交互式提示。
    """
    # ── 若 .env 不存在，静默创建默认模板 ──────────────────────────
    if not env_path.exists():
        env_path.write_text(_DEFAULT_ENV_TEMPLATE.strip())
        logger = logging.getLogger(__name__)
        logger.info("已创建默认配置: %s", env_path)




def reload_settings():
    """重新加载 .env 并刷新全局 settings 对象。

    在 ensure_config() 创建了 .env 后调用，使新配置生效。
    """
    global settings
    load_dotenv(env_path, override=True)
    settings = Settings()


class Settings(BaseSettings):
    # LLM Configuration
    openai_api_base: str = "https://api.openai.com/v1"
    openai_api_key: str = "sk-your-api-key-here"
    openai_model: str = "gpt-4o"

    # Agent Workflow
    max_iterations: int = 10

    # GitHub (for MCP authentication, consumed via os.environ)
    github_token: str = ""

    # Context Compression
    max_context_length: int = 1000000  # 最大上下文窗口（Token 数）
    context_margin_ratio: float = 0.95  # 安全余量比例（触发压缩阈值）
    compression_chunk_max_tokens: int = 50000  # Map 阶段每个 Chunk 的最大 Token 数
    compression_recent_rounds: int = 5  # Part B 保留的最近完整轮次数

    # Log Level (only WARNING and above shown on console)
    log_level: str = "WARNING"

    model_config = {
        "env_file": str(env_path),
        "extra": "ignore",
    }


settings = Settings()
