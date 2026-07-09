"""LLM client wrapper — provides both chat and raw-prompt completion.

Uses the OpenAI-compatible protocol so it works with OpenAI, vLLM,
OneAPI, Ollama (with openai compat), etc.
"""

from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.core.config import settings


def build_chat_model(
    temperature: float = 0.0,
    model: Optional[str] = None,
    max_retries: int = 2,
    timeout: int = 30,
) -> ChatOpenAI:
    """Build a ChatOpenAI instance from env / overrides."""
    return ChatOpenAI(
        model=model or settings.openai_model,
        temperature=temperature,
        max_retries=max_retries,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
        timeout=timeout,
    )


def clean_call(
    model: BaseChatModel,
    messages: list[BaseMessage],
    *,
    system_prompt: Optional[str] = None,
    suppress_callbacks: bool = True,
) -> str:
    """Send messages and return the content string.

    Optionally prepends a system message.

    Args:
        model: The chat model to invoke.
        messages: The messages to send.
        system_prompt: Optional system prompt to prepend.
        suppress_callbacks: If True, pass ``callbacks=[]`` to
            ``model.invoke()`` so that any inherited LangChain
            callbacks (e.g. from a parent agent run) are NOT
            propagated to this LLM call.  This is important for
            internal/infrastructure calls (e.g. bash guard safety
            review) whose output should NOT appear as agent
            "chain-of-thought" in the UI.
    """
    msgs = list(messages)
    if system_prompt:
        msgs = [SystemMessage(content=system_prompt)] + msgs
    config = {}
    if suppress_callbacks:
        config["callbacks"] = []
    result = model.invoke(msgs, config=config)
    return result.content if hasattr(result, "content") else str(result)


def clean_prompt_call(
    prompt: str,
    *,
    system_prompt: Optional[str] = None,
    temperature: float = 0.0,
    model: Optional[str] = None,
) -> str:
    """One-shot a plain-text prompt (no history).  Used by BashGuard."""
    llm = build_chat_model(temperature=temperature, model=model)
    return clean_call(llm, [HumanMessage(content=prompt)], system_prompt=system_prompt)


def summarize_completion(
    requirement: str,
    coder_report: str,
    model: Optional[str] = None,
) -> str:
    """Generate a one-sentence summary of what was accomplished.

    Args:
        requirement: The original user requirement.
        coder_report: The Coder Agent's final report.
        model: Optional model override.

    Returns:
        A concise one-line Chinese summary (≤ 80 characters).
    """
    prompt = (
        f"请用一句简短的话（不超过 80 字）总结以下任务完成了什么，"
        f"语气平实客观。\n\n用户需求:\n{requirement[:500]}\n\n"
        f"实现报告:\n{coder_report[:1000]}"
    )
    llm = build_chat_model(temperature=0.3, model=model)
    result = clean_call(llm, [HumanMessage(content=prompt)])
    # Clean up quotes, newlines, etc.
    summary = result.strip().strip('"').strip("'").strip()
    # Trim to one line
    summary = summary.split("\n")[0].strip()
    if len(summary) > 120:
        summary = summary[:117] + "..."
    return summary
