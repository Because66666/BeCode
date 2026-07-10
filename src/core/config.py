"""Application configuration loaded from .env file.

Data directory: ~/.becode/  — all runtime files (sessions, .env) are stored here.

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - BECODE_HOME = ~/.becode/                     ║
║  - SESSION_DIR = ~/.becode/sessions/            ║
║  - .env 读取自 ~/.becode/.env，首次运行通过     ║
║    ensure_config() 交互式创建/提示。             ║
║  - 打包 (PyInstaller) 时不包含 .env 文件。       ║
╚══════════════════════════════════════════════════╝
"""

import os
import sys
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
"""


def ensure_config():
    """确保 ~/.becode/.env 存在；若缺失则创建并提示用户。

    该函数：
    1. 检查 ~/.becode/.env 是否存在。
    2. 不存在则创建默认模板。
    3. 提示用户当前无有效配置，询问是否打开编辑。
    4. 告知用户项目处于开发初级阶段，暂不支持 Anthropic 协议。
    """
    # ── 若 .env 不存在，创建默认模板 ──────────────────────────────
    newly_created = False
    if not env_path.exists():
        env_path.write_text(_DEFAULT_ENV_TEMPLATE.strip())
        newly_created = True

    if not newly_created:
        return  # .env 已存在，无需提示

    # ── 首次运行：交互式提示 ───────────────────────────────────────
    _print_config_notice()
    _prompt_open_editor()


def _print_config_notice():
    """打印首次运行配置提示信息。"""
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  检测到首次运行 — 未找到配置文件                        ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  配置文件路径: {env_path}  ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print("║  提示：本项目目前处于开发初级阶段。                     ║")
    print("║  当前仅支持 OpenAI 兼容协议（如 OpenAI、Azure、         ║")
    print("║  Groq、Together AI 等）。                               ║")
    print("║  暂不支持 Anthropic 协议（Claude API）。                ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()


def _prompt_open_editor():
    """询问用户是否打开编辑器编辑配置文件。"""
    try:
        answer = input("是否打开配置文件进行编辑？(y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    if answer in ("y", "yes"):
        _open_in_editor(env_path)
        print(f"[INFO] 编辑完成后保存即可生效。如需重新打开，请编辑: {env_path}")
    else:
        print(f"[INFO] 请手动编辑配置文件: {env_path}")
        print("[INFO] 在文件中填入你的 API Key 等信息后重新运行 BeCode。")

    print()
    print("[INFO] 你也可以随时编辑 ~/.becode/.env 来修改配置。")
    print()


def _open_in_editor(filepath: Path):
    """使用系统默认文本编辑器打开指定文件。"""
    try:
        if sys.platform == "win32":
            os.startfile(filepath)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", str(filepath)], check=True)
        else:
            # Linux / other Unix
            import subprocess
            # Try common editors: xdg-open (desktop default), then sensible-editor
            for editor_cmd in (
                ["xdg-open", str(filepath)],
                ["sensible-editor", str(filepath)],
                ["editor", str(filepath)],
                ["nano", str(filepath)],
                ["vim", str(filepath)],
            ):
                try:
                    subprocess.run(editor_cmd, check=True)
                    return
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
            # Fallback: can't open automatically
            print(f"[WARN] 无法自动打开编辑器。请手动编辑: {filepath}")
    except Exception as exc:
        print(f"[WARN] 打开编辑器失败: {exc}")
        print(f"[INFO] 请手动编辑配置文件: {filepath}")


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

    # Log Level (only WARNING and above shown on console)
    log_level: str = "WARNING"

    model_config = {
        "env_file": str(env_path),
        "extra": "ignore",
    }


settings = Settings()
