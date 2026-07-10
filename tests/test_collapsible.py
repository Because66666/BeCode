"""Tests for src.ui.collapsible — CollapsibleSection, CollapsibleDisplay."""

import pytest
from rich.text import Text
from rich.panel import Panel

from src.ui.collapsible import (
    CollapsibleSection,
    CollapsibleDisplay,
    get_display,
    reset_display,
)


class TestCollapsibleSection:
    """Verify CollapsibleSection creation and properties."""

    def test_auto_increment_id(self):
        s1 = CollapsibleSection("Title 1", "Content 1")
        s2 = CollapsibleSection("Title 2", "Content 2")
        assert s2.section_id == s1.section_id + 1

    def test_line_count(self):
        section = CollapsibleSection("Test", "line1\nline2\nline3")
        assert section.line_count == 3

    def test_render_returns_panel(self):
        section = CollapsibleSection("Test", "Content")
        panel = section.render(width=80)
        assert isinstance(panel, Panel)

    def test_render_markdown_type(self):
        section = CollapsibleSection("Test", "# Hello", renderable_type="markdown")
        panel = section.render(width=80)
        assert isinstance(panel, Panel)

    def test_render_syntax_type(self):
        section = CollapsibleSection("Test", "print('hi')", renderable_type="syntax")
        panel = section.render(width=80)
        assert isinstance(panel, Panel)

    def test_default_collapsed(self):
        section = CollapsibleSection("Test", "Content")
        assert section.collapsed is True

    def test_collapsed_false(self):
        section = CollapsibleSection("Test", "Content", collapsed=False)
        assert section.collapsed is False


class TestCollapsibleDisplay:
    """Verify CollapsibleDisplay section aggregation."""

    def setup_method(self):
        reset_display()

    def test_add_section(self):
        display = CollapsibleDisplay()
        display.add_section(CollapsibleSection("Test", "Content"))
        assert len(display._sections) == 1

    def test_add_agent_report(self):
        display = CollapsibleDisplay()
        display.add_agent_report("coder", "Coder report")
        assert len(display._sections) == 1
        assert "Coder" in display._sections[0].title

    def test_add_review_verdict_pass(self):
        display = CollapsibleDisplay()
        display.add_review_verdict(is_pass=True)
        assert len(display._sections) == 1
        assert "通过" in display._sections[0].title

    def test_add_review_verdict_fail(self):
        display = CollapsibleDisplay()
        display.add_review_verdict(is_pass=False, feedback="Fix it")
        assert len(display._sections) == 1
        assert "修复" in display._sections[0].title


class TestGetDisplay:
    """Verify singleton access."""

    def setup_method(self):
        reset_display()

    def test_get_display_returns_instance(self):
        d = get_display()
        assert isinstance(d, CollapsibleDisplay)

    def test_get_display_is_singleton(self):
        d1 = get_display()
        d2 = get_display()
        assert d1 is d2

    def test_reset_display(self):
        d1 = get_display()
        reset_display()
        d2 = get_display()
        assert d1 is not d2
