"""Tests for src.core.session_store — SessionStore CRUD."""

import json
from pathlib import Path

import pytest

from src.core.session_store import SessionStore


class TestSessionStoreCreation:
    """Verify session creation and basic properties."""

    def test_session_id_is_8_chars(self, session_store: SessionStore):
        assert len(session_store.session_id) == 8

    def test_initial_turn_is_zero(self, session_store: SessionStore):
        assert session_store.turn == 0

    def test_initial_status_is_pending(self, session_store: SessionStore):
        assert session_store.status == "pending"

    def test_initial_history_empty(self, session_store: SessionStore):
        assert session_store.history == []

    def test_initial_requirement_empty(self, session_store: SessionStore):
        assert session_store.requirement == ""


class TestSessionStoreProperties:
    """Verify property getters/setters."""

    def test_status_setter(self, session_store: SessionStore):
        session_store.status = "completed"
        assert session_store.status == "completed"

    def test_requirement_setter(self, session_store: SessionStore):
        session_store.requirement = "Test requirement"
        assert session_store.requirement == "Test requirement"

    def test_incr_turn(self, session_store: SessionStore):
        assert session_store.incr_turn() == 1
        assert session_store.turn == 1
        assert session_store.incr_turn() == 2
        assert session_store.turn == 2


class TestSessionStoreHistory:
    """Verify history entry management."""

    def test_add_entry(self, session_store: SessionStore):
        session_store.add_entry("coder", "Report content")
        assert len(session_store.history) == 1
        entry = session_store.history[0]
        assert entry["role"] == "coder"
        assert entry["content"] == "Report content"
        assert entry["turn"] == 0  # initial turn
        assert "timestamp" in entry
        assert "metadata" not in entry  # no metadata passed

    def test_add_entry_with_metadata(self, session_store: SessionStore):
        meta = {"tool_calls": [{"tool": "read_file", "args": {"path": "x.py"}}]}
        session_store.add_entry("reviewer", "Verdict", metadata=meta)
        entry = session_store.history[0]
        assert entry["metadata"] == meta

    def test_add_entry_multiple(self, session_store: SessionStore):
        session_store.add_entry("coder", "First")
        session_store.incr_turn()
        session_store.add_entry("reviewer", "Second")
        assert len(session_store.history) == 2
        assert session_store.history[0]["content"] == "First"
        assert session_store.history[1]["content"] == "Second"
        assert session_store.history[1]["turn"] == 1


class TestSessionStorePersistence:
    """Verify save/load round-trip."""

    def test_save_creates_file(self, loaded_session: SessionStore):
        assert loaded_session._file.exists()

    def test_save_content(self, loaded_session: SessionStore):
        data = json.loads(loaded_session._file.read_text(encoding="utf-8"))
        assert data["session_id"] == loaded_session.session_id
        assert data["requirement"] == "Write a test"
        assert data["status"] == "running"
        assert len(data["history"]) == 3

    def test_load_existing_session(self, tmp_session_dir: Path, loaded_session: SessionStore):
        sid = loaded_session.session_id
        # Create a new store with the same ID
        new_store = SessionStore(session_id=sid)
        assert new_store.requirement == "Write a test"
        assert new_store.status == "running"
        assert new_store.turn == 1  # incr_turn was called
        assert len(new_store.history) == 3

    def test_repr(self, session_store: SessionStore):
        r = repr(session_store)
        assert session_store.session_id in r
        assert "turn=0" in r
        assert "status=pending" in r


class TestSessionStoreEdgeCases:
    """Verify edge-case behavior."""

    def test_load_nonexistent_session(self, tmp_session_dir: Path):
        store = SessionStore(session_id="nonexist")
        assert store.status == "pending"
        assert store.history == []

    def test_add_entry_to_loaded_session(self, loaded_session: SessionStore):
        loaded_session.add_entry("coder", "New entry")
        assert len(loaded_session.history) == 4

    def test_session_id_uniqueness(self):
        s1 = SessionStore()
        s2 = SessionStore()
        assert s1.session_id != s2.session_id
