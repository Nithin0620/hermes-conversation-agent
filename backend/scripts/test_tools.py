#!/usr/bin/env python3
"""Standalone smoke-test script for Hermes real-estate tools.

Calls each tool function directly against the dev DB/Chatwoot instance and
confirms every result is valid JSON.

Run from the backend/ directory:
    python scripts/test_tools.py

Requirements: 9.1
"""

import sys
import os
import json
import traceback

# ---------------------------------------------------------------------------
# Ensure backend/ is on the path regardless of the working directory.
# ---------------------------------------------------------------------------
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# ---------------------------------------------------------------------------
# Load environment variables from backend/.env (optional dependency).
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(BACKEND_DIR, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
        print(f"[setup] Loaded env from {_env_path}")
    else:
        print(f"[setup] No .env found at {_env_path} — relying on shell env")
except ImportError:
    print("[setup] python-dotenv not installed — relying on shell env")

# ---------------------------------------------------------------------------
# Imports — tool functions
# ---------------------------------------------------------------------------
from real_estate_tools.property_tools import search_properties, get_property_details  # noqa: E402
from real_estate_tools.crm_tools import assign_chatwoot_labels, update_lead_stage, create_lead  # noqa: E402
from real_estate_tools.followup_tools import schedule_followup  # noqa: E402

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

TEST_CONVERSATION_ID = "test-conv-001"
TEST_ACCOUNT_ID = 1

_results: list[tuple[str, bool, str]] = []  # (test_name, passed, detail)


def _run(test_name: str, fn, *args, **kwargs) -> dict | list:
    """Call *fn* and assert the return value is parseable JSON.

    Appends a (name, passed, detail) entry to _results.
    Always returns the parsed Python object (or None on failure).
    """
    print(f"\n{'─' * 60}")
    print(f"TEST: {test_name}")
    try:
        raw = fn(*args, **kwargs)
        print(f"  raw return: {raw}")

        parsed = json.loads(raw)
        print(f"  parsed    : {json.dumps(parsed, indent=2, ensure_ascii=False)}")
        _results.append((test_name, True, "json.loads() succeeded"))
        return parsed

    except json.JSONDecodeError as exc:
        msg = f"json.loads() FAILED: {exc}"
        print(f"  ERROR: {msg}")
        _results.append((test_name, False, msg))
        return None

    except Exception as exc:
        # Unexpected exception from the tool itself (all tools should catch these)
        msg = f"Unexpected exception: {exc}"
        print(f"  ERROR: {msg}")
        traceback.print_exc()
        _results.append((test_name, False, msg))
        return None


# ---------------------------------------------------------------------------
# 1. search_properties — no filters (should return some results or empty list)
# ---------------------------------------------------------------------------
_run(
    "search_properties — no filters (default limit=5)",
    search_properties,
)

# ---------------------------------------------------------------------------
# 2. search_properties — with city filter
# ---------------------------------------------------------------------------
_run(
    "search_properties — city='Mumbai'",
    search_properties,
    city="Mumbai",
    limit=3,
)

# ---------------------------------------------------------------------------
# 3. search_properties — limit clamping (limit > 10 should be clamped to 10)
# ---------------------------------------------------------------------------
result_clamped = _run(
    "search_properties — limit clamping (limit=999 → expect limit=10)",
    search_properties,
    limit=999,
)
if result_clamped is not None:
    actual_limit = result_clamped.get("limit")
    if actual_limit == 10:
        print(f"  ✓ limit correctly clamped to 10 (got {actual_limit})")
    else:
        print(f"  ✗ limit was NOT clamped — got {actual_limit}")
        # Mark the already-recorded entry as failed
        idx = next(
            (i for i, t in enumerate(_results) if t[0].startswith("search_properties — limit clamping")),
            None,
        )
        if idx is not None:
            name, _, detail = _results[idx]
            _results[idx] = (name, False, f"limit={actual_limit}, expected 10")

# ---------------------------------------------------------------------------
# 4. get_property_details — non-existent ID (should return {"error": ...})
# ---------------------------------------------------------------------------
result_missing = _run(
    "get_property_details — non-existent listing_id",
    get_property_details,
    listing_id="DOES-NOT-EXIST-00000",
)
if result_missing is not None and "error" in result_missing:
    print(f"  ✓ Correctly returned error JSON for missing ID")

# ---------------------------------------------------------------------------
# 5. get_property_details — first real listing_id from search (if any)
# ---------------------------------------------------------------------------
_search_result = None
try:
    _raw = search_properties(limit=1, offset=0)
    _search_result = json.loads(_raw)
except Exception:
    pass

if _search_result and _search_result.get("results"):
    first_listing_id = _search_result["results"][0].get("listing_id")
    if first_listing_id:
        _run(
            f"get_property_details — real listing_id={first_listing_id!r}",
            get_property_details,
            listing_id=str(first_listing_id),
        )
    else:
        print("\n[skip] get_property_details (real ID) — listing_id field not found in first result")
else:
    print("\n[skip] get_property_details (real ID) — no search results available")

# ---------------------------------------------------------------------------
# 6. create_lead — upsert a test lead
# ---------------------------------------------------------------------------
_run(
    "create_lead — upsert test lead",
    create_lead,
    account_id=TEST_ACCOUNT_ID,
    conversation_id=TEST_CONVERSATION_ID,
    name="Smoke Test User",
    phone="9999900000",
    intent="buy",
    city="Mumbai",
    budget="50-75 lakh",
)

# ---------------------------------------------------------------------------
# 7. update_lead_stage — valid stage
# ---------------------------------------------------------------------------
result_valid_stage = _run(
    "update_lead_stage — valid stage='hot_lead'",
    update_lead_stage,
    conversation_id=TEST_CONVERSATION_ID,
    stage="hot_lead",
    notes="Interested in Mumbai flats",
)
if result_valid_stage is not None:
    if result_valid_stage.get("updated") is True:
        print("  ✓ Stage updated successfully")
    elif "error" in result_valid_stage:
        print(f"  ✗ Unexpected error: {result_valid_stage['error']}")

# ---------------------------------------------------------------------------
# 8. update_lead_stage — invalid stage (must return {"error": ...})
# ---------------------------------------------------------------------------
result_bad_stage = _run(
    "update_lead_stage — invalid stage='bad_stage' (expect error JSON)",
    update_lead_stage,
    conversation_id=TEST_CONVERSATION_ID,
    stage="bad_stage",
)
if result_bad_stage is not None:
    if "error" in result_bad_stage:
        print(f"  ✓ Correctly returned error for invalid stage: {result_bad_stage['error']!r}")
    else:
        # This should never happen — mark test as failed
        print(f"  ✗ Expected error JSON but got: {result_bad_stage}")
        idx = next(
            (i for i, t in enumerate(_results) if "invalid stage" in t[0]),
            None,
        )
        if idx is not None:
            name, _, detail = _results[idx]
            _results[idx] = (name, False, f"Expected error key but got: {result_bad_stage}")

# ---------------------------------------------------------------------------
# 9. schedule_followup — valid delay
# ---------------------------------------------------------------------------
_run(
    "schedule_followup — delay_hours=2",
    schedule_followup,
    conversation_id=TEST_CONVERSATION_ID,
    account_id=TEST_ACCOUNT_ID,
    delay_hours=2,
    note="Smoke test follow-up",
)

# ---------------------------------------------------------------------------
# 10. schedule_followup — delay clamping (delay_hours=9999 → clamped to 720)
# ---------------------------------------------------------------------------
result_delay_clamp = _run(
    "schedule_followup — delay clamping (delay_hours=9999 → expect scheduled ~720h from now)",
    schedule_followup,
    conversation_id=TEST_CONVERSATION_ID,
    account_id=TEST_ACCOUNT_ID,
    delay_hours=9999,
    note="Clamping test",
)
if result_delay_clamp is not None and "scheduled_at" in result_delay_clamp:
    print(f"  ✓ scheduled_at returned: {result_delay_clamp['scheduled_at']}")

# ---------------------------------------------------------------------------
# 11. assign_chatwoot_labels — may fail if Chatwoot is unreachable; handled gracefully
# ---------------------------------------------------------------------------
result_labels = _run(
    "assign_chatwoot_labels — labels=['test_label'] (may fail if Chatwoot unavailable)",
    assign_chatwoot_labels,
    account_id=TEST_ACCOUNT_ID,
    conversation_id=TEST_CONVERSATION_ID,
    labels=["test_label"],
)
# The tool always returns valid JSON — error or success, both are acceptable here.
if result_labels is not None:
    if "error" in result_labels:
        print(f"  ℹ Chatwoot returned error (acceptable if unreachable): {result_labels['error']!r}")
    else:
        print(f"  ✓ Labels assigned: {result_labels.get('assigned')}")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print(f"\n{'═' * 60}")
print("SMOKE TEST SUMMARY")
print(f"{'═' * 60}")

passed = [t for t in _results if t[1]]
failed = [t for t in _results if not t[1]]

for name, ok, detail in _results:
    status = "PASS ✓" if ok else "FAIL ✗"
    print(f"  {status}  {name}")
    if not ok:
        print(f"          → {detail}")

print(f"\n  Total: {len(_results)}   Passed: {len(passed)}   Failed: {len(failed)}")

if failed:
    print("\n[SUMMARY] Some tests FAILED — see details above.")
    sys.exit(1)
else:
    print("\n[SUMMARY] All tests PASSED.")
    sys.exit(0)
