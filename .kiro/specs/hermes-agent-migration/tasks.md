# Implementation Plan: Hermes Agent Migration

## Overview

Migrate the real-estate chatbot from a monolithic Flask + custom LLM intent engine to a Hermes
Agent architecture in five independently deployable phases. Each phase builds on the previous one
and ends with a working system; no phase leaves orphaned code that is not wired in. The existing
webhook contract, PostgreSQL schema, and Chatwoot integration are preserved throughout.

---

## Tasks

- [x] 1. Phase 1 — Install Hermes and scaffold tool layer
  - [x] 1.1 Add dependencies to `backend/requirements.txt`
    - Append `hermes-agent @ git+https://github.com/NousResearch/hermes-agent.git`
    - Append `hypothesis==6.131.14` for property tests
    - _Requirements: 9.1_

  - [x] 1.2 Create `backend/tools/__init__.py` and `backend/config/system_prompt.py`
    - `backend/tools/__init__.py` — empty package marker
    - `backend/config/__init__.py` — empty package marker
    - `backend/config/system_prompt.py` — define `REAL_ESTATE_SYSTEM_PROMPT` constant exactly as
      specified in the design (Behaviour Rules, Context Available Per Turn, Tool Use Priority sections)
    - _Requirements: 6.5_

  - [x] 1.3 Implement `backend/tools/property_tools.py`
    - Implement `search_properties(city, asset_type, asset_category, institution, min_price,
      max_price, limit=5, offset=0) -> str` — clamp `limit` to `[1, 10]`, call
      `_get_shared_db().search_auctions()`, truncate `asset_details`/`asset_schedule`/`asset_address`
      to 200 chars, return JSON string `{"results": [...], "total": int, "offset": int, "limit": int}`
    - Implement `get_property_details(listing_id: str) -> str` — fetch single row by `listing_id`,
      return JSON of all `COLUMN_LABELS` fields; return `{"error": ...}` if not found
    - Register both tools in the `real_estate` toolset via `registry.register()`
    - All exceptions must be caught; return `{"error": str(exc)}` JSON string — never raise
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 8.1, 8.2_

  - [x] 1.4 Write property test for `search_properties` limit clamping (Property 6)
    - **Property 6: Search limit clamping** — for any integer `limit`, value used and returned
      is always in `[1, 10]`
    - **Validates: Requirements 2.2, 2.3**

  - [x] 1.5 Write property test for `search_properties` structural invariant (Property 5)
    - **Property 5: Search results structural invariant** — for any filter combination,
      returns valid JSON with keys `results`, `total`, `offset`, `limit` where
      `total >= len(results) >= 0` and `offset >= 0`
    - **Validates: Requirements 2.1**

  - [x] 1.6 Write property test — tools always return JSON (Property 7)
    - **Property 7: Tools always return JSON** — for any arguments including those that
      trigger exceptions, every tool handler returns a value parseable by `json.loads()`
    - **Validates: Requirements 2.7, 8.1, 8.2**

  - [x] 1.7 Implement `backend/tools/crm_tools.py`
    - Implement `assign_chatwoot_labels(account_id, conversation_id, labels) -> str`
      — fetch existing labels, create missing ones via `ChatwootClient`, call
      `set_conversation_labels` with `labels[:6]`; return `{"assigned": [...], "created": [...]}`
    - Implement `create_lead(account_id, conversation_id, name, phone, intent, city, budget) -> str`
      — call `_get_shared_store().upsert_lead()`; return `{"lead_id": str, "status": "created"}`;
      ON CONFLICT on `conversation_id` must update not insert
    - Implement `update_lead_stage(conversation_id, stage, notes) -> str` — validate `stage`
      against `{new_lead, qualified_lead, hot_lead, warm_lead, cold_lead}` before any DB call;
      return `{"error": ...}` for invalid stage; call `_get_shared_store().update_lead_stage()`
    - All exceptions caught; return `{"error": str(exc)}` — never raise
    - Register all three tools in `real_estate` toolset via `registry.register()`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 8.1, 8.2_

  - [x] 1.8 Write property test for label count cap (Property 8)
    - **Property 8: Label count cap** — for any `labels` list of any size,
      at most 6 labels are ever assigned to the Chatwoot conversation
    - **Validates: Requirements 3.1**

  - [x] 1.9 Write property test for lead stage validation (Property 9)
    - **Property 9: Lead stage validation** — for any `stage` string, `update_lead_stage`
      returns `{"updated": true, ...}` for valid stages and `{"error": ...}` for invalid ones;
      never mutates DB on invalid input
    - **Validates: Requirements 3.6, 3.7**

  - [x] 1.10 Implement `backend/tools/followup_tools.py`
    - Implement `schedule_followup(conversation_id, account_id, delay_hours, note) -> str`
      — clamp `delay_hours` to `[1, 720]`; compute `scheduled_at = UTC now + timedelta(hours=delay_hours)`;
      call `_get_shared_store().insert_followup()`; return `{"followup_id": int, "scheduled_at": ISO8601}`
    - All exceptions caught; return `{"error": str(exc)}` — never raise
    - Register tool in `real_estate` toolset
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 8.1, 8.2_

  - [x] 1.11 Write property test for follow-up delay clamping (Property 11)
    - **Property 11: Follow-up delay clamping** — for any integer `delay_hours`,
      the delay used to compute `scheduled_at` is always clamped to `[1, 720]`
    - **Validates: Requirements 4.2, 4.3**

  - [ ]* 1.12 Write property test for follow-up temporal invariant (Property 10)
    - **Property 10: Follow-up scheduling temporal invariant** — for any `delay_hours`
      (after clamping), `schedule_followup` always produces `scheduled_at` strictly greater
      than `NOW()` at the moment of the call
    - **Validates: Requirements 4.1, 4.4**

  - [x] 1.13 Add `_get_shared_db()` singleton to `backend/services/database.py`
    - Add module-level `_shared_db: DatabaseService | None = None`
    - Add `_get_shared_db() -> DatabaseService` function that creates and caches one instance
    - Used by tool modules to avoid multiple connections per worker process
    - _Requirements: 5.3_

  - [x] 1.14 Add new table methods and `_get_shared_store()` to `backend/services/state_store.py`
    - Add `upsert_lead(conversation_id, account_id, name, phone, intent, city, budget) -> UUID`
      — INSERT ... ON CONFLICT (conversation_id) DO UPDATE; refresh `updated_at`
    - Add `update_lead_stage(conversation_id, stage, notes) -> None`
      — UPDATE hermes_leads SET stage, notes, updated_at WHERE conversation_id
    - Add `insert_followup(conversation_id, account_id, note, scheduled_at) -> int`
      — INSERT INTO hermes_followups RETURNING id
    - Add `get_due_followups() -> list[dict]` — SELECT WHERE status='pending' AND scheduled_at <= NOW()
    - Extend `_ensure_tables()` to CREATE the `hermes_leads` and `hermes_followups` tables and
      the partial index on `hermes_followups(scheduled_at) WHERE status='pending'`
    - Add module-level `_shared_store: StateStore | None = None` and
      `_get_shared_store() -> StateStore` singleton factory
    - All table/index creation must happen in a single transaction; roll back on any failure
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 1.15 Write `scripts/test_tools.py` — standalone smoke-test script
    - Import and call `search_properties`, `get_property_details`, `assign_chatwoot_labels`,
      `update_lead_stage`, and `schedule_followup` directly against the dev DB
    - Print each return value and assert `json.loads()` succeeds
    - Execution: `python scripts/test_tools.py` from `backend/` directory
    - _Requirements: 9.1_

- [x] 2. Checkpoint — Phase 1 complete
  - Ensure all tests pass (`python -m pytest backend/tests/ -x`).
  - Run `python scripts/test_tools.py` and confirm all tools return valid JSON.
  - Ask the user if questions arise before proceeding.

- [x] 3. Phase 2 — Integrate HermesAgentService with Flask behind feature flag
  - [x] 3.1 Implement `backend/services/hermes_agent.py`
    - Implement `HermesAgentService.__init__(state_store, model, api_key, base_url, max_iterations)`
      — store configuration; do not instantiate `AIAgent` here (one per request)
    - Implement `_history_to_hermes(rows) -> list[dict]` — map `[{role, content}]` rows to
      Hermes `conversation_history` format
    - Implement `_make_agent() -> AIAgent` — instantiate with `quiet_mode=True`,
      `skip_context_files=True`, `skip_memory=True`, `ephemeral_system_prompt=REAL_ESTATE_SYSTEM_PROMPT`,
      `enabled_toolsets=["real_estate"]`, `max_iterations=10`, `platform="whatsapp"`
    - Implement `run(conversation_id, user_message, account_id) -> str`
      — load history via `_store.get_history()`, prepend context prefix to `user_message`,
      call `agent.run_conversation()`, persist user + assistant messages via `_store.add_message()`,
      return reply; catch ALL exceptions and return fallback string — never raise
    - Implement `run_label_update(conversation_id, account_id) -> None`
      — best-effort: run agent with label classification prompt; swallow and log all exceptions
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 3.2 Write property test — HermesAgentService never raises (Property 3)
    - **Property 3: HermesAgentService never raises** — for any `conversation_id`,
      `user_message`, and `account_id`, `run()` never raises; returns a non-empty string
    - **Validates: Requirements 1.3, 1.4**

  - [x] 3.3 Write unit tests for `HermesAgentService`
    - Mock `AIAgent` and `StateStore`; test `run()` success path, `AIAgent` exception path,
      `run_label_update()` exception suppression
    - Verify a fresh `AIAgent` instance is created per `run()` call (Property 4)
    - _Requirements: 1.4, 1.5, 9.2_

  - [x] 3.4 Modify `backend/routes/webhook.py` — add HERMES_ENABLED feature flag
    - Import `HermesAgentService` and instantiate it at module level alongside existing services
    - Wrap the `handle_conversation` call:
      ```python
      if os.getenv("HERMES_ENABLED", "false").lower() == "true":
          reply = hermes_service.run(conversation_id, user_message, account_id)
      else:
          reply = handle_conversation(conversation_id, user_message, state)
      ```
    - Keep `handle_conversation`, `update_labels`, and `LLMService` import intact (Phase 2 still
      uses them when flag is `false`)
    - _Requirements: 5.1, 5.5, 5.6_

  - [ ]* 3.5 Write unit tests for webhook flag routing
    - Mock `HermesAgentService.run` and `handle_conversation`; verify each is called exclusively
      based on the `HERMES_ENABLED` env var value
    - _Requirements: 5.5, 5.6, 9.2_

- [x] 4. Checkpoint — Phase 2 complete
  - Ensure all tests pass. Confirm `HERMES_ENABLED=false` (default) leaves behaviour unchanged.
  - Ask the user if questions arise before proceeding.

- [x] 5. Phase 3 — Promote Hermes to production; remove legacy code
  - [x] 5.1 Simplify `backend/routes/webhook.py` — remove legacy code path
    - Remove the `HERMES_ENABLED` flag branch; call `hermes_service.run()` directly
    - Remove the `handle_conversation()` function and all helper functions only used by it
      (`load_state`, `get_filter_hints`, `serialize_rows`, `update_labels`)
    - Remove the `LLMService` import and the `llm =` module-level instance
    - Remove `state`-related logic (`DEFAULT_STATE`, `load_state`, `store.save_state` calls)
    - Keep `ChatwootClient`, `StateStore`, `HermesAgentService` imports and usage
    - Webhook should: validate event/message_type → call `hermes_service.run()` → send reply →
      call `hermes_service.run_label_update()` (best-effort, try/except) → return `{"status": "success"}`
    - _Requirements: 1.1, 1.2, 1.3, 5.1_

  - [x] 5.2 Delete `backend/services/llm.py`
    - Remove the file after confirming no remaining imports reference it
    - _Requirements: 5.1_

  - [ ]* 5.3 Write property test — single reply per incoming message (Property 1)
    - **Property 1: Single reply per incoming message** — for any valid incoming webhook payload,
      `ChatwootClient.send_message()` is called exactly once and `HermesAgentService.run()`
      returns a non-empty string
    - **Validates: Requirements 1.1, 1.4**

  - [ ]* 5.4 Write property test — webhook ignore contract (Property 2)
    - **Property 2: Webhook ignore contract** — for any webhook POST where event or message_type
      is not `message_created`/`incoming`, no `send_message()` call is made and response is
      `{"status": "ignored"}`
    - **Validates: Requirements 1.2**

  - [ ]* 5.5 Write integration test — full conversation turn (Requirements 9.3)
    - Exercise full path: `POST /webhook` → `HermesAgentService.run()` → `search_properties`
      tool call → DB query against seeded local PostgreSQL → `ChatwootClient.send_message()`
    - Assert reply is a non-empty string and `send_message` called exactly once
    - _Requirements: 9.3_

  - [ ]* 5.6 Write integration test — pagination non-overlap (Requirements 9.4)
    - Call `search_properties(offset=0)` and `search_properties(offset=5)` against seeded DB
    - Assert the two result sets share no `listing_id` values
    - _Requirements: 9.4_

- [x] 6. Checkpoint — Phase 3 complete
  - Ensure all tests pass. Confirm `llm.py` is deleted and all imports resolve cleanly.
  - Ask the user if questions arise before proceeding.

- [x] 7. Phase 4 — Introduce Hermes memory (replace JSONB state store)
  - [x] 7.1 Update `HermesAgentService._make_agent()` — enable Hermes memory
    - Change `skip_memory=True` to `skip_memory=False`
    - Configure the Hermes memory backend to use the existing `STATE_DATABASE_URL` PostgreSQL
      instance (set via env or constructor argument)
    - _Requirements: 6.2_

  - [ ]* 7.2 Write property test — message history round-trip (Property 12)
    - **Property 12: Message history round-trip** — after `HermesAgentService.run()` completes,
      `StateStore.get_history(conversation_id)` returns a list that includes the user message
      and assistant reply from that turn
    - **Validates: Requirements 6.6**

- [x] 8. Phase 5 — Autonomous follow-up worker
  - [x] 8.1 Implement `backend/workers/followup_worker.py`
    - Poll loop: every 5 minutes, call `_get_shared_store().get_due_followups()`
    - For each due row: instantiate `HermesAgentService`, call `run()` with the follow-up
      note as context to generate a re-engagement message
    - Send reply via `ChatwootClient.send_message(account_id, conversation_id, reply)`
    - Update row: `UPDATE hermes_followups SET status='sent', sent_at=NOW() WHERE id=<id>`
    - Handle individual row failures with try/except; log error and continue to next row
    - Graceful shutdown on `SIGTERM`/`SIGINT`
    - _Requirements: 4.7, 4.8_

  - [ ]* 8.2 Write integration test — follow-up worker processes due rows (Requirements 9.6)
    - Insert a `hermes_followups` row with `scheduled_at` in the past
    - Run one worker poll cycle
    - Assert the row `status` is `'sent'` and `sent_at` is set
    - _Requirements: 4.8, 9.6_

  - [x] 8.3 Add `followup-worker` service to `docker-compose.yml`
    - Add service definition:
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
    - _Requirements: 4.7_

- [x] 9. Final Checkpoint — Ensure all tests pass
  - Run the full test suite (`python -m pytest backend/tests/ -v`).
  - Verify `docker-compose.yml` has the `followup-worker` service.
  - Ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Checkpoints at the end of each phase ensure incremental validation
- Property tests use `hypothesis` and validate universal invariants (Properties 1–12 from design)
- Unit tests validate specific examples, error conditions, and mock-based isolation
- Integration tests require a locally running PostgreSQL instance seeded with sample data
- The legacy `handle_conversation` code path remains intact through Phase 2 (flag=false default)
- `_get_shared_db()` and `_get_shared_store()` singletons avoid multiple DB connections per process
- Hermes `AIAgent` must be created fresh per request — never share an instance across concurrent calls

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.13", "1.14"] },
    { "id": 2, "tasks": ["1.3", "1.7", "1.10"] },
    { "id": 3, "tasks": ["1.4", "1.5", "1.6", "1.8", "1.9", "1.11", "1.12", "1.15"] },
    { "id": 4, "tasks": ["3.1"] },
    { "id": 5, "tasks": ["3.2", "3.3", "3.4"] },
    { "id": 6, "tasks": ["3.5"] },
    { "id": 7, "tasks": ["5.1"] },
    { "id": 8, "tasks": ["5.2", "5.3", "5.4", "5.5", "5.6"] },
    { "id": 9, "tasks": ["7.1"] },
    { "id": 10, "tasks": ["7.2"] },
    { "id": 11, "tasks": ["8.1"] },
    { "id": 12, "tasks": ["8.2", "8.3"] }
  ]
}
```
