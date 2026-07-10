"""Tests for main.py — CLI argument parsing and mode dispatch."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestArgumentParsing:
    """Verify argument parser handles various inputs."""

    def test_hello_flag(self):
        """--hello should print and exit."""
        from main import main
        with patch.object(sys, "argv", ["becode", "--hello"]):
            with patch("builtins.print") as mock_print:
                with pytest.raises(SystemExit) as exc:
                    main()
                assert exc.value.code == 0
                mock_print.assert_any_call("hello world test")

    def test_version_flag(self):
        """--version should print version info and exit."""
        from main import main
        with patch.object(sys, "argv", ["becode", "--version"]):
            with patch("builtins.print") as mock_print:
                with pytest.raises(SystemExit) as exc:
                    main()
                assert exc.value.code == 0
                # Should print version
                version_call = [c for c in mock_print.call_args_list if "v" in str(c) and "BeCode" in str(c)]
                assert version_call

    def test_execute_exit(self):
        """-e .exit should exit cleanly."""
        from main import main
        with patch.object(sys, "argv", ["becode", "-e", ".exit"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0

    def test_execute_unknown(self):
        """-e with unknown command should exit with code 1."""
        from main import main
        with patch.object(sys, "argv", ["becode", "-e", "badcommand"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1

    def test_file_not_found(self):
        """--file with nonexistent path should exit with error."""
        from main import main
        with patch.object(sys, "argv", ["becode", "--file", "/nonexistent/req.txt"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1

    def test_requirement_passed_directly(self):
        """Positional arg should be used as requirement."""
        from main import main
        with patch.object(sys, "argv", ["becode", "Write a test"]):
            with patch("main.single_shot_mode") as mock_single:
                with patch("main.Path.cwd") as mock_cwd:
                    mock_cwd.return_value = Path(".")
                    main()
                    mock_single.assert_called_once()
                    args, _ = mock_single.call_args
                    assert args[0] == "Write a test"


class TestSingleShotMode:
    """Verify single_shot_mode flow."""

    @patch("main.single_shot_mode")
    @patch("main.Path.cwd")
    def test_with_requirement(self, mock_cwd, mock_single):
        mock_cwd.return_value = Path(".")
        from main import main
        with patch.object(sys, "argv", ["becode", "Write tests"]):
            main()
            mock_single.assert_called_once()


class TestInteractiveMode:
    """Verify interactive_mode dispatch."""

    @patch("main.interactive_mode")
    @patch("main.Path.cwd")
    def test_no_args_enters_interactive(self, mock_cwd, mock_interactive):
        mock_cwd.return_value = Path(".")
        from main import main
        with patch.object(sys, "argv", ["becode"]):
            main()
            mock_interactive.assert_called_once()
