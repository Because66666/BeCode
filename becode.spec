# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['becode_cli.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('src\\tools\\prompt_platform_windows.md', 'src\\tools'),
        ('src\\tools\\prompt_platform_darwin.md', 'src\\tools'),
        ('version', '.'),
    ],
    hiddenimports=['src', 'src.core', 'src.core.config', 'src.core.orchestrator', 'src.core.llm_client', 'src.core.session_store', 'src.agents', 'src.agents.coder_agent', 'src.agents.reviewer_agent', 'src.tools', 'src.tools.tools', 'src.tools.bash_guard', 'src.tools.web_search', 'src.ui', 'src.ui.console', 'src.ui.callbacks', 'src.ui.collapsible'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PySide6', 'PySide2', 'tkinter', 'matplotlib', 'IPython', 'sphinx', 'docutils', 'pytest', 'jedi', 'black', 'nbformat'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='becode',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=r'assets\favicon_256x256.ico',
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='becode',
)
