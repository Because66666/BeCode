"""AgentConsole — Rich terminal UI for the Agent Workflow System.

Provides a Claude Code-style terminal interface with:
- Colored section headers with icons
- Compact 3-line tool call display
- Real-time command output rendering
- Clean visual separation between agent thinking, tool usage, and results

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - tool_call() 方法只展示三行: 工具名称、参数、  ║
║    执行结果（单行截断 ≤100 字符）。              ║
║    移除了 tool_call_start / tool_call_end。      ║
║  - final_result() 移除了并排 Table，仅保留       ║
║    紧凑统计信息 Panel。                          ║
║  - 移除了 enter_interactive_mode() 方法。        ║
║  - interactive_prompt() 支持平台特定的可编辑     ║
║    预填：Windows 用 kernel32.WriteConsoleInputW, ║
║    Unix/macOS 用 readline.set_startup_hook。     ║
╚══════════════════════════════════════════════════╝
"""

import sys
import shutil
import signal
from typing import Optional
from pathlib import Path

from rich.console import Console as RichConsole
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.markdown import Markdown
from rich.rule import Rule
from rich import box

from src.ui.collapsible import get_display, reset_display, CollapsibleSection

_console: Optional["AgentConsole"] = None


def get_console() -> "AgentConsole":
    """Get or create the global AgentConsole singleton."""
    global _console
    if _console is None:
        _console = AgentConsole()
    return _console


# ── Platform-specific Prefill Input Helpers ────────────────────────


def _unix_prefill_input(prompt_text: str, prefill: str) -> str:
    """Use ``readline`` to pre-fill text on Unix / macOS.

    The text appears at the prompt ready for the user to edit.
    """
    try:
        import readline  # noqa: F401
    except ImportError:
        # Fallback: just print the hint (no editable pre-fill)
        print(f"\n💬 {prompt_text} {prefill}", end="")
        return input().strip()

    def hook():
        readline.insert_text(prefill)

    readline.set_startup_hook(hook)
    try:
        return input(f"\n[bold cyan]💬 {prompt_text}[/] ").strip()
    finally:
        readline.set_startup_hook()


def _win32_prefill_input(prompt_text: str, prefill: str) -> str:
    """Pre-fill text into the console input buffer on Windows.

    Uses ``WriteConsoleInputA`` to inject each character as a key-down
    event so that the text appears at the prompt and the user can edit it.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32

    STD_INPUT_HANDLE = -10
    h_stdin = kernel32.GetStdHandle(STD_INPUT_HANDLE)

    # ── Write the prompt first ──────────────────────────────────────
    print()
    sys.stdout.write(f"💬 {prompt_text} ")
    sys.stdout.flush()

    # ── Write each character as a key-down INPUT_RECORD ──────────────
    # typedef struct _INPUT_RECORD {
    #     WORD  EventType;
    #     union {
    #         KEY_EVENT_RECORD   KeyEvent;
    #         MOUSE_EVENT_RECORD MouseEvent;
    #         WINDOW_BUFFER_SIZE_RECORD WindowBufferSizeEvent;
    #         MENU_EVENT_RECORD  MenuEvent;
    #     } Event;
    # } INPUT_RECORD;
    #
    # EventType: 1 = KEY_EVENT
    #
    # typedef struct _KEY_EVENT_RECORD {
    #     BOOL  bKeyDown;
    #     WORD  wRepeatCount;
    #     WORD  wVirtualKeyCode;
    #     WORD  wVirtualScanCode;
    #     union {
    #         WCHAR UnicodeChar;
    #         CHAR  AsciiChar;
    #     } uChar;
    #     DWORD dwControlKeyState;
    # } KEY_EVENT_RECORD;

    class KEY_EVENT_RECORD(ctypes.Structure):
        _fields_ = [
            ("bKeyDown", wintypes.BOOL),
            ("wRepeatCount", wintypes.WORD),
            ("wVirtualKeyCode", wintypes.WORD),
            ("wVirtualScanCode", wintypes.WORD),
            ("uChar", wintypes.WCHAR),
            ("dwControlKeyState", wintypes.DWORD),
        ]

    class EVENT_U(ctypes.Union):
        _fields_ = [("KeyEvent", KEY_EVENT_RECORD)]

    class INPUT_RECORD(ctypes.Structure):
        _fields_ = [
            ("EventType", wintypes.WORD),
            ("Event", EVENT_U),
        ]

    INPUT_RECORD_SIZE = ctypes.sizeof(INPUT_RECORD)

    # Build an array of INPUT_RECORDs — one key-down per character
    records = []
    for ch in prefill:
        rec = INPUT_RECORD()
        rec.EventType = 1  # KEY_EVENT
        rec.Event.KeyEvent.bKeyDown = True
        rec.Event.KeyEvent.wRepeatCount = 1
        rec.Event.KeyEvent.wVirtualKeyCode = 0
        rec.Event.KeyEvent.wVirtualScanCode = 0
        rec.Event.KeyEvent.uChar = ch
        rec.Event.KeyEvent.dwControlKeyState = 0
        records.append(rec)

    if records:
        n_written = wintypes.DWORD(0)
        ArrayType = INPUT_RECORD * len(records)
        arr = ArrayType(*records)
        kernel32.WriteConsoleInputW(
            h_stdin,
            ctypes.byref(arr),
            len(records),
            ctypes.byref(n_written),
        )

    # ── Now read the input (pre-filled text is already in buffer) ────
    return input().strip()


class AgentConsole:
    """Styled terminal output mimicking Claude Code's interface."""

    def __init__(self):
        self._console = RichConsole(force_terminal=True, color_system="truecolor")
        self._width = min(shutil.get_terminal_size().columns, 100)
        self._collapsible = get_display()

    # ── Welcome / Startup ─────────────────────────────────────────────

    def welcome(self, session_id: str, max_iterations: int, model: str):
        """Display the welcome banner."""
        panel = Panel(
            Text.from_markup(
                f"\n  [bold cyan]🧠 Agent Workflow System[/]\n"
                f"  [dim]Claude Code-style CLI Interface[/]\n\n"
                f"  [white]会话 ID:[/] [yellow]{session_id}[/]\n"
                f"  [white]最大轮次:[/] [yellow]{max_iterations}[/]\n"
                f"  [white]模型:[/] [yellow]{model}[/]\n"
            ),
            box=box.HEAVY,
            border_style="cyan",
            width=self._width,
            title="[bold]🚀 启动[/]",
        )
        self._console.print(panel)
        self._console.print()

    def show_requirement(self, requirement: str):
        """Show the user's requirement in a styled panel (full content)."""
        self._console.print(
            Panel(
                Markdown(requirement),
                box=box.ROUNDED,
                border_style="yellow",
                title="[bold]📋 用户需求[/]",
                width=self._width,
            )
        )
        self._console.print()

    # ── Summary Display (Interactive Mode) ────────────────────────────

    def show_summary(self, text: str):
        """Display a one-line LLM-generated task summary in light gray italic."""
        self._console.print()
        self._console.print(
            Panel(
                Text.from_markup(f"[italic bright_black]{text}[/]"),
                box=box.SIMPLE,
                border_style="bright_black",
                width=self._width,
                padding=(0, 1),
                title="[dim italic]📋 上次任务总结[/]",
            )
        )
        self._console.print()

    def interactive_prompt(self, prompt_text: str = "请输入需求:", prefill: str = "") -> str:
        """Show an interactive input prompt with optional editable pre-fill.

        On Ctrl+C return in a prior round, the *previous* user input is
        pre-filled into the input buffer so the user can edit it directly.

        Args:
            prompt_text: The prompt message to display.
            prefill: Previous user input to pre-fill (editable by user).

        Returns:
            The user's input string (may be empty).
        """
        try:
            if prefill:
                user_input = self._prefill_input(prompt_text, prefill)
            else:
                user_input = input(f"\n[bold cyan]💬 {prompt_text}[/] ").strip()
            return user_input
        except KeyboardInterrupt:
            raise

    # ── Platform-specific prefill helpers ──────────────────────────────

    @staticmethod
    def _prefill_input(prompt_text: str, prefill: str) -> str:
        """Get input with the given text pre-filled into the input buffer.

        The pre-filled text appears at the prompt and the user can edit it
        freely (cursor at end of text).
        """
        if sys.platform == "win32":
            return _win32_prefill_input(prompt_text, prefill)
        else:
            return _unix_prefill_input(prompt_text, prefill)

    def show_interrupt_message(self, has_output: bool = False):
        """Display a Ctrl+C interrupt message."""
        if has_output:
            self._console.print(
                Panel(
                    Text.from_markup(
                        "[italic dim]⌨️ 用户中断 — 当前输出已保留，可继续输入新需求[/]"
                    ),
                    box=box.SIMPLE,
                    border_style="yellow",
                    width=self._width,
                    padding=(0, 1),
                )
            )
        else:
            self._console.print(
                Panel(
                    Text.from_markup(
                        "[italic dim]⌨️ 用户中断 — 返回输入状态[/]"
                    ),
                    box=box.SIMPLE,
                    border_style="yellow",
                    width=self._width,
                    padding=(0, 1),
                )
            )
        self._console.print()

    # ── Iteration / Agent Lifecycle ───────────────────────────────────

    def start_iteration(self, iteration: int, total: int):
        """Mark the start of a new iteration."""
        self._console.print()
        self._console.print(
            Rule(
                f"[bold cyan] 第 {iteration}/{total} 轮 [/]",
                style="cyan",
                characters="━",
            )
        )
        self._console.print()

    def agent_thinking(self, agent_name: str, message: str = ""):
        """Show the agent is thinking/reasoning."""
        prefix = {
            "coder": "[bold green]🤖 Coder Agent[/]",
            "reviewer": "[bold magenta]🔍 Reviewer Agent[/]",
        }.get(agent_name, f"[bold white]{agent_name}[/]")

        text = f"{prefix} [dim]思考中...[/]"
        if message:
            text += f"\n[italic dim]{message}[/]"
        self._console.print(text)
        self._console.print()

    # ── Tool Calls (merged invocation + result) ──────────────────────

    @staticmethod
    def _short_path(p: str, max_len: int = 60) -> str:
        """Shorten a file path to a relative path (workspace-relative)."""
        try:
            p_obj = Path(p)
            # If absolute, try to make relative
            if p_obj.is_absolute():
                try:
                    rel = p_obj.relative_to(Path.cwd())
                    p = str(rel)
                except ValueError:
                    pass
        except Exception:
            pass
        if len(p) > max_len:
            p = "..." + p[-(max_len - 3):]
        return p

    def tool_call(self, tool_name: str, args: dict, result: str):
        """Display a compact 3-line tool call Panel.

        Line 1 — Tool call name (e.g. 💻 命令调用)
        Line 2 — Parameters (single line, truncated; file tools show path)
        Line 3 — Result excerpt (single line, truncated)
        """
        icons = {
            "read_file": "📖",
            "edit_file": "✏️",
            "bash_exec": "💻",
            "web_search": "🔍",
            "web_fetch": "🌐",
        }
        labels = {
            "read_file": "文件读取",
            "edit_file": "编辑文件",
            "bash_exec": "命令调用",
            "web_search": "搜索请求",
            "web_fetch": "网页获取",
        }
        border_map = {
            "read_file": "green", "edit_file": "yellow",
            "bash_exec": "white", "web_search": "blue", "web_fetch": "blue",
        }
        icon = icons.get(tool_name, "🔧")
        label = labels.get(tool_name, "工具调用")
        bstyle = border_map.get(tool_name, "white")

        # ── Line 1: tool name (English + Chinese label) ──────────────
        line1 = f"[bold]{icon} {label}[/]  [dim]({tool_name})[/]"

        # ── Line 2: parameters (single line) ──────────────────────────
        param_parts = []
        for k, v in args.items():
            val_str = str(v)
            # For file tools, shorten to relative path
            if tool_name in ("read_file", "edit_file") and k in ("path", "file_path"):
                val_str = self._short_path(val_str)
            # For bash_exec, show the command
            if tool_name == "bash_exec" and k == "command":
                val_str = val_str.strip()
                # Truncate long commands
                if len(val_str) > 80:
                    val_str = val_str[:77] + "..."
            # Truncate long values
            if len(val_str) > 60:
                val_str = val_str[:57] + "..."
            param_parts.append(f"{k}={val_str}")
        line2 = " | ".join(param_parts) if param_parts else "(无参数)"

        # ── Line 3: result (single line, truncated) ───────────────────
        result_one_line = result.strip().replace("\n", " ").replace("\r", "")
        if len(result_one_line) > 100:
            result_one_line = result_one_line[:97] + "..."
        line3 = f"[dim]{result_one_line}[/]"

        # ── Build 3-line Panel ────────────────────────────────────────
        from rich.console import Group
        combined = Group(
            Text.from_markup(line1),
            Text.from_markup(f"  {line2}"),
            Text.from_markup(f"  {line3}"),
        )

        try:
            self._console.print(
                Panel(
                    combined,
                    box=box.SIMPLE,
                    border_style=bstyle,
                    width=self._width,
                    padding=(0, 1),
                )
            )
        except Exception:
            self._console.print(
                Panel(
                    Text(f"{line2}\n{result_one_line}"),
                    box=box.SIMPLE,
                    border_style=bstyle,
                    width=self._width,
                    padding=(0, 1),
                )
            )
        self._console.print()

        # ── Register collapsible section ─────────────────────────────
        rtype = (
            "syntax" if tool_name in ("bash_exec", "read_file")
            else "markdown" if tool_name == "web_search"
            else "text"
        )
        collapsible_content = f"{label} ({tool_name})\n参数: {line2}\n结果: {result}"
        self._collapsible.add_section(
            CollapsibleSection(
                title=f"{icon} {label} ({tool_name})",
                content=collapsible_content,
                border_style=bstyle,
                renderable_type=rtype,
                collapsed=True,
            )
        )

    # ── Model Thinking (light color, not persisted) ───────────────────

    def show_thinking(self, text: str):
        """Display the model's chain-of-thought reasoning in a light/dim style.

        This content is shown to the user for transparency but is NOT
        recorded in the session history (see ``callbacks.ToolCallCapture.on_llm_end``).
        """
        self._console.print(Text.from_markup(f"  [italic bright_black]💭 {text}[/]"))

    # ── Agent Reports ─────────────────────────────────────────────────

    def agent_report(self, agent_name: str, report: str):
        """Display the final report from an agent and register collapsible section (default expanded)."""
        style = "green" if agent_name == "coder" else "magenta"
        icon = "📝" if agent_name == "coder" else "🔍"
        label = "Coder Agent 报告" if agent_name == "coder" else "Reviewer Agent 审查意见"

        # Register collapsible section
        self._collapsible.add_section(
            CollapsibleSection(
                title=f"{icon} {label}",
                content=report,
                border_style=style,
                renderable_type="markdown",
                collapsed=False,
            )
        )

        # Also print to real-time console
        self._console.print(
            Panel(
                Markdown(report),
                box=box.ROUNDED,
                border_style=style,
                title=f"[bold]{icon} {label}[/]",
                width=self._width,
            )
        )
        self._console.print()

    # ── Review Verdict ────────────────────────────────────────────────

    def review_verdict(self, is_pass: bool, feedback: str = ""):
        """Display the review verdict and register collapsible section."""
        if is_pass:
            title = "🎉 审查通过"
            content = "✅ 审查通过！所有需求已实现，工作流完成。"
            bstyle = "green"
            collapsed = False  # Short verdict, show full
        else:
            title = "🔄 需要修复"
            content = f"❌ 审查未通过\n\n下一轮修复建议:\n{feedback}"
            bstyle = "red"
            collapsed = True

        # Register collapsible section
        self._collapsible.add_section(
            CollapsibleSection(
                title=title,
                content=content,
                border_style=bstyle,
                renderable_type="text",
                collapsed=collapsed,
            )
        )

        # Also print to real-time console (keep original styled display)
        panel = Panel(
            Text.from_markup(
                f"\n  [bold green]✅ 审查通过！[/]\n\n"
                f"  [dim]所有需求已实现，工作流完成。[/]\n"
                if is_pass else
                f"\n  [bold red]❌ 审查未通过[/]\n\n"
                f"  [yellow]下一轮修复建议:[/]\n"
                f"  [dim]{feedback}[/]\n"
            ),
            box=box.HEAVY,
            border_style=bstyle,
            title=f"[bold]{title}[/]",
            width=self._width,
        )
        self._console.print(panel)
        self._console.print()

    # ── Final Result ──────────────────────────────────────────────────

    def final_result(self, success: bool, coder_report: str, review_verdict: str,
                     total_turns: int, session_id: str):
        """Display the final workflow result (compact stats only)."""
        from rich.text import Text as RichText

        status_icon = "✅" if success else "⚠️"
        status_text = "成功" if success else "未完成"
        status_color = "green" if success else "yellow"

        # ── Compact statistics ───────────────────────────────────────
        coder_k_len = f"{len(coder_report) / 1000:.1f}K"
        stats_text = (
            f"[bold]状态:[/] [{status_color}]{status_icon} {status_text}[/]  │  "
            f"[bold]轮次:[/] [white]{total_turns}[/]  │  "
            f"[bold]会话ID:[/] [dim]{session_id}[/]  │  "
            f"[bold]Coder上下文:[/] [cyan]{coder_k_len}[/]"
        )
        self._console.print()
        self._console.print(
            Panel(
                RichText.from_markup(stats_text),
                box=box.SIMPLE,
                border_style=status_color,
                title="[bold]📊 统计信息[/]",
                width=self._width,
                padding=(0, 1),
            )
        )
        self._console.print()

    # ── Utilities ─────────────────────────────────────────────────────

    def error(self, message: str):
        """Display an error message."""
        self._console.print(
            Panel(
                Text(message, style="red"),
                box=box.SIMPLE,
                border_style="red",
                title="[bold red]❌ 错误[/]",
                width=self._width,
            )
        )

    def separator(self):
        """Print a simple horizontal rule."""
        self._console.print(Rule(style="dim"))

    def print(self, text: str = ""):
        """Plain print passthrough."""
        self._console.print(text)
