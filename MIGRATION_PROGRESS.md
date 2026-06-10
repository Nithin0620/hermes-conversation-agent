# Hermes Agent Migration — What Was Done

## Summary

Migrated the real-estate chatbot from a monolithic Flask + custom LLM intent engine (`llm.py`)
to a **Hermes Agent** architecture. The Flask webhook endpoint, PostgreSQL schema, and Chatwoot
integration are fully preserved. 32 of 40 tasks are complete; the remaining 8 are all optional
integration/property tests that require a live PostgreSQL instance.

**Test suite: 25/25 passing.**

---

## Phase 1 — Install Hermes and scaffold tool layer ✅

### Dependencies & package scaffolding
- **`backend/requirements.txt`** — added `hermes-agent @ git+https://github.com/NousResearch/hermes-agent.git` and `hypothesis==6.131.14`
- **`backend/tools/__init__.py`** — created empty package marker
- **`backend/config/__init__.py`** — created empty package marker
- **`backend/config/system_prompt.py`** — defined `REAL_ESTATE_SYSTEM_PROMPT` constant with Behaviour Rules, Context Available Per Turn, and Tool Use Priority sections

### Property tools (`backend/tools/property_tools.py`)
- `search_properties(city, asset_type, asset_category, institution, min_price, max_price, limit, offset)` — clamps `limit` to `[1, 10]`, calls `_get_shared_db().search_auctions()`, truncates `asset_details`/`asset_schedule`/`asset_address` to 200 chars, returns `{"results", "total", "offset", "limit"}` JSON
- `get_property_details(listing_id)` — fetches single row by `listing_id`, returns all fields as JSON; returns `{"error": ...}` if not found
- Both tools registered in the `real_estate` Hermes toolset
- All exceptions caught; returns `{"error": str(exc)}` — never raises

### CRM tools (`backend/tools/crm_tools.py`)
- `assign_chatwoot_labels(account_id, conversation_id, labels)` — fetches existing labels, creates missing ones, caps at 6 labels via `labels[:6]`; returns `{"assigned": [...], "created": [...]}`
- `create_lead(account_id, conversation_id, name, phone, intent, city, budget)` — upserts to `hermes_leads` (ON CONFLICT DO UPDATE); returns `{"lead_id", "status"}`
- `update_lead_stage(conversation_id, stage, notes)` — validates stage against `{new_lead, qualified_lead, hot_lead, warm_lead, cold_lead}` **before** any DB call; returns `{"error": ...}` for invalid stage without touching DB
- All tools registered in `real_estate` toolset; all exceptions caught

### Follow-up tools (`backend/tools/followup_tools.py`)
- `schedule_followup(conversation_id, account_id, delay_hours, note)` — clamps `delay_hours` to `[1, 720]`, computes `scheduled_at = UTC now + timedelta(hours=delay_hours)`, inserts to `hermes_followups`; returns `{"followup_id", "scheduled_at"}` ISO 8601

### Database singleton (`backend/services/database.py`)
- Added module-level `_shared_db` singleton and `_get_shared_db()` factory — one DB connection per worker process

### State store extensions (`backend/services/state_store.py`)
- Added `upsert_lead(...)` — INSERT … ON CONFLICT (conversation_id) DO UPDATE
- Added `update_lead_stage(conversation_id, stage, notes)` — UPDATE hermes_leads
- Added `insert_followup(conversation_id, account_id, note, scheduled_at)` — INSERT INTO hermes_followups RETURNING id
- Added `get_due_followups()` — SELECT WHERE status='pending' AND scheduled_at <= NOW()
- Added `mark_followup_sent(followup_id)` — UPDATE status='sent', sent_at=NOW()
- Extended `_ensure_tables()` to CREATE `hermes_leads` and `hermes_followups` tables and the partial index on `hermes_followups(scheduled_at) WHERE status='pending'` — all in a single transaction with rollback on failure
- Added `_shared_store` singleton and `_get_shared_store()` factory

### Smoke-test script (`backend/scripts/test_tools.py`)
- Standalone script: imports and calls all tools directly against the dev DB
- Asserts `json.loads()` succeeds on every return value
- Run via: `python scripts/test_tools.py` from `backend/`

### Property tests written (Phase 1)
| Test | Property | Validates |
|---|---|---|
| `test_search_properties_limit_clamping` | Property 6 | Req 2.2, 2.3 |
| `test_search_properties_structural_invariant` | Property 5 | Req 2.1 |
| `test_search_properties_always_returns_json` | Property 7a | Req 2.7, 8.1, 8.2 |
| `test_get_property_details_always_returns_json_*` | Property 7b | Req 2.7, 8.1, 8.2 |
| `test_assign_chatwoot_labels_always_returns_json_*` | Property 7c | Req 2.7, 8.1, 8.2 |
| `test_assign_chatwoot_labels_count_cap` | Property 8 | Req 3.1 |
| `test_create_lead_always_returns_json_*` | Property 7d | Req 2.7, 8.1, 8.2 |
| `test_update_lead_stage_always_returns_json` | Property 7e | Req 2.7, 8.1, 8.2 |
| `test_update_lead_stage_valid_returns_updated_true` | Property 9 (valid) | Req 3.6, 3.7 |
| `test_update_lead_stage_invalid_returns_error_no_db_call` | Property 9 (invalid) | Req 3.6, 3.7 |
| `test_schedule_followup_always_returns_json_*` | Property 7f | Req 2.7, 8.1, 8.2 |
| `test_schedule_followup_delay_clamping` | Property 11 | Req 4.2, 4.3 |

---

## Phase 2 — Integrate HermesAgentService with Flask behind feature flag ✅

### `backend/services/hermes_agent.py` (new file)
- `HermesAgentService.__init__(state_store, model, api_key, base_url, max_iterations)` — stores config; does not instantiate `AIAgent` here
- `_history_to_hermes(rows)` — maps `[{role, content}]` StateStore rows to Hermes `conversation_history` format
- `_make_agent()` — instantiates `AIAgent` with `quiet_mode=True`, `skip_context_files=True`, `ephemeral_system_prompt=REAL_ESTATE_SYSTEM_PROMPT`, `enabled_toolsets=["real_estate"]`, `max_iterations=10`, `platform="whatsapp"`
- `run(conversation_id, user_message, account_id)` — loads history, prepends context prefix, calls `agent.run_conversation()`, persists user + assistant messages, returns reply; catches ALL exceptions and returns fallback string
- `run_label_update(conversation_id, account_id)` — best-effort label classification; swallows and logs all exceptions

### Property & unit tests (Phase 2)
- `test_run_never_raises_on_success` — Property 3 (success path): Req 1.3, 1.4
- `test_run_never_raises_with_varied_agent_responses` — Property 3 (response variation)
- `test_run_never_raises_when_agent_raises` — Property 3 (error path)
- `test_run_never_raises_when_store_raises` — Property 3 (store error path)
- Unit tests: mock `AIAgent` and `StateStore`; test success path, exception path, `run_label_update()` exception suppression, fresh `AIAgent` per call (Property 4)

### `backend/routes/webhook.py` — `HERMES_ENABLED` feature flag added
- Imported `HermesAgentService`; instantiated at module level
- Wrapped handler: `if HERMES_ENABLED == "true"` → `hermes_service.run()` else → legacy `handle_conversation()`

---

## Phase 3 — Promote Hermes to production; remove legacy code ✅

### `backend/routes/webhook.py` — simplified
- Removed `HERMES_ENABLED` flag branch; `hermes_service.run()` is the only code path
- Removed `handle_conversation()`, `load_state()`, `get_filter_hints()`, `serialize_rows()`, `update_labels()` helper functions
- Removed `LLMService` import and `llm =` module-level instance
- Removed all `DEFAULT_STATE` / `store.save_state()` state logic
- Webhook flow: validate event/message_type → `hermes_service.run()` → send reply → `hermes_service.run_label_update()` (best-effort try/except) → return `{"status": "success"}`

### `backend/services/llm.py` — deleted
- Removed after confirming no remaining imports reference it

---

## Phase 4 — Introduce Hermes memory ✅

### `backend/services/hermes_agent.py` — memory enabled
- Changed `skip_memory=False`
- Added `_build_session_db()` helper that creates a `hermes_state.SessionDB` SQLite instance
- `HermesAgentService.__init__` now builds a shared `SessionDB` (reused across per-request `AIAgent` instances)
- `_make_agent()` passes `session_db=self._session_db` to `AIAgent`
- Memory DB path configurable via `HERMES_MEMORY_DB_PATH` env var; defaults to `backend/hermes_memory.db`

---

## Phase 5 — Autonomous follow-up worker ✅

### `backend/workers/__init__.py` — created (empty package marker)

### `backend/workers/followup_worker.py` (new file)
- **Poll loop**: every 300 seconds (5 minutes), calls `_get_shared_store().get_due_followups()`
- **Per-row processing**: builds re-engagement prompt from follow-up note → instantiates `HermesAgentService` → calls `run()` → sends reply via `ChatwootClient.send_message()` → marks row sent via `store.mark_followup_sent()`
- **Per-row error handling**: individual `try/except` per row; logs error and continues — one failure never blocks the rest
- **Graceful shutdown**: `signal.signal(SIGTERM/SIGINT, handler)` sets `_stop_flag`; sleep loop checks flag every second for near-instant shutdown response
- **Runnable**: `python workers/followup_worker.py` from `backend/` (sys.path patched at startup)

### `docker-compose.yml` — `followup-worker` service added
```yaml
followup-worker:
  build:
    context: ./backend
  command: python workers/followup_worker.py
  env_file:
    - ./backend/.env
  depends_on:
    - postgres
    - backend
```

---

## What's Left (Optional tasks only)

These 8 tasks are all marked optional (`*`) in the spec. They require a live PostgreSQL instance or are extra coverage. None block any functionality.

| Task | Description |
|---|---|
| 1.12 | Property 10: follow-up temporal invariant (scheduled_at > NOW()) |
| 3.5 | Unit tests for webhook flag routing |
| 5.3 | Property 1: single reply per incoming message |
| 5.4 | Property 2: webhook ignore contract |
| 5.5 | Integration test: full conversation turn end-to-end |
| 5.6 | Integration test: pagination non-overlap |
| 7.2 | Property 12: message history round-trip |
| 8.2 | Integration test: follow-up worker processes due rows |

---

## Files Created / Modified

| File | Status | What changed |
|---|---|---|
| `backend/requirements.txt` | Modified | Added `hermes-agent` and `hypothesis` |
| `backend/config/__init__.py` | Created | Empty package marker |
| `backend/config/system_prompt.py` | Created | `REAL_ESTATE_SYSTEM_PROMPT` constant |
| `backend/tools/__init__.py` | Created | Empty package marker |
| `backend/tools/property_tools.py` | Created | `search_properties`, `get_property_details` |
| `backend/tools/crm_tools.py` | Created | `assign_chatwoot_labels`, `create_lead`, `update_lead_stage` |
| `backend/tools/followup_tools.py` | Created | `schedule_followup` |
| `backend/services/database.py` | Modified | `_get_shared_db()` singleton |
| `backend/services/state_store.py` | Modified | New table methods, `_get_shared_store()`, `mark_followup_sent()` |
| `backend/services/hermes_agent.py` | Created | `HermesAgentService` with memory support |
| `backend/services/llm.py` | **Deleted** | Replaced by Hermes agent |
| `backend/routes/webhook.py` | Modified | Simplified to Hermes-only; legacy code removed |
| `backend/workers/__init__.py` | Created | Empty package marker |
| `backend/workers/followup_worker.py` | Created | Poll worker with graceful shutdown |
| `backend/scripts/test_tools.py` | Created | Standalone smoke-test script |
| `backend/tests/test_hermes_agent_property.py` | Created | 21 hypothesis property tests |
| `backend/tests/test_hermes_agent_unit.py` | Created | 4 unit tests for `HermesAgentService` |
| `docker-compose.yml` | Modified | Added `followup-worker` service |
