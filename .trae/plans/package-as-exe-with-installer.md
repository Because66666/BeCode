# Plan: 打包 BeCode 为 exe + 安装程序

## 需求

1. 将 Python 项目打包为 exe (PyInstaller)
2. 运行时文件存放在 `~/.becode/` 下（sessions、.env 配置等）
3. 交付安装程序 exe，允许用户选择安装路径
4. 安装时设置环境变量 PATH，用户可在任意路径使用 `becode` 命令

## 实现方案

### FR (功能需求)

| ID | 描述 | 优先级 |
|----|------|--------|
| FR-1 | 数据目录迁移：所有运行时文件（sessions、.env）从项目目录迁移到 `~/.becode/` | P0 |
| FR-2 | PyInstaller 打包：生成 `becode.exe` 单目录可执行文件 | P0 |
| FR-3 | 安装程序：使用 Inno Setup 制作 `BeCode_Setup_v1.0.0.exe` | P0 |
| FR-4 | PATH 环境变量：安装时自动将安装目录加入系统 PATH | P0 |
| FR-5 | 首次运行配置：`~/.becode/.env` 不存在时自动创建 | P1 |

### NFR (非功能需求)

| ID | 描述 | 优先级 |
|----|------|--------|
| NFR-1 | 兼容 Windows 10/11 | P0 |
| NFR-2 | 安装程序 ≤ 50MB | P1 |
| NFR-3 | 卸载时自动清理 PATH 和文件 | P1 |

### AC (验收标准)

- [x] `becode --version` 可执行并输出版本号
- [x] `~/.becode/` 目录自动创建
- [x] `~/.becode/.env` 首次运行时自动生成
- [x] `~/.becode/sessions/` 存放会话 JSON 文件
- [x] 安装程序允许用户选择安装路径
- [x] 安装后 `becode` 命令在任意路径可用

## 修改的文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/core/config.py` | 修改 | 新增 BECODE_HOME/SESSION_DIR 常量，修改 .env 加载逻辑 |
| `src/core/session_store.py` | 修改 | 使用 SESSION_DIR 替代 settings.session_dir |
| `main.py` | 修改 | 新增 --version 参数，更新路径显示，优化无参数时的行为 |
| `becode_cli.py` | 新建 | PyInstaller 入口脚本 |
| `installer/becode_setup.iss` | 新建 | Inno Setup 安装脚本 |
| `.gitignore` | 修改 | 添加构建产物忽略规则 |

## 构建产物

- `dist/becode/becode.exe` — 可执行文件 (~16MB)
- `dist/BeCode_Setup_v1.0.0.exe` — 安装程序 (~32MB)
