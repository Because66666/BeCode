# Plan: Interactive Dialogue Mode  
  
## 目标  
- 无参数运行（双击）进入交互式对话模式  
- 每次任务完成后显示 LLM 生成的一句话摘要（灰色斜体）  
- 摘要写入上下文作为后续任务的背景提示  
- Ctrl+C 中断处理：无输出→回输入态+预填；有输出→保留继续  
  
## 修改文件清单  
- main.py: 交互式循环 + SIGINT 处理  
- src/ui/console.py: show_summary / interactive_prompt / show_interrupt_message  
- src/core/llm_client.py: summarize_completion  
- src/core/orchestrator.py: run_interactive 方法  
  
## Ctrl+C 策略  
- 输入阶段中断 → should_prefill=True → 下一次提示时显示上次输入作为参考  
- Agent 执行中无正式输出 → 返回输入态，预填上次输入  
- Agent 执行中有正式输出 → 保留输出到上下文，继续输入新需求  
