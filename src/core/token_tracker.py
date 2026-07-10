"""TokenTracker — global singleton for tracking LLM token usage across a session.

Each call to ``add_usage()`` accumulates input and output tokens.  The
orchestrator resets the tracker at the start of each ``run()`` or
``run_interactive()``, and the console reads the totals for display in
the final statistics panel.
"""

from typing import Optional


class TokenTracker:
    """Accumulates token usage across LLM calls in the current session."""

    def __init__(self):
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

    def add_usage(self, input_tokens: Optional[int], output_tokens: Optional[int]):
        """Add a single LLM call's token usage to the running totals.

        Args:
            input_tokens: Number of prompt tokens consumed, or None.
            output_tokens: Number of completion tokens generated, or None.
        """
        if input_tokens is not None:
            self.total_input_tokens += input_tokens
        if output_tokens is not None:
            self.total_output_tokens += output_tokens

    def reset(self):
        """Reset both counters to zero (called at start of each session)."""
        self.total_input_tokens = 0
        self.total_output_tokens = 0


# ── Module-level singleton ────────────────────────────────────────────

_tracker: Optional[TokenTracker] = None


def get_token_tracker() -> TokenTracker:
    """Return the global TokenTracker instance (lazily created)."""
    global _tracker
    if _tracker is None:
        _tracker = TokenTracker()
    return _tracker
