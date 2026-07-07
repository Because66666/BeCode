# Hello World 输出 — 实现方案

## 需求描述
实现一个输出 "hello world" 的 Python 代码。

## 功能需求 (FR)
- FR1: 创建 `hello_world.py`，运行后直接输出 `hello world`
- FR2: 补充 `main.py` 的 `--hello` 命令行参数，运行 `python main.py --hello` 输出 `hello world`

## 非功能需求 (NFR)
- NFR1: 无需外部依赖，纯 Python 标准库
- NFR2: 代码简洁，单文件可执行

## 验收条件 (AC)
- AC1: `python hello_world.py` 输出 `hello world`
- AC2: `python main.py --hello` 输出 `hello world` 后立即退出
