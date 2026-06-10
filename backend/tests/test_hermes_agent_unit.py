"""
Unit tests for HermesAgentService.

Tests:
1. test_run_success_path          — successful AIAgent call; verify reply and add_message calls
2. test_run_aiagent_exception     — AIAgent raises; verify fallback string returned (never raises)
3. test_run_label_update_exception_suppression — AIAgent raises in label path; verify None returned
4. test_fresh_agent_per_run_call  — _make_agent() called once per run() invocation (Property 4)

Requirements: 1.4, 1.5, 9.2
"""
import sys
import os
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Stub out run_agent before any project import so hermes_agent.py can be
# imported without the real hermes-agent package being installed.
# ---------------------------------------------------------------------------
_mock_ai_agent_cls = MagicMock(name="AIAgent")
_run_agent_stub = MagicMock(name="run_agent_module")
_run_agent_stub.AIAgent = _mock_ai_agent_cls
sys.modules.setdefault("run_agent", _run_agent_stub)

# Ensure backend/ is on the path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.hermes_agent import HermesAgentService  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_store(history=None):
    """Return a MagicMock StateStore with sensible defaults."""
    store = MagicMock()
    store.get_history.return_value = history if history is not None else []
    store.add_message.return_value = None
    return store


def _make_service(store=None):
    """Return a HermesAgentService wired to a mock StateStore."""
    if store is None:
        store = _make_mock_store()
    return HermesAgentService(
        state_store=store,
        model="test-model",
        api_key="test-key",
        base_url="http://test",
        max_iterations=5,
    ), store


# ---------------------------------------------------------------------------
# Test 1: run() success path
# ---------------------------------------------------------------------------

def test_run_success_path():
    """
    When AIAgent.run_conversation returns {"final_response": "Hello"},
    run() must:
      - return exactly "Hello"
      - call add_message twice: once for user, once for assistant
    """
    service, store = _make_service()

    mock_agent = MagicMock()
    mock_agent.run_conversation.return_value = {"final_response": "Hello"}

    with patch("services.hermes_agent.AIAgent", return_value=mock_agent):
        result = service.run("conv-1", "Hi there", 42)

    assert result == "Hello", f"Expected 'Hello', got {result!r}"

    # add_message should have been called exactly twice
    assert store.add_message.call_count == 2, (
        f"Expected 2 add_message calls, got {store.add_message.call_count}"
    )

    calls = store.add_message.call_args_list
    # First call: persist the user message
    assert calls[0] == call("conv-1", "user", "Hi there"), (
        f"First add_message call unexpected: {calls[0]}"
    )
    # Second call: persist the assistant reply
    assert calls[1] == call("conv-1", "assistant", "Hello"), (
        f"Second add_message call unexpected: {calls[1]}"
    )


# ---------------------------------------------------------------------------
# Test 2: run() when AIAgent raises an exception
# ---------------------------------------------------------------------------

def test_run_aiagent_exception():
    """
    When AIAgent.run_conversation raises any Exception, run() must:
      - NOT propagate the exception
      - Return a non-empty fallback string
    """
    service, store = _make_service()

    mock_agent = MagicMock()
    mock_agent.run_conversation.side_effect = RuntimeError("agent blew up")

    with patch("services.hermes_agent.AIAgent", return_value=mock_agent):
        # Must not raise
        try:
            result = service.run("conv-2", "What properties do you have?", 99)
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"run() raised an unexpected exception: {exc!r}")

    assert isinstance(result, str), "run() must return a str"
    assert len(result) > 0, "run() must return a non-empty fallback string"


# ---------------------------------------------------------------------------
# Test 3: run_label_update() exception suppression
# ---------------------------------------------------------------------------

def test_run_label_update_exception_suppression():
    """
    When AIAgent.run_conversation raises inside run_label_update(), the method must:
      - NOT propagate the exception
      - Return None (implicitly)
    """
    service, store = _make_service()

    mock_agent = MagicMock()
    mock_agent.run_conversation.side_effect = Exception("label agent crashed")

    with patch("services.hermes_agent.AIAgent", return_value=mock_agent):
        try:
            result = service.run_label_update("conv-3", 7)
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"run_label_update() raised an unexpected exception: {exc!r}")

    assert result is None, f"run_label_update() must return None, got {result!r}"


# ---------------------------------------------------------------------------
# Test 4: fresh AIAgent per run() call (Property 4)
# ---------------------------------------------------------------------------

def test_fresh_agent_per_run_call():
    """
    **Validates: Requirements 1.5**

    Property 4: A fresh AIAgent instance is created for every run() call.
    Calling run() twice must result in _make_agent() being invoked twice,
    producing two distinct instances — confirming no shared mutable state
    across concurrent requests.
    """
    service, store = _make_service()

    agent_instance_1 = MagicMock(name="agent_instance_1")
    agent_instance_1.run_conversation.return_value = {"final_response": "Reply 1"}

    agent_instance_2 = MagicMock(name="agent_instance_2")
    agent_instance_2.run_conversation.return_value = {"final_response": "Reply 2"}

    with patch("services.hermes_agent.AIAgent", side_effect=[agent_instance_1, agent_instance_2]) as mock_cls:
        result1 = service.run("conv-4a", "First message", 1)
        result2 = service.run("conv-4b", "Second message", 2)

    # AIAgent constructor must have been called exactly twice
    assert mock_cls.call_count == 2, (
        f"Expected AIAgent to be constructed 2 times, got {mock_cls.call_count}"
    )

    # The two instances must be distinct objects
    assert agent_instance_1 is not agent_instance_2, (
        "Each run() call must receive a distinct AIAgent instance"
    )

    # Sanity-check that both calls returned the correct reply
    assert result1 == "Reply 1"
    assert result2 == "Reply 2"
