# Plan: 添加 --hello 命令行参数打印 "hello world test"

## 需求概述
在 BeCode CLI 中添加 `--hello` 参数，运行后打印 "hello world test"。

## 实现方案
1. 在 `main.py` 的 `ArgumentParser` 中新增 `--hello` 互斥参数
2. 在 `main()` 中优先处理 `--hello` 分支，打印后退出

## 文件变更
- `main.py` — 新增 `--hello` 参数解析与处理逻辑

## 验收标准 (AC)
- [x] 运行 `python main.py --hello` 输出 "hello world test"
- [x] 不影响现有参数（requirement, --file, --version, --model, --max-iterations）
- [x] 不破坏现有单次运行和交互模式
