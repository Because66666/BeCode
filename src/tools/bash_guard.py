"""Bash command security guard — dual check: static rules + LLM review.

Architecture
────────────
1. Rule layer — regex blacklist for obviously dangerous commands.
2. LLM layer — one-shot call to a clean (stateless) LLM context that
   judges the command string semantically.

If EITHER layer rejects, the command is blocked.

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - BASH_GUARD_LLM_DISABLED=1 环境变量可跳过     ║
║    LLM 审查层（用于测试或无 API Key 环境）。     ║
║  - LLM 审查调用通过 clean_prompt_call →          ║
║    clean_call(suppress_callbacks=True) 完成，     ║
║    阻止父级 agent 的 ToolCallCapture 向此         ║
║    基础设施调用传播，因此安全模型的输出不会       ║
║    被误渲染为 agent 的"思考过程"(show_thinking)。 ║
║  - bash_exec 会在工具输出首行显式包含             ║
║    "🔒 安全审查: {reason}"，让用户看到审查结果。   ║
╚══════════════════════════════════════════════════╝
"""

import json
import logging
import os
import re
import shlex
from dataclasses import dataclass
from typing import Optional

from src.core.llm_client import clean_prompt_call

logger = logging.getLogger(__name__)

# ── default-deny patterns ──────────────────────────────────────────
# These match at the token / word level to avoid false positives on
# innocent commands that *contain* these strings.

BLOCKED_PATTERNS: list[re.Pattern] = [
    # Destructive filesystem operations
    re.compile(r"\brm\s+(-rf?|--recursive)\s+(/\s*|/\*\s*)$", re.I),
    re.compile(r"\brm\s+(-rf?|--recursive)\s+/\s", re.I),
    re.compile(r"\brm\s+(-rf?|--recursive)\s+\$\{?\w+\}?\s*$", re.I),  # rm -rf $VAR (empty → /)
    re.compile(r"\bmkfs\.\w+", re.I),
    re.compile(r"\bdd\s+if=", re.I),
    re.compile(r"\bmkswap\b", re.I),
    re.compile(r"\bfdisk\b", re.I),
    re.compile(r"\bparted\b", re.I),
    re.compile(r"\bshutdown\b", re.I),
    re.compile(r"\breboot\b", re.I),
    re.compile(r"\binit\s+0\b", re.I),
    re.compile(r"\bpoweroff\b", re.I),
    re.compile(r"\bhalt\b", re.I),
    # ⚠️  Polymorphic rm — catch rm with various flags
    re.compile(r"\brm\s+(-{1,2}\w*[rRfF]\w*\s+)*\s*/\s*$", re.I),
    re.compile(r"\brm\s+(-{1,2}\w*[rR]\w*\s+)*\s+\.\s*$", re.I),
    # Disk wiping
    re.compile(r"\bwipefs?\b", re.I),
    re.compile(r"\bblkdiscard\b", re.I),
    # Format / re-format
    re.compile(r"\bmkfs\b", re.I),
    re.compile(r"\bformat\s+(/|C:|D:)", re.I),
    # Fork bomb and resource abuse
    re.compile(r":\(\)\s*\{", re.I),
    re.compile(r"\|\s*&\s*$"),
    # Network floods (naive)
    re.compile(r"\bping\s+(-f|-i\s+0)", re.I),
]

SAFETY_REVIEW_SYSTEM_PROMPT = """You are a bash command safety reviewer. Your job is to judge whether a shell command is SAFE or UNSAFE.

An UNSAFE command is one that:
- Destroys or deletes files / disks / partitions
- Shuts down or reboots the system
- Wipes or formats storage
- Executes a fork bomb or resource exhaustion attack
- Downloads and runs untrusted code (curl | sh, wget | bash)
- Exfiltrates data to an external server
- Installs malware, rootkits, or backdoors
- Modifies system files (/etc/passwd, /etc/sudoers, /etc/shadow, /boot/*)

A SAFE command is everything else — code compilation, file reading, git operations, pip install, mkdir, cp/mv with limited scope, grep/find, python scripts, etc.

You MUST respond in JSON format ONLY — no other text before or after.
The JSON must have exactly two fields:
- "result": either "SAFE" or "UNSAFE"
- "reason": a brief explanation for your decision

Examples:
{"result": "SAFE", "reason": "git clone to /tmp directory is a safe file download operation."}
{"result": "SAFE", "reason": "Python print is a harmless read-only operation."}
{"result": "UNSAFE", "reason": "rm -rf / deletes all files on the system."}
{"result": "UNSAFE", "reason": "Piping curl to bash downloads and executes untrusted code."}
{"result": "SAFE", "reason": "Removing local node_modules directory is safe."}
{"result": "SAFE", "reason": "Copying a file within the workspace is safe."}
{"result": "UNSAFE", "reason": "dd if=/dev/zero of=/dev/sda wipes a disk."}"""


@dataclass
class GuardResult:
    approved: bool
    reason: str
    command: str


# ── public API ─────────────────────────────────────────────────────


def check_command(command: str, user_requirement: str = "") -> GuardResult:
    """Check a bash command through rule layer → LLM layer.

    Args:
        command: The raw shell command string.
        user_requirement: The original user requirement (for context).

    Returns:
        GuardResult with approved=True/False and a human-readable reason.
    """
    # 1. Rule layer — fast path reject
    rule_reason = _rule_check(command)
    if rule_reason:
        logger.warning("BashGuard RULE block: %s | command=%r", rule_reason, command[:120])
        return GuardResult(approved=False, reason=rule_reason, command=command)

    # 2. LLM layer — semantic check (clean context, no history)
    #    Skip entirely if disabled via env var (for testing / offline use)
    if os.environ.get("BASH_GUARD_LLM_DISABLED", "").lower() in ("1", "true", "yes"):
        logger.info("BashGuard LLM check skipped (disabled by env var)")
        return GuardResult(approved=True, reason="Command passed rule check (LLM check disabled).", command=command)

    llm_reason = _llm_check(command, user_requirement)
    if llm_reason:
        logger.warning("BashGuard LLM block: %s | command=%r", llm_reason, command[:120])
        return GuardResult(approved=False, reason=llm_reason, command=command)

    logger.info("BashGuard APPROVED: %r", command[:120])
    return GuardResult(approved=True, reason="Command passed safety check.", command=command)


# ── internals ──────────────────────────────────────────────────────


def _rule_check(command: str) -> Optional[str]:
    """Static regex checks.  Returns reason string if blocked, None if OK."""
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(command):
            return f"命中高危命令规则: {pattern.pattern[:60]}"
    return None


def _parse_llm_json_reply(reply: str) -> Optional[dict]:
    """Try to parse LLM reply as JSON with result & reason fields.

    Strips markdown code fences if present before parsing.
    Returns parsed dict on success, None on failure.
    """
    text = reply.strip()
    # Strip markdown JSON code fences if present
    if text.startswith("```"):
        # Remove ```json / ``` etc.
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3].strip()
        elif text.rfind("```") != -1:
            text = text[: text.rfind("```")].strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "result" in parsed and "reason" in parsed:
            return parsed
        return None
    except (json.JSONDecodeError, ValueError):
        return None


def _llm_check(command: str, user_requirement: str) -> Optional[str]:
    """Send command to a *stateless* LLM call for semantic review.

    The LLM is expected to return JSON with ``{"result": "SAFE"|"UNSAFE",
    "reason": "..."}``.  If JSON parsing fails, the call is retried once
    with the previous raw reply included as context so the LLM can correct
    its output format.

    If the LLM is unreachable (network error / timeout), the check is
    *skipped* — the command is allowed through with a warning.  This
    avoids blocking development when the API is temporarily down.
    """
    prompt_template = (
        f"User requirement: {user_requirement or '(not provided)'}\n\n"
        f"Command to review:\n```bash\n{command}\n```\n\n"
        "Is this command SAFE or UNSAFE? Respond in JSON format only."
    )

    def _do_call(prompt: str) -> Optional[str]:
        try:
            reply = clean_prompt_call(
                prompt,
                system_prompt=SAFETY_REVIEW_SYSTEM_PROMPT,
                temperature=0.0,
            )
            parsed = _parse_llm_json_reply(reply)
            if parsed is None:
                # First attempt failed — retry with previous context
                correction_prompt = (
                    f"{prompt}\n\n"
                    f"[IMPORTANT] Your previous response was not valid JSON. "
                    f"You replied with:\n{reply}\n\n"
                    "Please respond ONLY with valid JSON in the format: "
                    '{"result": "SAFE" or "UNSAFE", "reason": "..."}'
                )
                retry_reply = clean_prompt_call(
                    correction_prompt,
                    system_prompt=SAFETY_REVIEW_SYSTEM_PROMPT,
                    temperature=0.0,
                )
                retry_parsed = _parse_llm_json_reply(retry_reply)
                if retry_parsed is None:
                    logger.warning(
                        "BashGuard LLM JSON parse failed after retry. "
                        "Original reply=%r, retry reply=%r", reply, retry_reply
                    )
                    return None  # fail OPEN — rule layer already passed
                parsed = retry_parsed

            result = parsed["result"].strip().upper()
            reason = parsed["reason"].strip()
            if result == "UNSAFE":
                return f"LLM 审核不通过: {reason}"
            return None
        except Exception as exc:
            logger.warning("BashGuard LLM call failed (skipping LLM check): %s", exc)
            return None  # fail OPEN — rule layer already passed

    return _do_call(prompt_template)
