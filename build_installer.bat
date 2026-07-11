@echo off
chcp 65001 >nul
title BeCode 一键打包工具

:: ============================================
:: build_installer.bat — BeCode 一键打包脚本
:: 功能：
::   1. 从 version 文件读取版本号并自动递增（0~9 循环，向上进位）
::   2. 运行 PyInstaller 打包 .exe
::   3. 将新版本号传给 ISCC（通过 /dMyAppVersion=...）生成安装包
::   4. 输出文件：dist\install.exe
::
:: ╔══════════════════════════════════════════════════╗
:: ║  Learned Workspace Facts                        ║
:: ║  - 版本号存储在项目根目录的 version 文件中      ║
:: ║  - 通过 ISCC 的 /d 命令行参数传入 .iss 脚本     ║
:: ║  - 版本递增规则：X.Y.Z 每位 0~9 循环进位        ║
:: ║  - 依次执行 PyInstaller + Inno Setup ISCC       ║
:: ║  - 前置依赖检测：自动搜索 ISCC.exe 常见路径    ║
:: ╚══════════════════════════════════════════════════╝
:: ============================================

setlocal enabledelayedexpansion

:: ---------- 0. 检测前置依赖 ----------
echo [INFO] 检测前置依赖...

:: 0a. 检测局部虚拟环境中的 PyInstaller
set VENV_DIR=%~dp0becode_venv
if not exist "%VENV_DIR%\Scripts\pyinstaller.exe" (
    echo [ERROR] 未找到虚拟环境中的 pyinstaller
    echo         预期路径: %VENV_DIR%\Scripts\pyinstaller.exe
    echo         请先激活 becode_venv 并安装依赖: pip install -r requirements.txt
    pause
    exit /b 1
)
echo [OK] 虚拟环境 PyInstaller 已就绪: %VENV_DIR%\Scripts\pyinstaller.exe
set PYINSTALLER="%VENV_DIR%\Scripts\pyinstaller.exe"

:: 0b. 检测 Inno Setup 编译器 (ISCC)
set ISCC_PATH=
for %%P in (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    "C:\Program Files\Inno Setup 6\ISCC.exe"
    "C:\Program Files (x86)\Inno Setup 5\ISCC.exe"
    "C:\Program Files\Inno Setup 5\ISCC.exe"
) do (
    if exist %%P (
        set ISCC_PATH=%%~fP
        goto :ISCC_FOUND
    )
)
:ISCC_FOUND
if not defined ISCC_PATH (
    :: 尝试从 PATH 中查找
    where ISCC.exe >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] 未找到 Inno Setup 编译器 (ISCC.exe)
        echo 请安装 Inno Setup：https://jrsoftware.org/isdl.php
        pause
        exit /b 1
    ) else (
        set ISCC_PATH=ISCC.exe
    )
)
echo [OK] Inno Setup 已就绪: %ISCC_PATH%

:: ---------- 1. 从 version 文件读取当前版本 ----------
set VERSION_FILE=%~dp0version
if not exist "%VERSION_FILE%" (
    echo [ERROR] 找不到版本文件: %VERSION_FILE%
    echo         请创建 version 文件，内容仅为版本号字符串（如 1.0.0）
    pause
    exit /b 1
)

:: 读取版本号（仅第一行，去除空白字符）
set /p OLD_VERSION=<"%VERSION_FILE%"
:: 去除首尾空白
set OLD_VERSION=%OLD_VERSION: =%
echo [INFO] 当前版本: [%OLD_VERSION%]

:: 验证版本号格式
echo %OLD_VERSION%| findstr /r "^[0-9]\.[0-9]\.[0-9]$" >nul
if errorlevel 1 (
    echo [ERROR] 版本号格式无效，应为 X.Y.Z（如 1.0.0）
    echo         当前内容: [%OLD_VERSION%]
    pause
    exit /b 1
)

:: ---------- 2. 解析并递增版本号 ----------
:: 格式: X.Y.Z  (每位 0-9 整数)
for /f "tokens=1-3 delims=." %%a in ("%OLD_VERSION%") do (
    set V1=%%a
    set V2=%%b
    set V3=%%c
)

set /a V3+=1
if !V3! gtr 9 (
    set V3=0
    set /a V2+=1
    if !V2! gtr 9 (
        set V2=0
        set /a V1+=1
        if !V1! gtr 9 (
            set V1=0
        )
    )
)

set NEW_VERSION=!V1!.!V2!.!V3!
echo [INFO] 新版本: %NEW_VERSION%

:: ---------- 3. 将新版本号写回 version 文件 ----------
> "%VERSION_FILE%" echo %NEW_VERSION%
echo [OK] 版本文件已更新为 %NEW_VERSION%

:: 设置 ISS 文件路径（供后续步骤使用）
set ISS_FILE=installer\becode_setup.iss
if not exist %ISS_FILE% (
    echo [ERROR] 找不到 %ISS_FILE%
    pause
    exit /b 1
)

:: ---------- 4. 运行 PyInstaller 打包 ----------
echo [INFO] 正在运行 PyInstaller 打包...
echo [INFO] 执行: %PYINSTALLER% becode.spec --noconfirm 
call %PYINSTALLER% becode.spec --noconfirm 
if errorlevel 1 (
    echo [ERROR] PyInstaller 打包失败！请查看上方错误信息。
    pause
    exit /b 1
)
echo [OK] PyInstaller 打包完成

:: ---------- 5. 运行 Inno Setup 生成安装包 ----------
echo [INFO] 正在生成安装包...
echo [INFO] 执行: "%ISCC_PATH%" /dMyAppVersion="%NEW_VERSION%" "%ISS_FILE%"
"%ISCC_PATH%" /dMyAppVersion="%NEW_VERSION%" "%ISS_FILE%"
if errorlevel 1 (
    echo [ERROR] Inno Setup 打包失败！请查看上方错误信息。
    pause
    exit /b 1
)
echo [OK] 安装包生成完成

:: ---------- 6. 复制为 install.exe ----------
if exist "dist\BeCode_Setup_v%NEW_VERSION%.exe" (
    copy /Y "dist\BeCode_Setup_v%NEW_VERSION%.exe" "dist\install.exe" >nul
    echo [OK] 已复制为 dist\install.exe
) else (
    echo [WARN] 未找到安装包文件，可能由 ISCC 输出到其他位置
    dir /s /b *.exe 2>nul | findstr /i setup
)

:: ---------- 7. 完成 ----------
echo ============================================
echo  打包完成！
echo  版本: %OLD_VERSION% → %NEW_VERSION%
echo  安装包: dist\BeCode_Setup_v%NEW_VERSION%.exe
echo  别名:   dist\install.exe
echo ============================================
pause