@echo off
chcp 65001 >nul
title BeCode 一键打包工具

:: ============================================
:: build_installer.bat — BeCode 一键打包脚本
:: 功能：
::   1. 自动迭代版本号（0~9 循环，向上进位）
::   2. 运行 PyInstaller 打包 .exe
::   3. 运行 Inno Setup 编译器生成安装包
::   4. 输出文件：dist\install.exe
::
:: ╔══════════════════════════════════════════════════╗
:: ║  Learned Workspace Facts                        ║
:: ║  - 自动读取 installer/becode_setup.iss 中的    ║
:: ║    版本号，按 0~9 进位规则递增                  ║
:: ║  - 依次执行 PyInstaller + Inno Setup ISCC       ║
:: ║  - 前置依赖检测：自动搜索 ISCC.exe 常见路径    ║
:: ╚══════════════════════════════════════════════════╝
:: ============================================

setlocal enabledelayedexpansion

:: ---------- 0. 检测前置依赖 ----------
echo [INFO] 检测前置依赖...

:: 0a. 检测 PyInstaller
where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 pyinstaller，请先安装：pip install pyinstaller
    pause
    exit /b 1
)
echo [OK] PyInstaller 已就绪

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

:: ---------- 1. 读取当前版本 ----------
set ISS_FILE=installer\becode_setup.iss
if not exist %ISS_FILE% (
    echo [ERROR] 找不到 %ISS_FILE%
    pause
    exit /b 1
)

:: 提取版本号行
for /f "tokens=3" %%a in ('findstr /b "#define MyAppVersion" "%ISS_FILE%"') do (
    set VERSION_LINE=%%a
)
:: 去掉引号
set OLD_VERSION=%VERSION_LINE:"=%
echo [INFO] 当前版本: %OLD_VERSION%

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

:: ---------- 3. 更新 .iss 文件中的版本号 ----------
:: 使用 PowerShell 正则替换（避免批处理特殊字符问题）
powershell -NoProfile -Command ^
    "(Get-Content '%ISS_FILE%') -replace '#define MyAppVersion \"%OLD_VERSION%\"', '#define MyAppVersion \"%NEW_VERSION%\"' | Set-Content '%ISS_FILE%' -Encoding UTF8"
if errorlevel 1 (
    echo [ERROR] 版本号更新失败
    pause
    exit /b 1
)
echo [OK] 版本号已更新为 %NEW_VERSION%

:: ---------- 4. 运行 PyInstaller 打包 ----------
echo [INFO] 正在运行 PyInstaller 打包...
echo [INFO] 执行: pyinstaller becode.spec --noconfirm --clean
call pyinstaller becode.spec --noconfirm --clean
if errorlevel 1 (
    echo [ERROR] PyInstaller 打包失败！请查看上方错误信息。
    pause
    exit /b 1
)
echo [OK] PyInstaller 打包完成

:: ---------- 5. 运行 Inno Setup 生成安装包 ----------
echo [INFO] 正在生成安装包...
echo [INFO] 执行: "%ISCC_PATH%" "%ISS_FILE%"
"%ISCC_PATH%" "%ISS_FILE%"
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