"""ToolCallCapture — LangChain callback handler.

Captures tool invocations during agent execution and displays them
in real-time through the AgentConsole UI.

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - content='' 显示问题修复: LangChain 0.3+ 的   ║
║    on_tool_end callback 传递的是 ToolMessage     ║
║    对象而非纯字符串。修复: _extract_tool_output() ║
║    函数优先使用 .content 属性。                  ║
║  - ToolCallCapture 新增 _tool_calls 累加器和     ║
║    get_tool_calls() 方法，在 on_tool_start 中    ║
║    记录工具名和参数（不含响应）。                 ║
║  - on_llm_end 新增: 捕获 LLM 的 chain-of-thought ║
║    推理文本，通过 console.show_thinking() 以浅色   ║
║    字体 (italic bright_black) 展示给用户。         ║
║    此思考内容不会添加到 _tool_calls，因此不会       ║
║    持久化到 session JSON 中。                      ║
╚══════════════════════════════════════════════════╝
"""

import logging
from typing import Any, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from src.ui.console import get_console

logger = logging.getLogger(__name__)


def _extract_tool_output(output: Any) -> str:
    """Extract the actual text content from a tool's output.

    In LangChain 0.3+, ``on_tool_end`` may receive a ``ToolMessage``
    object (when called from an agent context) rather than a plain string.
    Calling ``str()`` on such a message yields:
        content='...' tool_call_id='...'
    which is the ``content='...'`` style the user reported.

    This helper extracts ``.content`` when available, falling back to
    ``str(output)`` for plain strings/other types.
    """
    if output is None:
        return "(无输出)"

    # If it's a message-like object with a .content attribute, use that
    if hasattr(output, "content"):
        return str(output.content) if output.content else "(无输出)"

    return str(output)


class ToolCallCapture(BaseCallbackHandler):
    """Callback handler that captures agent thought process and tool calls.

    Displays:
    - Agent chain-of-thought (when available)
    - Tool calls with arguments
    - Tool results

    Also records tool invocations (name + args, without responses) for
    session persistence via :meth:`get_tool_calls`.
    """

    def __init__(self, agent_name: str = "coder"):
        self.agent_name = agent_name
        self._console = get_console()
        self._current_tool: Optional[str] = None
        self._current_tool_args: Optional[dict] = None
        # Accumulated tool calls for session persistence (no responses).
        self._tool_calls: list[dict[str, Any]] = []

    # ── Public accessors ─────────────────────────────────────────────

    def get_tool_calls(self) -> list[dict[str, Any]]:
        """Return the list of tool invocations captured so far.

        Each entry: ``{"tool": str, "args": dict}``
        """
        return list(self._tool_calls)

    def clear_tool_calls(self):
        """Reset the captured tool-call list."""
        self._tool_calls.clear()

    # ── Tool lifecycle ────────────────────────────────────────────────

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        inputs: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """Called when a tool starts executing."""
        tool_name = serialized.get("name", "unknown_tool")

        # Extract tool arguments
        args = {}
        if inputs:
            args = {k: str(v) for k, v in inputs.items()}
        elif input_str:
            args = {"input": input_str[:200]}

        self._current_tool = tool_name
        self._current_tool_args = args

        # Record the tool call for session persistence (without response).
        self._tool_calls.append({"tool": tool_name, "args": dict(args)})

        # Don't print anything yet -- wait for result to merge.
        return None

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> Any:
        """Called when a tool finishes executing.

        Displays a single merged Panel showing both the tool invocation
        (args) and its result, eliminating the previous start/end split
        that caused duplicate output.
        """
        tool_name = self._current_tool or "unknown_tool"
        args = self._current_tool_args or {}
        result_str = _extract_tool_output(output)

        self._console.tool_call(tool_name, args, result_str)

        self._current_tool = None
        self._current_tool_args = None
        return None

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> Any:
        """Called when a tool raises an error."""
        tool_name = self._current_tool or "unknown_tool"
        self._console.error(f"工具 {tool_name} 出错: {error}")
        self._current_tool = None
        self._current_tool_args = None
        return None

    # ── LLM / Chain-of-thought ────────────────────────────────────────

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """Called when LLM starts — signals agent thinking."""
        # Only show thinking at the start of a chain (not for each tool's
        # underlying LLM call) by checking if there's no parent run.
        if parent_run_id is None:
            self._console.agent_thinking(self.agent_name)
        return None

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> Any:
        """Called when LLM finishes generating.

        Extracts the model's chain-of-thought / reasoning text from the
        response and displays it in a light/dim color via the console.

        IMPORTANT: This thinking content is displayed for user transparency
        but is deliberately NOT added to ``self._tool_calls``, so it will
        NOT be persisted to the session history.  Only explicit tool calls
        (captured in ``on_tool_start``) are recorded in the session.
        """
        try:
            # Extract text content from the LLM response.
            # In LangChain 0.3+, ``LLMResult.generations`` is a list of lists
            # of ``ChatGeneration`` objects (for chat models). Each generation
            # has a ``.message`` attribute (``AIMessage``) with ``.content``.
            # Plain text models use ``.text`` instead.
            thought_parts: list[str] = []
            generations = getattr(response, "generations", [])
            for gen_list in generations:
                for gen in gen_list:
                    # ChatGeneration → has .message (AIMessage)
                    msg = getattr(gen, "message", None)
                    if msg is not None:
                        content = getattr(msg, "content", None) or ""
                        if content.strip():
                            thought_parts.append(content.strip())
                    else:
                        # Plain Generation → has .text
                        text = getattr(gen, "text", None) or ""
                        if text.strip():
                            thought_parts.append(text.strip())

            if thought_parts:
                combined = "\n".join(thought_parts).strip()
                if combined:
                    self._console.show_thinking(combined)

        except Exception:
            # Silently ignore — thinking display is non-critical
            pass

        # NOTE: We do NOT add anything to self._tool_calls here.
        # Only on_tool_start records tool invocations for session persistence.
        return None

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """Called when an agent chain starts."""
        if parent_run_id is None:
            self._console.agent_thinking(self.agent_name)
        return None