"""CollapsibleDisplay — Section aggregation for the Agent Console.

Provides a simple section storage where output sections
(file contents, command output, agent reports, review verdicts) are
registered for potential rendering.  No interactive / keyboard features.

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - 完全移除了 threading、keyboard 依赖、         ║
║    _keyboard_listener()、start_interactive()、   ║
║    toggle_last()/toggle_all()、COLLAPSE_HINT     ║
║    以及 rich.live.Live 的使用。                  ║
║  - CollapsibleDisplay 简化为纯 section 存储容器， ║
║    不再依赖 keyboard、threading、rich.live.Live。 ║
╚══════════════════════════════════════════════════╝
"""

from typing import Any, Optional

from rich.console import Console as RichConsole
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.markdown import Markdown
from rich import box


# ── Globals ─────────────────────────────────────────────────────────────

_display: Optional["CollapsibleDisplay"] = None


# ── Section data ────────────────────────────────────────────────────────


class CollapsibleSection:
    """A single output section.

    Attributes:
        section_id: Unique identifier (auto-incremented).
        title: Panel title (rich markup).
        content: The full text content.
        border_style: Rich border colour name.
        collapsed: Whether the section is currently collapsed.
        renderable_type: How to render the content (text/syntax/markdown).
    """

    _counter = 0

    def __init__(
        self,
        title: str,
        content: str,
        border_style: str = "white",
        renderable_type: str = "text",
        collapsed: bool = True,
    ):
        CollapsibleSection._counter += 1
        self.section_id = CollapsibleSection._counter
        self.title = title
        self.content = content
        self.border_style = border_style
        self.renderable_type = renderable_type
        self.collapsed = collapsed

    @property
    def line_count(self) -> int:
        """Approximate number of lines in the content."""
        return self.content.count("\n") + 1

    def _make_renderable(self, text: str) -> Any:
        """Convert plain text to a Rich renderable based on type."""
        if self.renderable_type == "syntax":
            return Syntax(text, "text", theme="monokai", word_wrap=True)
        if self.renderable_type == "markdown":
            return Markdown(text)
        return Text(text)

    def render(self, width: int) -> Panel:
        """Render this section as a Rich Panel."""
        rendered = self._make_renderable(self.content)
        return Panel(
            rendered,
            box=box.SIMPLE,
            border_style=self.border_style,
            title=f"[bold]{self.title}[/]",
            width=width,
            padding=(0, 1),
        )


# ── Display manager ────────────────────────────────────────────────────


class CollapsibleDisplay:
    """Manages a list of output sections (no interactive features)."""

    def __init__(self, console: Optional[RichConsole] = None):
        self._console = console or RichConsole(force_terminal=True, color_system="truecolor")
        self._sections: list[CollapsibleSection] = []
        self._width = 100

    # ── Public API ─────────────────────────────────────────────────────

    def add_section(self, section: CollapsibleSection) -> None:
        """Register a new section."""
        self._sections.append(section)

    def add_agent_report(self, agent_name: str, content: str) -> None:
        """Convenience: add an agent report section (default expanded)."""
        style = "green" if agent_name == "coder" else "magenta"
        icon = "📝" if agent_name == "coder" else "🔍"
        label = "Coder Agent 报告" if agent_name == "coder" else "Reviewer Agent 审查意见"
        self.add_section(
            CollapsibleSection(
                title=f"{icon} {label}",
                content=content,
                border_style=style,
                renderable_type="markdown",
                collapsed=False,
            )
        )

    def add_review_verdict(self, is_pass: bool, feedback: str = "") -> None:
        """Convenience: add a review verdict section."""
        if is_pass:
            title = "🎉 审查通过"
            content = "✅ 审查通过！所有需求已实现，工作流完成。"
            bstyle = "green"
            collapsed = False
        else:
            title = "🔄 需要修复"
            content = f"❌ 审查未通过\n\n下一轮修复建议:\n{feedback}"
            bstyle = "red"
            collapsed = True
        self.add_section(
            CollapsibleSection(
                title=title,
                content=content,
                border_style=bstyle,
                renderable_type="text",
                collapsed=collapsed,
            )
        )


# ── Singleton helper ───────────────────────────────────────────────────


def get_display() -> CollapsibleDisplay:
    """Get or create the global CollapsibleDisplay singleton."""
    global _display
    if _display is None:
        _display = CollapsibleDisplay()
    return _display


def reset_display() -> None:
    """Reset the singleton (useful for testing)."""
    global _display
    _display = None
    CollapsibleSection._counter = 0
