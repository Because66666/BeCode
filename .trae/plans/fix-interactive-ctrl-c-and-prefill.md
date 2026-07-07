# Plan: Fix Interactive Mode Ctrl+C Handling & Editable Prefill

## 目标
修复交互式对话模式的 Ctrl+C 中断处理，实现可编辑的预填输入。

## 修改文件
1. **main.py**
   - 添加 `result: Optional[dict] = None` 初始化
   - 修改第 131 行为 `if _has_formal_output and result is not None:`
   - 将 `_has_formal_output` 追踪逻辑移入 orchestrator

2. **src/core/orchestrator.py**
   - `run_interactive()` 改造：通过捕获 KeyboardInterrupt 并返回 `interrupted` 状态和 `has_formal_output` 标记
   - 替换全局 `_has_formal_output` 的依赖，改为返回值传递

3. **src/ui/console.py**
   - `interactive_prompt()` 实现平台相关的可编辑预填输入：
     - Windows: 使用 `ctypes.windll.kernel32.WriteConsoleInput` 注入按键事件
     - Unix/macOS: 使用 `readline.set_startup_hook` + `insert_text` 预填
   - 预填文本在输入框中出现且光标在末尾，用户可直接编辑

4. **CLAUDE.md**
   - 更新 Learned Workspace Facts

## Ctrl+C 策略（修复后）
- 输入阶段 Ctrl+C → `should_prefill=True` → 下次输入时预填上次输入（可编辑）
- 执行中无正式输出 Ctrl+C → 回输入态 + 预填上次输入
- 执行中有正式输出 Ctrl+C → 保留输出到上下文，继续输入
