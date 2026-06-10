"""
Property-based tests for HermesAgentService.

**Validates: Requirements 1.3, 1.4**

Property 3: HermesAgentService never raises
  For any conversation_id, user_message, and account_id, run() never raises
  and always returns a non-empty string — regardless of whether the underlying
  AIAgent succeeds or throws an exception.
"""
import sys
import os
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub out run_agent (hermes-agent package) before any project import so that
# hermes_agent.py can be imported without the real package being installed.
# ---------------------------------------------------------------------------
_mock_ai_agent_cls = MagicMock(name="AIAgent")
_run_agent_stub = MagicMock(name="run_agent_module")
_run_agent_stub.AIAgent = _mock_ai_agent_cls
sys.modules.setdefault("run_agent", _run_agent_stub)

# Ensure backend/ is on the path so project imports resolve correctly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from services.hermes_agent import HermesAgentService  # noqa: E402


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# conversation_id: non-empty text (Chatwoot IDs are typically numeric strings,
# but the service must handle any non-empty string).
conversation_id_st = st.text(min_size=1, max_size=200)

# user_message: non-empty text (WhatsApp messages can be arbitrary Unicode).
user_message_st = st.text(min_size=1, max_size=2000)

# account_id: any integer (Chatwoot account IDs are positive ints in practice,
# but the service must not raise for any int value).
account_id_st = st.integers(min_value=-(2**31), max_value=2**31 - 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_service(agent_response=None, agent_raises=None):
    """
    Return a (HermesAgentService, mock_agent_instance) pair where AIAgent
    and StateStore are fully mocked.

    - agent_response: dict returned by mock_agent.run_conversation()
    - agent_raises:   exception raised by mock_agent.run_conversation()
    """
    mock_store = MagicMock()
    mock_store.get_history.return_value = []
    mock_store.add_message.return_value = None

    service = HermesAgentService(state_store=mock_store)

    mock_agent_instance = MagicMock()
    if agent_raises is not None:
        mock_agent_instance.run_conversation.side_effect = agent_raises
    else:
        response = agent_response if agent_response is not None else {"final_response": "Test reply."}
        mock_agent_instance.run_conversation.return_value = response

    return service, mock_agent_instance


# ---------------------------------------------------------------------------
# Property 3 — success path
# ---------------------------------------------------------------------------

@given(
    conversation_id=conversation_id_st,
    user_message=user_message_st,
    account_id=account_id_st,
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_run_never_raises_on_success(conversation_id, user_message, account_id):
    """
    **Validates: Requirements 1.3, 1.4**

    Property 3 (success path): When AIAgent succeeds and returns a final_response,
    HermesAgentService.run() must return a non-empty string and must never raise.
    """
    service, mock_agent_instance = _build_service(
        agent_response={"final_response": "Some reply from the agent."}
    )

    with patch("services.hermes_agent.AIAgent", return_value=mock_agent_instance):
        result = service.run(conversation_id, user_message, account_id)

    assert isinstance(result, str), "run() must return a str"
    assert len(result) > 0, "run() must return a non-empty string"


@given(
    conversation_id=conversation_id_st,
    user_message=user_message_st,
    account_id=account_id_st,
    final_response=st.one_of(
        st.none(),
        st.just(""),
        st.text(min_size=1, max_size=500),
    ),
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_run_never_raises_with_varied_agent_responses(
    conversation_id, user_message, account_id, final_response
):
    """
    **Validates: Requirements 1.3, 1.4**

    Property 3 (response variation): Even when AIAgent returns None, an empty string,
    or any non-empty string as final_response, run() must return a non-empty string
    and must never raise.
    """
    service, mock_agent_instance = _build_service(
        agent_response={"final_response": final_response}
    )

    with patch("services.hermes_agent.AIAgent", return_value=mock_agent_instance):
        result = service.run(conversation_id, user_message, account_id)

    assert isinstance(result, str), "run() must return a str"
    assert len(result) > 0, (
        "run() must return a non-empty string even when final_response is empty/None"
    )


# ---------------------------------------------------------------------------
# Property 3 — error path (AIAgent raises)
# ---------------------------------------------------------------------------

_EXCEPTION_TYPES = [
    Exception("generic error"),
    RuntimeError("runtime failure"),
    ValueError("bad value"),
    ConnectionError("DB connection lost"),
    TimeoutError("agent timed out"),
    KeyError("missing key"),
    AttributeError("attr missing"),
]


@given(
    conversation_id=conversation_id_st,
    user_message=user_message_st,
    account_id=account_id_st,
    exc_index=st.integers(min_value=0, max_value=len(_EXCEPTION_TYPES) - 1),
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_run_never_raises_when_agent_raises(
    conversation_id, user_message, account_id, exc_index
):
    """
    **Validates: Requirements 1.3, 1.4**

    Property 3 (error path): When the underlying AIAgent raises any exception,
    HermesAgentService.run() must:
      - NOT propagate the exception (i.e. not raise)
      - Return a non-empty fallback string
    """
    exc = _EXCEPTION_TYPES[exc_index]
    service, mock_agent_instance = _build_service(agent_raises=exc)

    with patch("services.hermes_agent.AIAgent", return_value=mock_agent_instance):
        result = service.run(conversation_id, user_message, account_id)

    assert isinstance(result, str), "run() must return a str even when AIAgent raises"
    assert len(result) > 0, "run() must return a non-empty string even when AIAgent raises"


# ---------------------------------------------------------------------------
# Property 3 — store error path (StateStore raises)
# ---------------------------------------------------------------------------

@given(
    conversation_id=conversation_id_st,
    user_message=user_message_st,
    account_id=account_id_st,
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_run_never_raises_when_store_raises(conversation_id, user_message, account_id):
    """
    **Validates: Requirements 1.3, 1.4**

    Property 3 (store error path): When StateStore.get_history raises an exception,
    HermesAgentService.run() must not propagate it and must return a non-empty string.
    """
    mock_store = MagicMock()
    mock_store.get_history.side_effect = Exception("DB unavailable")

    service = HermesAgentService(state_store=mock_store)

    mock_agent_instance = MagicMock()
    mock_agent_instance.run_conversation.return_value = {"final_response": "ok"}

    with patch("services.hermes_agent.AIAgent", return_value=mock_agent_instance):
        result = service.run(conversation_id, user_message, account_id)

    assert isinstance(result, str), "run() must return a str when store raises"
    assert len(result) > 0, "run() must return a non-empty string when store raises"


# ---------------------------------------------------------------------------
# Property 6 — search_properties limit clamping
# ---------------------------------------------------------------------------

# Import the function under test (DB call will be mocked)
import json  # noqa: E402 (already imported above via hypothesis; re-stated for clarity)
from real_estate_tools.property_tools import search_properties, get_property_details  # noqa: E402

# Strategy: any integer that could be passed as limit (including out-of-range values)
limit_st = st.integers(min_value=-(2**31), max_value=2**31 - 1)


def _make_mock_db(rows=None, total=0):
    """Return a mock DatabaseService whose search_auctions returns (rows, total)."""
    mock_db = MagicMock()
    mock_db.search_auctions.return_value = (rows if rows is not None else [], total)
    return mock_db


@given(limit=limit_st)
@settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_search_properties_limit_clamping(limit):
    """
    **Validates: Requirements 2.2, 2.3**

    Property 6: Search limit clamping — for any integer `limit`, the value used
    internally and reflected in the returned JSON is always in [1, 10].
    The DB call is mocked so no live database is required.
    """
    mock_db = _make_mock_db()

    with patch("services.database._get_shared_db", return_value=mock_db):
        result_str = search_properties(limit=limit)

    # The function must always return valid JSON (never raise)
    parsed = json.loads(result_str)

    # Must not be an error response — a clamped limit is always valid
    assert "error" not in parsed, (
        f"search_properties returned an error for limit={limit}: {parsed['error']}"
    )

    returned_limit = parsed["limit"]

    # The limit field in the response must be within [1, 10]
    assert 1 <= returned_limit <= 10, (
        f"Returned limit {returned_limit} is outside [1, 10] for input limit={limit}"
    )

    # The limit forwarded to search_auctions must also be within [1, 10]
    call_kwargs = mock_db.search_auctions.call_args
    assert call_kwargs is not None, "search_auctions was not called"
    actual_limit_arg = call_kwargs.kwargs.get("limit") or call_kwargs.args[1]
    assert 1 <= actual_limit_arg <= 10, (
        f"Limit passed to DB ({actual_limit_arg}) is outside [1, 10] for input limit={limit}"
    )


# ---------------------------------------------------------------------------
# Property 8 — assign_chatwoot_labels label count cap
# ---------------------------------------------------------------------------

from real_estate_tools.crm_tools import assign_chatwoot_labels  # noqa: E402

# Strategy: labels list of any size (0 to 20 items)
label_st = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu"), whitelist_characters="_"),
    min_size=1,
    max_size=30,
)
labels_list_st = st.lists(label_st, min_size=0, max_size=20)

account_id_pos_st = st.integers(min_value=1, max_value=2**31 - 1)
conversation_id_nonempty_st = st.text(min_size=1, max_size=200)


@given(
    account_id=account_id_pos_st,
    conversation_id=conversation_id_nonempty_st,
    labels=labels_list_st,
)
@settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_assign_chatwoot_labels_count_cap(account_id, conversation_id, labels):
    """
    **Validates: Requirements 3.1**

    Property 8: Label count cap — for any `labels` list of any size,
    assign_chatwoot_labels assigns at most 6 labels to the Chatwoot conversation.
    The value passed to set_conversation_labels must always have length <= 6.
    """
    mock_client = MagicMock()
    # Simulate no existing labels in the account
    mock_client.get_all_labels.return_value = []
    mock_client.create_label.return_value = None
    mock_client.set_conversation_labels.return_value = None

    with patch("services.chatwoot.ChatwootClient", return_value=mock_client):
        result_str = assign_chatwoot_labels(account_id, conversation_id, labels)

    # The function must always return valid JSON
    parsed = json.loads(result_str)

    # Must not be an error response for a normal call
    assert "error" not in parsed, (
        f"assign_chatwoot_labels returned an error: {parsed.get('error')}"
    )

    # set_conversation_labels must have been called exactly once
    assert mock_client.set_conversation_labels.call_count == 1, (
        "set_conversation_labels must be called exactly once"
    )

    # Extract the labels argument passed to set_conversation_labels
    call_args = mock_client.set_conversation_labels.call_args
    assigned_labels = call_args.args[2] if len(call_args.args) >= 3 else call_args.kwargs.get("labels", [])

    # At most 6 labels must be assigned — regardless of how many were passed in
    assert len(assigned_labels) <= 6, (
        f"set_conversation_labels was called with {len(assigned_labels)} labels "
        f"(input had {len(labels)}); must be at most 6"
    )

    # The assigned list in the response must also be <= 6
    assert len(parsed["assigned"]) <= 6, (
        f"Response 'assigned' field has {len(parsed['assigned'])} labels; must be at most 6"
    )


# ---------------------------------------------------------------------------
# Property 5 — search_properties structural invariant
# ---------------------------------------------------------------------------

# Strategies for filter parameters
optional_text_st = st.one_of(st.none(), st.text(min_size=1, max_size=100))
optional_float_st = st.one_of(st.none(), st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False))
offset_st = st.integers(min_value=0, max_value=10_000)

# Strategy to build a controlled list of mock DB rows (each row is a plain dict)
row_st = st.fixed_dictionaries({
    "listing_id": st.text(min_size=1, max_size=50),
    "city": st.text(min_size=1, max_size=50),
    "reserve_price": st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False),
})


@given(
    city=optional_text_st,
    asset_type=optional_text_st,
    asset_category=optional_text_st,
    institution=optional_text_st,
    min_price=optional_float_st,
    max_price=optional_float_st,
    limit=limit_st,
    offset=offset_st,
    rows=st.lists(row_st, min_size=0, max_size=10),
)
@settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_search_properties_structural_invariant(
    city, asset_type, asset_category, institution,
    min_price, max_price, limit, offset, rows,
):
    """
    **Validates: Requirements 2.1**

    Property 5: Search results structural invariant — for any filter combination,
    `search_properties` always returns a valid JSON string with keys `results`,
    `total`, `offset`, and `limit`, where:
      - `total >= len(results) >= 0`
      - `offset >= 0`
    The DB is mocked to return controlled data so no live database is required.
    """
    total = len(rows)  # simulate DB reporting the exact count for our rows
    mock_db = _make_mock_db(rows=rows, total=total)

    with patch("services.database._get_shared_db", return_value=mock_db):
        result_str = search_properties(
            city=city,
            asset_type=asset_type,
            asset_category=asset_category,
            institution=institution,
            min_price=min_price,
            max_price=max_price,
            limit=limit,
            offset=offset,
        )

    # Must always return valid JSON
    try:
        parsed = json.loads(result_str)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"search_properties did not return valid JSON: {exc!r}. "
            f"Raw output: {result_str!r}"
        )

    # Must not be an error response for valid inputs
    assert "error" not in parsed, (
        f"search_properties returned an error for a valid call: {parsed.get('error')}"
    )

    # Must contain all required structural keys
    for key in ("results", "total", "offset", "limit"):
        assert key in parsed, (
            f"Response JSON is missing required key '{key}'. Keys present: {list(parsed.keys())}"
        )

    # `results` must be a list
    assert isinstance(parsed["results"], list), (
        f"'results' must be a list, got {type(parsed['results']).__name__}"
    )

    # `total >= len(results) >= 0`
    result_count = len(parsed["results"])
    assert result_count >= 0, "len(results) must be >= 0"
    assert parsed["total"] >= result_count, (
        f"total ({parsed['total']}) must be >= len(results) ({result_count})"
    )

    # `offset >= 0`
    assert parsed["offset"] >= 0, (
        f"offset in response ({parsed['offset']}) must be >= 0"
    )


# ---------------------------------------------------------------------------
# Property 7 — Tools always return JSON
# ---------------------------------------------------------------------------
#
# **Validates: Requirements 2.7, 8.1, 8.2**
#
# For any arguments (including edge cases that trigger exceptions), every tool
# handler must return a value parseable by json.loads() — never raise, never
# return None, never return a raw dict.
# ---------------------------------------------------------------------------

from real_estate_tools.crm_tools import (  # noqa: E402
    assign_chatwoot_labels,
    create_lead,
    update_lead_stage,
)
from real_estate_tools.followup_tools import schedule_followup  # noqa: E402

# ---------------------------------------------------------------------------
# Common strategies for tool arguments
# ---------------------------------------------------------------------------

# Any text, including empty — to trigger edge cases
any_text_st = st.text(max_size=200)
nonempty_text_st = st.text(min_size=1, max_size=200)
any_int_st = st.integers(min_value=-(2**31), max_value=2**31 - 1)
optional_text_st_p7 = st.one_of(st.none(), st.text(max_size=200))
label_list_st = st.lists(st.text(max_size=50), min_size=0, max_size=20)


# ---------------------------------------------------------------------------
# Helper: assert result is JSON-parseable
# ---------------------------------------------------------------------------

def _assert_json_parseable(result, tool_name: str, **kwargs):
    """Assert that result is a non-None string parseable by json.loads()."""
    assert result is not None, (
        f"{tool_name} returned None (must return a JSON string)"
    )
    assert isinstance(result, str), (
        f"{tool_name} returned {type(result).__name__!r}, expected str. "
        f"Args: {kwargs}"
    )
    try:
        json.loads(result)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"{tool_name} returned non-JSON string: {exc!r}. "
            f"Raw output: {result!r}. Args: {kwargs}"
        )


# ---------------------------------------------------------------------------
# Property 7a — search_properties always returns JSON
# ---------------------------------------------------------------------------

@given(
    city=optional_text_st,
    asset_type=optional_text_st,
    asset_category=optional_text_st,
    institution=optional_text_st,
    min_price=st.one_of(st.none(), st.floats(allow_nan=True, allow_infinity=True)),
    max_price=st.one_of(st.none(), st.floats(allow_nan=True, allow_infinity=True)),
    limit=any_int_st,
    offset=any_int_st,
)
@settings(
    max_examples=150,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_search_properties_always_returns_json(
    city, asset_type, asset_category, institution,
    min_price, max_price, limit, offset,
):
    """
    **Validates: Requirements 2.7, 8.1, 8.2**

    Property 7a: search_properties always returns a JSON-parseable string for any
    combination of arguments, including NaN/Inf floats and out-of-range ints that
    may trigger exceptions internally.
    """
    # Mock the DB to fail (worst-case path: every call triggers an exception)
    mock_db = MagicMock()
    mock_db.search_auctions.side_effect = Exception("simulated DB failure")

    with patch("services.database._get_shared_db", return_value=mock_db):
        result = search_properties(
            city=city,
            asset_type=asset_type,
            asset_category=asset_category,
            institution=institution,
            min_price=min_price,
            max_price=max_price,
            limit=limit,
            offset=offset,
        )

    _assert_json_parseable(
        result, "search_properties",
        city=city, asset_type=asset_type, limit=limit, offset=offset,
    )


@given(
    city=optional_text_st,
    asset_type=optional_text_st,
    limit=st.integers(min_value=1, max_value=10),
    offset=st.integers(min_value=0, max_value=1000),
    rows=st.lists(
        st.fixed_dictionaries({"listing_id": nonempty_text_st, "city": optional_text_st}),
        min_size=0, max_size=10,
    ),
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_search_properties_always_returns_json_on_success(
    city, asset_type, limit, offset, rows,
):
    """
    **Validates: Requirements 2.7, 8.1, 8.2**

    Property 7a (success path): search_properties always returns a JSON-parseable
    string even when the DB returns arbitrary row data.
    """
    mock_db = MagicMock()
    mock_db.search_auctions.return_value = (rows, len(rows))

    with patch("services.database._get_shared_db", return_value=mock_db):
        result = search_properties(city=city, asset_type=asset_type, limit=limit, offset=offset)

    _assert_json_parseable(result, "search_properties", city=city, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Property 7b — get_property_details always returns JSON
# ---------------------------------------------------------------------------

@given(listing_id=any_text_st)
@settings(
    max_examples=150,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_get_property_details_always_returns_json_on_db_error(listing_id):
    """
    **Validates: Requirements 2.7, 8.1, 8.2**

    Property 7b (error path): get_property_details returns a JSON string even when the
    database raises an exception (including for empty/unusual listing_id values).
    """
    mock_db = MagicMock()
    mock_db.get_connection.side_effect = Exception("simulated DB failure")

    with patch("services.database._get_shared_db", return_value=mock_db):
        result = get_property_details(listing_id)

    _assert_json_parseable(result, "get_property_details", listing_id=listing_id)


@given(listing_id=nonempty_text_st)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_get_property_details_always_returns_json_not_found(listing_id):
    """
    **Validates: Requirements 2.7, 8.1, 8.2**

    Property 7b (not-found path): get_property_details returns a JSON string when the
    listing is not found in the database (cursor returns None).
    """
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchone.return_value = None

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor

    mock_db = MagicMock()
    mock_db.get_connection.return_value = mock_conn

    with patch("services.database._get_shared_db", return_value=mock_db):
        with patch("psycopg2.extras.RealDictCursor"):
            result = get_property_details(listing_id)

    _assert_json_parseable(result, "get_property_details", listing_id=listing_id)


# ---------------------------------------------------------------------------
# Property 7c — assign_chatwoot_labels always returns JSON
# ---------------------------------------------------------------------------

@given(
    account_id=any_int_st,
    conversation_id=any_text_st,
    labels=label_list_st,
)
@settings(
    max_examples=150,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_assign_chatwoot_labels_always_returns_json(account_id, conversation_id, labels):
    """
    **Validates: Requirements 2.7, 8.1, 8.2**

    Property 7c: assign_chatwoot_labels always returns a JSON-parseable string for any
    combination of arguments, including those that cause the Chatwoot client to raise.
    """
    mock_client = MagicMock()
    mock_client.get_all_labels.side_effect = Exception("simulated Chatwoot API failure")

    with patch("services.chatwoot.ChatwootClient", return_value=mock_client):
        result = assign_chatwoot_labels(account_id, conversation_id, labels)

    _assert_json_parseable(
        result, "assign_chatwoot_labels",
        account_id=account_id, conversation_id=conversation_id, labels=labels,
    )


@given(
    account_id=st.integers(min_value=1, max_value=10_000),
    conversation_id=nonempty_text_st,
    labels=label_list_st,
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_assign_chatwoot_labels_always_returns_json_on_success(
    account_id, conversation_id, labels,
):
    """
    **Validates: Requirements 2.7, 8.1, 8.2**

    Property 7c (success path): assign_chatwoot_labels returns a JSON-parseable string
    when the Chatwoot client succeeds.
    """
    mock_client = MagicMock()
    # Return empty existing labels so all provided labels look "new"
    mock_client.get_all_labels.return_value = []
    mock_client.create_label.return_value = None
    mock_client.set_conversation_labels.return_value = None

    with patch("services.chatwoot.ChatwootClient", return_value=mock_client):
        result = assign_chatwoot_labels(account_id, conversation_id, labels)

    _assert_json_parseable(
        result, "assign_chatwoot_labels",
        account_id=account_id, conversation_id=conversation_id, labels=labels,
    )


# ---------------------------------------------------------------------------
# Property 7d — create_lead always returns JSON
# ---------------------------------------------------------------------------

@given(
    account_id=any_int_st,
    conversation_id=any_text_st,
    name=optional_text_st_p7,
    phone=optional_text_st_p7,
    intent=optional_text_st_p7,
    city=optional_text_st_p7,
    budget=optional_text_st_p7,
)
@settings(
    max_examples=150,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_create_lead_always_returns_json(
    account_id, conversation_id, name, phone, intent, city, budget,
):
    """
    **Validates: Requirements 2.7, 8.1, 8.2**

    Property 7d: create_lead always returns a JSON-parseable string for any combination
    of arguments, including those that cause the state store to raise.
    """
    mock_store = MagicMock()
    mock_store.upsert_lead.side_effect = Exception("simulated DB failure")

    with patch("services.state_store._get_shared_store", return_value=mock_store):
        result = create_lead(
            account_id=account_id,
            conversation_id=conversation_id,
            name=name,
            phone=phone,
            intent=intent,
            city=city,
            budget=budget,
        )

    _assert_json_parseable(
        result, "create_lead",
        account_id=account_id, conversation_id=conversation_id,
    )


@given(
    account_id=st.integers(min_value=1, max_value=10_000),
    conversation_id=nonempty_text_st,
    name=optional_text_st_p7,
    phone=optional_text_st_p7,
    intent=optional_text_st_p7,
    city=optional_text_st_p7,
    budget=optional_text_st_p7,
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_create_lead_always_returns_json_on_success(
    account_id, conversation_id, name, phone, intent, city, budget,
):
    """
    **Validates: Requirements 2.7, 8.1, 8.2**

    Property 7d (success path): create_lead returns a JSON-parseable string when the
    store upsert succeeds.
    """
    import uuid
    mock_store = MagicMock()
    mock_store.upsert_lead.return_value = uuid.uuid4()

    with patch("services.state_store._get_shared_store", return_value=mock_store):
        result = create_lead(
            account_id=account_id,
            conversation_id=conversation_id,
            name=name,
            phone=phone,
            intent=intent,
            city=city,
            budget=budget,
        )

    _assert_json_parseable(
        result, "create_lead",
        account_id=account_id, conversation_id=conversation_id,
    )


# ---------------------------------------------------------------------------
# Property 7e — update_lead_stage always returns JSON
# ---------------------------------------------------------------------------

# Any stage string — includes valid and invalid values
stage_st = st.text(max_size=100)

@given(
    conversation_id=any_text_st,
    stage=stage_st,
    notes=optional_text_st_p7,
)
@settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_update_lead_stage_always_returns_json(conversation_id, stage, notes):
    """
    **Validates: Requirements 2.7, 8.1, 8.2**

    Property 7e: update_lead_stage always returns a JSON-parseable string for any
    combination of arguments — including invalid stage strings and DB failures.
    """
    mock_store = MagicMock()
    mock_store.update_lead_stage.side_effect = Exception("simulated DB failure")

    with patch("services.state_store._get_shared_store", return_value=mock_store):
        result = update_lead_stage(
            conversation_id=conversation_id,
            stage=stage,
            notes=notes,
        )

    _assert_json_parseable(
        result, "update_lead_stage",
        conversation_id=conversation_id, stage=stage, notes=notes,
    )


# ---------------------------------------------------------------------------
# Property 7f — schedule_followup always returns JSON
# ---------------------------------------------------------------------------

@given(
    conversation_id=any_text_st,
    account_id=any_int_st,
    delay_hours=any_int_st,
    note=optional_text_st_p7,
)
@settings(
    max_examples=150,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_schedule_followup_always_returns_json(
    conversation_id, account_id, delay_hours, note,
):
    """
    **Validates: Requirements 2.7, 8.1, 8.2**

    Property 7f: schedule_followup always returns a JSON-parseable string for any
    combination of arguments, including those that cause the state store to raise.
    """
    mock_store = MagicMock()
    mock_store.insert_followup.side_effect = Exception("simulated DB failure")

    with patch("services.state_store._get_shared_store", return_value=mock_store):
        result = schedule_followup(
            conversation_id=conversation_id,
            account_id=account_id,
            delay_hours=delay_hours,
            note=note,
        )

    _assert_json_parseable(
        result, "schedule_followup",
        conversation_id=conversation_id, account_id=account_id, delay_hours=delay_hours,
    )


@given(
    conversation_id=nonempty_text_st,
    account_id=st.integers(min_value=1, max_value=10_000),
    delay_hours=st.integers(min_value=1, max_value=720),
    note=optional_text_st_p7,
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_schedule_followup_always_returns_json_on_success(
    conversation_id, account_id, delay_hours, note,
):
    """
    **Validates: Requirements 2.7, 8.1, 8.2**

    Property 7f (success path): schedule_followup returns a JSON-parseable string when
    the store insert succeeds.
    """
    mock_store = MagicMock()
    mock_store.insert_followup.return_value = 42

    with patch("services.state_store._get_shared_store", return_value=mock_store):
        result = schedule_followup(
            conversation_id=conversation_id,
            account_id=account_id,
            delay_hours=delay_hours,
            note=note,
        )

    _assert_json_parseable(
        result, "schedule_followup",
        conversation_id=conversation_id, account_id=account_id, delay_hours=delay_hours,
    )


# ---------------------------------------------------------------------------
# Property 9 — Lead stage validation
# ---------------------------------------------------------------------------

from real_estate_tools.crm_tools import update_lead_stage, VALID_STAGES  # noqa: E402

# Strategies
# Valid stages: drawn from the known-good set
valid_stage_st = st.sampled_from(sorted(VALID_STAGES))

# Invalid stages: any text that is NOT a member of VALID_STAGES.
# We combine:
#   1. arbitrary text strings (most will be invalid)
#   2. near-misses generated by mutating valid stage names
_invalid_stage_examples = [
    "",              # empty string
    " ",             # whitespace
    "NEW_LEAD",      # wrong case
    "new lead",      # space instead of underscore
    "newlead",       # missing underscore
    "invalid_stage", # completely wrong
    "hot",           # partial match
    "lead",          # partial match
    "0",             # numeric string
]

invalid_stage_st = st.one_of(
    st.text(min_size=0, max_size=100).filter(lambda s: s not in VALID_STAGES),
    st.sampled_from(_invalid_stage_examples),
)

# conversation_id strategy (non-empty strings)
_conv_id_st = st.text(min_size=1, max_size=200)


# Helper: build a mock StateStore
def _make_mock_store():
    """Return a MagicMock that mimics StateStore for update_lead_stage calls."""
    mock_store = MagicMock()
    mock_store.update_lead_stage.return_value = None
    return mock_store


# ---------------------------------------------------------------------------
# Property 9a — valid stage → success response
# ---------------------------------------------------------------------------

@given(
    conversation_id=_conv_id_st,
    stage=valid_stage_st,
    notes=st.one_of(st.none(), st.text(min_size=0, max_size=200)),
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_update_lead_stage_valid_returns_updated_true(conversation_id, stage, notes):
    """
    **Validates: Requirements 3.6, 3.7**

    Property 9 (valid stage path): For any valid stage, `update_lead_stage` must:
      - Return valid JSON parseable by json.loads()
      - Contain {"updated": true, "stage": <stage>}
      - Call the DB store exactly once (with the correct stage)
    """
    mock_store = _make_mock_store()

    with patch("services.state_store._get_shared_store", return_value=mock_store):
        result_str = update_lead_stage(
            conversation_id=conversation_id,
            stage=stage,
            notes=notes,
        )

    # Must return valid JSON — never raise
    try:
        parsed = json.loads(result_str)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"update_lead_stage did not return valid JSON for valid stage={stage!r}: {exc!r}. "
            f"Raw output: {result_str!r}"
        )

    # Must not return an error for a valid stage
    assert "error" not in parsed, (
        f"update_lead_stage returned an error for valid stage={stage!r}: {parsed.get('error')}"
    )

    # Must include {"updated": true, "stage": <stage>}
    assert parsed.get("updated") is True, (
        f"Expected 'updated' == True for stage={stage!r}, got {parsed.get('updated')!r}"
    )
    assert parsed.get("stage") == stage, (
        f"Expected 'stage' == {stage!r}, got {parsed.get('stage')!r}"
    )

    # DB store must have been called exactly once
    mock_store.update_lead_stage.assert_called_once()
    call_kwargs = mock_store.update_lead_stage.call_args
    # Stage passed to store must match the requested stage
    passed_stage = (
        call_kwargs.kwargs.get("stage")
        if call_kwargs.kwargs.get("stage") is not None
        else call_kwargs.args[1]
    )
    assert passed_stage == stage, (
        f"Stage passed to DB store ({passed_stage!r}) != requested stage ({stage!r})"
    )


# ---------------------------------------------------------------------------
# Property 9b — invalid stage → error response, DB never touched
# ---------------------------------------------------------------------------

@given(
    conversation_id=_conv_id_st,
    stage=invalid_stage_st,
    notes=st.one_of(st.none(), st.text(min_size=0, max_size=200)),
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_update_lead_stage_invalid_returns_error_no_db_call(conversation_id, stage, notes):
    """
    **Validates: Requirements 3.6, 3.7**

    Property 9 (invalid stage path): For any stage string NOT in VALID_STAGES,
    `update_lead_stage` must:
      - Return valid JSON parseable by json.loads()
      - Contain an "error" key (never {"updated": true})
      - NOT call the DB store at all (stage validation before any DB access)
      - Never raise an exception
    """
    mock_store = _make_mock_store()

    with patch("services.state_store._get_shared_store", return_value=mock_store):
        result_str = update_lead_stage(
            conversation_id=conversation_id,
            stage=stage,
            notes=notes,
        )

    # Must return valid JSON — never raise
    try:
        parsed = json.loads(result_str)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"update_lead_stage did not return valid JSON for invalid stage={stage!r}: {exc!r}. "
            f"Raw output: {result_str!r}"
        )

    # Must return an error for an invalid stage
    assert "error" in parsed, (
        f"Expected 'error' key for invalid stage={stage!r}, got keys: {list(parsed.keys())}"
    )

    # Must NOT return updated=true
    assert parsed.get("updated") is not True, (
        f"update_lead_stage returned 'updated: true' for invalid stage={stage!r}"
    )

    # DB store must NEVER be called for an invalid stage (requirement 3.7)
    mock_store.update_lead_stage.assert_not_called(), (
        f"DB store was called despite invalid stage={stage!r}"
    )
    # Also ensure _get_shared_store itself was never called (validation happens first)
    # (The with-patch means any call would use the mock, but we verify update_lead_stage wasn't invoked)


# ---------------------------------------------------------------------------
# Property 11 — schedule_followup delay clamping
# ---------------------------------------------------------------------------

from datetime import datetime, timezone, timedelta  # noqa: E402
from real_estate_tools.followup_tools import schedule_followup  # noqa: E402

# Strategy: any integer that could be passed as delay_hours (including extreme values)
delay_hours_st = st.integers(min_value=-(2**31), max_value=2**31 - 1)


def _make_mock_store(followup_id=42):
    """Return a mock StateStore whose insert_followup returns a fixed ID."""
    mock_store = MagicMock()
    mock_store.insert_followup.return_value = followup_id
    return mock_store


@given(delay_hours=delay_hours_st)
@settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_schedule_followup_delay_clamping(delay_hours):
    """
    **Validates: Requirements 4.2, 4.3**

    Property 11: Follow-up delay clamping — for any integer `delay_hours`,
    the delay used to compute `scheduled_at` is always clamped to [1, 720].

    Verification approach:
      - The StateStore is mocked so no real DB is required.
      - `scheduled_at` is parsed from the returned JSON.
      - The difference between `scheduled_at` and the call time must be in
        [1 hour, 720 hours].
    """
    mock_store = _make_mock_store()

    # Record the time window around the call so we can bound `scheduled_at`
    before_call = datetime.now(timezone.utc)

    with patch("services.state_store._get_shared_store", return_value=mock_store):
        result_str = schedule_followup(
            conversation_id="conv-test-123",
            account_id=1,
            delay_hours=delay_hours,
        )

    after_call = datetime.now(timezone.utc)

    # Must always return valid JSON
    try:
        parsed = json.loads(result_str)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"schedule_followup did not return valid JSON: {exc!r}. "
            f"Raw output: {result_str!r}"
        ) from exc

    # Must not be an error response — clamping is always well-defined
    assert "error" not in parsed, (
        f"schedule_followup returned an error for delay_hours={delay_hours}: "
        f"{parsed.get('error')}"
    )

    # Must contain required keys
    assert "scheduled_at" in parsed, (
        f"Response JSON missing 'scheduled_at'. Keys: {list(parsed.keys())}"
    )

    # Parse scheduled_at and compute the effective delay
    scheduled_at = datetime.fromisoformat(parsed["scheduled_at"])
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

    # Lower bound: scheduled_at must be at least (before_call + 1h)
    min_scheduled = before_call + timedelta(hours=1)
    assert scheduled_at >= min_scheduled, (
        f"scheduled_at ({scheduled_at.isoformat()}) is earlier than "
        f"now + 1h ({min_scheduled.isoformat()}) for delay_hours={delay_hours}. "
        "Clamping to minimum of 1 hour was not applied."
    )

    # Upper bound: scheduled_at must be at most (after_call + 720h)
    max_scheduled = after_call + timedelta(hours=720)
    assert scheduled_at <= max_scheduled, (
        f"scheduled_at ({scheduled_at.isoformat()}) exceeds "
        f"now + 720h ({max_scheduled.isoformat()}) for delay_hours={delay_hours}. "
        "Clamping to maximum of 720 hours was not applied."
    )

    # Cross-check: the delay stored in the DB call must also be in [1, 720]
    assert mock_store.insert_followup.called, "insert_followup was not called"
    call_kwargs = mock_store.insert_followup.call_args
    stored_scheduled_at_arg = (
        call_kwargs.kwargs.get("scheduled_at") or call_kwargs.args[3]
    )
    stored_dt = datetime.fromisoformat(stored_scheduled_at_arg)
    if stored_dt.tzinfo is None:
        stored_dt = stored_dt.replace(tzinfo=timezone.utc)

    # The delay passed to insert_followup must also be within [1h, 720h] of call time
    effective_delta = stored_dt - before_call
    effective_hours = effective_delta.total_seconds() / 3600.0

    assert 1.0 <= effective_hours <= 721.0, (
        # 721 gives 1 second of slack for execution time between before_call and the
        # actual datetime.now() inside schedule_followup.
        f"Delay stored in DB ({effective_hours:.4f}h) is outside [1, 720] "
        f"for input delay_hours={delay_hours}."
    )
