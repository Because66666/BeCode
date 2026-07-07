#!/usr/bin/env python3
"""BeCode CLI entry point for PyInstaller packaged executable.

This file is the main entry point when packaged as an exe.
It simply delegates to main.py's main() function.
"""

import sys
import os

# Ensure the package root is on sys.path (needed for PyInstaller)
_pkg_dir = os.path.dirname(os.path.abspath(__file__))
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from main import main

if __name__ == "__main__":
    main()
