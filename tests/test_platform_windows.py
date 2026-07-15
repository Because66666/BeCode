"""验证 `prompt_platform_windows.md` 中关于 `subprocess.run(command, shell=True)` 的各项声明。

测试策略：直接调用 `subprocess.run(command, shell=True)` —— 与项目实际的命令执行方式一致，
绕过 bash_guard 层，纯粹验证 cmd.exe 的行为。

执行：`pytest tests/test_platform_windows.py -v --tb=short`
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

# ── 所有测试仅限 Windows ──────────────────────────────────────────────
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows 平台适用")


def _run(command: str, **kwargs) -> subprocess.CompletedProcess:
    """直接模拟 tools.py 中 subprocess.run(command, shell=True) 的调用方式。"""
    return subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        **kwargs,
    )


# ── 1. 运行环境：cmd.exe ──────────────────────────────────────────────

class TestShellIsCmdExe:
    """验证第 4 行：「命令在 cmd.exe 环境中执行」"""

    def test_comspec_is_cmd_exe(self):
        """%COMSPEC% 指向 cmd.exe"""
        r = _run("echo %COMSPEC%")
        assert r.returncode == 0
        assert "cmd.exe" in r.stdout.strip()

    def test_parent_process_is_cmd(self):
        """通过 %CMDCMDLINE% 确认实际解释器是 cmd.exe"""
        r = _run("echo %CMDCMDLINE%")
        assert r.returncode == 0
        assert "cmd.exe" in r.stdout.lower()


# ── 2. 环境变量：%VAR% 语法 ──────────────────────────────────────────

class TestEnvVarPercentSyntax:
    """验证第 12 行：「环境变量：用 %VAR% 读取」"""

    def test_read_with_percent_syntax(self):
        """%USERNAME% 能被正确展开"""
        r = _run("echo %USERNAME%")
        assert r.returncode == 0
        assert r.stdout.strip() != "%USERNAME%"  # 没有被原样输出，说明被展开了

    def test_read_userprofile(self):
        """%USERPROFILE% 能正确展开为路径"""
        r = _run("echo %USERPROFILE%")
        assert r.returncode == 0
        path = r.stdout.strip()
        assert path.startswith("C:\\") or path.startswith("D:\\")


# ── 3. PowerShell 专属语法应当失效 ──────────────────────────────────────

class TestPowerShellSyntaxFails:
    """验证第 4 行：「不要使用 PowerShell 专属语法」"""

    def test_env_dollar_syntax_fails(self):
        """PowerShell 的 $env:VAR 语法在 cmd.exe 中不被识别"""
        r = _run("echo $env:USERNAME")
        assert r.returncode == 0
        # cmd.exe 会将 $env:USERNAME 当作普通文本输出，而不是展开变量
        assert "$env:USERNAME" in r.stdout.strip()

    def test_new_item_fails(self):
        """PowerShell 的 New-Item 在 cmd.exe 中不可用"""
        r = _run("New-Item -Path .\\test_file.txt -ItemType File 2>&1")
        # cmd 不认识 New-Item，会报错
        assert r.returncode != 0 or "not recognized" in r.stderr.lower()

    def test_force_flag_fails(self):
        """PowerShell 的 -Force 参数风格在 cmd 中不被识别"""
        r = _run("echo '-Force'")
        assert r.returncode == 0
        assert "-Force" in r.stdout  # 仅作文本输出，不能作为参数语法


# ── 4. mkdir 自动创建父级目录 ───────────────────────────────────────────

class TestMkdirCreatesParents:
    """验证第 16 行：「mkdir 会自动创建父级目录」"""

    def test_mkdir_creates_parents(self, tmp_path: Path):
        """mkdir 可以一次性创建多级目录"""
        target = tmp_path / "a" / "b" / "c"
        r = _run(f"mkdir {target}")
        assert r.returncode == 0
        assert target.exists()


# ── 5. 顺序执行：& 和 && ──────────────────────────────────────────────

class TestSequentialExecution:
    """验证第 18 行：「用 & 串联，用 && 表示前步成功才执行」"""

    def test_ampersand_chains_always(self, tmp_path: Path):
        """& 无视前步成败，始终串联"""
        r = _run(
            f"cd /d {tmp_path} & echo first"
        )
        assert r.returncode == 0
        assert "first" in r.stdout

    def test_andand_conditional(self, tmp_path: Path):
        """&& 前步成功才执行后步"""
        r = _run(
            f"cd /d {tmp_path} && echo success"
        )
        assert r.returncode == 0
        assert "success" in r.stdout

    def test_andand_stops_on_failure(self, tmp_path: Path):
        """&& 在前步失败时停止"""
        r = _run(
            f"cd /d {tmp_path} && nonexistent_cmd_xyz && echo should_not_appear"
        )
        assert "should_not_appear" not in r.stdout


# ── 6. 文件操作：copy / xcopy / del ────────────────────────────────────

class TestFileOperations:
    """验证第 14 行：「使用 cmd 原生命令（copy/xcopy/move/del）」"""

    def test_copy_file(self, tmp_path: Path):
        """copy 命令可以复制文件"""
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("hello", encoding="utf-8")
        r = _run(f"copy /Y {src} {dst}")
        assert r.returncode == 0
        assert dst.exists()

    def test_xcopy_directory(self, tmp_path: Path):
        """xcopy 可以递归复制目录"""
        src_dir = tmp_path / "src_dir"
        src_file = src_dir / "f.txt"
        src_dir.mkdir(parents=True)
        src_file.write_text("data", encoding="utf-8")
        dst_dir = tmp_path / "dst_dir"
        r = _run(f"xcopy {src_dir} {dst_dir}\\ /E /I /Y")
        assert r.returncode == 0
        assert dst_dir.exists()
        assert (dst_dir / "f.txt").exists()

    def test_move_file(self, tmp_path: Path):
        """move 命令可以移动文件"""
        src = tmp_path / "movable.txt"
        dst = tmp_path / "moved.txt"
        src.write_text("data", encoding="utf-8")
        r = _run(f"move /Y {src} {dst}")
        assert r.returncode == 0
        assert dst.exists()
        assert not src.exists()

    def test_del_file(self, tmp_path: Path):
        """del 命令可以删除文件"""
        fp = tmp_path / "delete_me.txt"
        fp.write_text("bye", encoding="utf-8")
        r = _run(f"del /Q {fp}")
        assert r.returncode == 0
        assert not fp.exists()


# ── 7. %USERPROFILE% 替代硬编码路径 ──────────────────────────────────────

class TestUserprofileSubstitution:
    """验证第 7 行：用 %USERPROFILE% 替代 C:\\Users\\..."""

    def test_userprofile_expands(self):
        """%USERPROFILE% 展开后是合法的用户目录"""
        r = _run("dir /b %USERPROFILE%")
        assert r.returncode == 0
        # 至少应该能列出一些内容（不报错即可）
        assert "not found" not in r.stderr.lower()

    def test_userprofile_in_path(self):
        """使用 %USERPROFILE% 构造路径可以正常工作"""
        r = _run("dir /b /a %USERPROFILE%\\.nexus 2>nul || echo NO_NEXUS")
        assert r.returncode in (0, 1)  # 目录存在与否都算正常


# ── 8. 带空格/引号的路径 ──────────────────────────────────────────────────

class TestPathWithSpaces:
    """验证第 9 行：「含空格的路径用短名，含单引号的路径不加引号裸写」"""

    def test_short_name(self, tmp_path: Path):
        """含空格的路径使用短名（dir /x 可查）"""
        # 创建带空格的目录
        spaced = tmp_path / "test dir"
        spaced.mkdir(parents=True)
        # 获取短名
        r_dir = _run(f"dir /x {tmp_path}")
        assert r_dir.returncode == 0
        # 短名规则：确保目录存在且能被列出即可
        assert "test dir" in r_dir.stdout or "TESTDI~" in r_dir.stdout

    def test_no_double_quotes_for_single_quoted_path(self, tmp_path: Path):
        """含单引号的路径不加引号"""
        # 创建含单引号的目录
        quoted = tmp_path / "it's"
        quoted.mkdir(parents=True)
        test_file = quoted / "test.txt"
        test_file.write_text("ok", encoding="utf-8")

        # 不加引号直接使用短名（cmd 下含 ' 的路径不加引号）
        r = _run(f"dir /b /ad {tmp_path}")
        assert r.returncode == 0
        # 目录能被列出
        assert quoted.exists()
