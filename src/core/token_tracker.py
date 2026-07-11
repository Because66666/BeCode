"""TokenTracker — global singleton for tracking LLM token usage across a session.

Each call to ``add_usage()`` accumulates input and output tokens per agent
(coder / reviewer).  The orchestrator resets the tracker at the start of
each ``run()`` or ``run_interactive()``, and the console reads the per-agent
totals for display in the final statistics panel.

Error handling (snapshot/restore):
  - Before each agent attempt, the orchestrator calls ``snapshot(agent_name)``.
  - If the attempt fails, ``restore(agent_name)`` rolls back usage from the
    failed attempt, avoiding double-counting.
  - On success, the usage is kept as-is.
"""

from typing import Optional


class AgentUsage:
    """Token usage for a single agent (coder or reviewer)."""

    def __init__(self):
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self._last_successful_input: int = 0
        self._last_successful_output: int = 0
        self._pending_input: Optional[int] = None
        self._pending_output: Optional[int] = None

    def add_usage(self, input_tokens: Optional[int], output_tokens: Optional[int],
                  mark_success: bool = True):
        """Add a single LLM call's token usage.

        If ``mark_success`` is True, the added tokens are committed directly.
        If False (error case), tokens are stored as pending and will be
        committed later via ``commit_pending()``.

        Args:
            input_tokens: Number of prompt tokens consumed, or None.
            output_tokens: Number of completion tokens generated, or None.
            mark_success: Whether to commit immediately (True) or defer (False).
        """
        inp = input_tokens if input_tokens is not None else 0
        out = output_tokens if output_tokens is not None else 0

        if mark_success:
            # Normal case: commit directly
            self.input_tokens += inp
            self.output_tokens += out
            self._last_successful_input = inp
            self._last_successful_output = out
            self._pending_input = None
            self._pending_output = None
        else:
            # Error case: store as pending (will be committed on next success)
            self._pending_input = inp
            self._pending_output = out

    def commit_pending(self):
        """Commit any pending usage from a failed-then-retried attempt.

        Error handling rule: when an agent fails and then succeeds on retry,
        the usage from the *last successful LLM call before the error* is
        retained, and the usage from the *retry completion* is added on top.
        Pending usage (from failed attempts) is discarded to avoid double-counting.
        """
        self._pending_input = None
        self._pending_output = None

    @property
    def total_input(self) -> int:
        return self.input_tokens

    @property
    def total_output(self) -> int:
        return self.output_tokens


class TokenTracker:
    """Accumulates token usage across LLM calls per agent in the current session.

    Supports snapshot/restore for retry loops: before each agent attempt,
    call ``snapshot(agent_name)``; if the attempt fails, call
    ``restore(agent_name)`` to roll back any usage from the failed attempt.
    """

    def __init__(self):
        self._coder = AgentUsage()
        self._reviewer = AgentUsage()
        self._snapshots: dict[str, AgentUsage] = {}

    def add_usage(self, input_tokens: Optional[int], output_tokens: Optional[int],
                  agent_name: str = "coder"):
        """Add a single LLM call's token usage for a specific agent.

        Args:
            input_tokens: Number of prompt tokens consumed, or None.
            output_tokens: Number of completion tokens generated, or None.
            agent_name: Which agent ("coder" or "reviewer").
        """
        agent = self._get_agent(agent_name)
        inp = input_tokens if input_tokens is not None else 0
        out = output_tokens if output_tokens is not None else 0
        agent.input_tokens += inp
        agent.output_tokens += out

    def snapshot(self, agent_name: str = "coder"):
        """Save the current usage state for an agent before an attempt.

        Call before each retry attempt. If the attempt fails, call
        ``restore()`` to roll back.
        """
        agent = self._get_agent(agent_name)
        snap = AgentUsage()
        snap.input_tokens = agent.input_tokens
        snap.output_tokens = agent.output_tokens
        self._snapshots[agent_name] = snap

    def restore(self, agent_name: str = "coder"):
        """Restore usage to the last snapshot (discard failed attempt's usage).

        Call when a retry attempt fails, to avoid double-counting usage
        from failed LLM calls.
        """
        snap = self._snapshots.get(agent_name)
        if snap is not None:
            agent = self._get_agent(agent_name)
            agent.input_tokens = snap.input_tokens
            agent.output_tokens = snap.output_tokens

    def get_usage(self, agent_name: str = "coder") -> dict:
        """Get usage summary for a specific agent.

        Returns:
            dict with keys: input_tokens, output_tokens
        """
        agent = self._get_agent(agent_name)
        return {
            "input_tokens": agent.total_input,
            "output_tokens": agent.total_output,
        }

    @property
    def total_input_tokens(self) -> int:
        """Total input tokens across all agents."""
        return self._coder.total_input + self._reviewer.total_input

    @property
    def total_output_tokens(self) -> int:
        """Total output tokens across all agents."""
        return self._coder.total_output + self._reviewer.total_output

    def reset(self):
        """Reset all counters to zero (called at start of each session)."""
        self._coder = AgentUsage()
        self._reviewer = AgentUsage()
        self._snapshots.clear()

    def _get_agent(self, name: str) -> AgentUsage:
        if name == "coder":
            return self._coder
        elif name == "reviewer":
            return self._reviewer
        else:
            # Fallback to coder for unknown agent names
            return self._coder

    @property
    def coder_input(self) -> int:
        return self._coder.total_input

    @property
    def coder_output(self) -> int:
        return self._coder.total_output

    @property
    def reviewer_input(self) -> int:
        return self._reviewer.total_input

    @property
    def reviewer_output(self) -> int:
        return self._reviewer.total_output


# ── Module-level singleton ────────────────────────────────────────────

_tracker: Optional[TokenTracker] = None


def get_token_tracker() -> TokenTracker:
    """Return the global TokenTracker instance (lazily created)."""
    global _tracker
    if _tracker is None:
        _tracker = TokenTracker()
    return _tracker
