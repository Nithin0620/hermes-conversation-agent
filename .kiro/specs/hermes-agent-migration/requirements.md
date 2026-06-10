# Requirements Document

## Introduction

This document formalises the requirements for migrating the Hermes real-estate chatbot from its
current monolithic Flask + custom LLM intent engine to a Hermes Agent architecture. The migration
preserves all existing external contracts (webhook endpoint, Chatwoot integration, PostgreSQL
auction schema) while replacing the hand-rolled `llm.py` reasoning layer with a Hermes `AIAgent`
backed by purpose-built, independently testable tools for property search, CRM management, and
follow-up scheduling. The migration is delivered in five phases, each independently deployable
without breaking the live system.

## Glossary

- **Webhook**: The Flask `POST /webhook` HTTP endpoint that receives Chatwoot event payloads.
- **HermesAgentService**: The Python service class (`services/hermes_agent.py`) that wraps the
  Hermes `AIAgent`, manages conversation history, and returns reply strings to the webhook handler.
- **AIAgent**: The `NousResearch/hermes-agent` `AIAgent` class that drives LLM reasoning and tool
  dispatch.
- **PropertyTools**: The module `tools/property_tools.py` exposing `search_properties` and
  `get_property_details` as Hermes tools.
- **CRMTools**: The module `tools/crm_tools.py` exposing `create_lead`, `update_lead_stage`, and
  `assign_chatwoot_labels` as Hermes tools.
- **FollowUpTools**: The module `tools/followup_tools.py` exposing `schedule_followup` as a
  Hermes tool.
- **FollowUpWorker**: The background process (`workers/followup_worker.py`) that polls the
  `hermes_followups` table and sends due follow-up messages via Chatwoot.
- **StateStore**: The existing `services/state_store.py` class managing conversation state and
  message history in PostgreSQL JSONB tables.
- **ChatwootClient**: The existing `services/chatwoot.py` HTTP client for the Chatwoot REST API.
- **DatabaseService**: The existing `services/database.py` PostgreSQL client for the auction
  database.
- **Tool_Handler**: Any of the callable functions registered in the Hermes tool registry
  (`search_properties`, `get_property_details`, `create_lead`, `update_lead_stage`,
  `assign_chatwoot_labels`, `schedule_followup`).
- **HERMES_ENABLED**: An environment variable feature flag that controls whether the Hermes agent
  code path or the legacy `handle_conversation` code path is active (used during Phase 2).
- **hermes_leads**: A new PostgreSQL table storing CRM lead records keyed by `conversation_id`.
- **hermes_followups**: A new PostgreSQL table storing scheduled follow-up tasks with a
  `scheduled_at` timestamp and a `status` field.
- **REAL_ESTATE_SYSTEM_PROMPT**: The constant string in `config/system_prompt.py` injected as the
  system prompt for every `AIAgent` instance.

---

## Requirements

### Requirement 1: Webhook Event Handling and Conversation Reply

**User Story:** As a WhatsApp user, I want the chatbot to reply to every message I send through
Chatwoot, so that I receive helpful property information without unresponsive gaps.

#### Acceptance Criteria

1. WHEN a `POST /webhook` request is received with `event == "message_created"` and
   `message_type == "incoming"`, THE Webhook SHALL delegate the user message to
   `HermesAgentService.run()` and send exactly one reply to Chatwoot via
   `ChatwootClient.send_message()`.

2. WHEN a `POST /webhook` request is received with any `event` or `message_type` value other
   than `message_created` / `incoming`, THE Webhook SHALL return a `{"status": "ignored"}`
   response and SHALL NOT send any message to Chatwoot.

3. IF `HermesAgentService.run()` raises any exception, THEN THE Webhook SHALL immediately send
   one generic error reply to Chatwoot (without retrying the service call) and SHALL return
   HTTP 200.

4. THE HermesAgentService SHALL return a non-empty string from every call to `run()`, regardless
   of whether the underlying `AIAgent` succeeds or raises an exception.

5. WHEN `HermesAgentService.run()` is called concurrently for different conversations, THE
   HermesAgentService SHALL create a fresh `AIAgent` instance per call so that no mutable agent
   state is shared across concurrent requests.

---

### Requirement 2: Property Search Tool

**User Story:** As a prospective buyer, I want the chatbot to search bank auction properties by
city, type, budget, and institution, so that I can quickly find listings that match my criteria.

#### Acceptance Criteria

1. WHEN `search_properties` is called with any combination of `city`, `asset_type`,
   `asset_category`, `institution`, `min_price`, `max_price`, `limit`, and `offset` parameters,
   THE PropertyTools SHALL return a valid JSON string with keys `results`, `total`, `offset`, and
   `limit`.

2. WHEN `search_properties` is called with a `limit` value less than 1, THE PropertyTools SHALL
   clamp `limit` to `1` before querying the database.

3. WHEN `search_properties` is called with a `limit` value greater than 10, THE PropertyTools
   SHALL clamp `limit` to `10` before querying the database.

4. WHEN `search_properties` is called with an `offset` value, THE PropertyTools SHALL use that
   `offset` value unchanged provided it is non-negative, and the returned JSON SHALL include the
   same `offset` value.

5. WHEN `get_property_details` is called with a `listing_id` that exists in the auction database,
   THE PropertyTools SHALL return a JSON string containing all `COLUMN_LABELS` fields for that
   listing.

6. WHEN `get_property_details` is called with a `listing_id` that does not exist in the auction
   database, THE PropertyTools SHALL return a JSON string with an `error` key describing the
   missing listing.

7. IF any database error occurs during `search_properties` or `get_property_details`, THEN THE
   PropertyTools SHALL return a JSON string with an `error` key and SHALL NOT raise an exception.

8. THE PropertyTools SHALL truncate `asset_details`, `asset_schedule`, and `asset_address` fields
   to 200 characters in `search_properties` results to keep response payloads compact.

---

### Requirement 3: CRM Tools

**User Story:** As a sales agent, I want the chatbot to automatically classify conversations,
capture lead data, and update lead stages in the CRM, so that I can prioritise follow-up without
manual data entry.

#### Acceptance Criteria

1. WHEN `assign_chatwoot_labels` is called with a `labels` list of any length, THE CRMTools SHALL
   assign at most 6 labels to the conversation and SHALL silently truncate any excess labels
   beyond the sixth.

2. WHEN `assign_chatwoot_labels` is called with a label string that does not yet exist in the
   Chatwoot account, THE CRMTools SHALL create that label via the Chatwoot API before assigning
   it to the conversation.

3. WHEN `assign_chatwoot_labels` encounters a Chatwoot API error, THE CRMTools SHALL return a
   JSON string with an `error` key and SHALL NOT raise an exception, so that label failures never
   block the user reply.

4. WHEN `create_lead` is called with a `conversation_id` and `account_id` plus any subset of
   optional fields (`name`, `phone`, `intent`, `city`, `budget`), THE CRMTools SHALL upsert a
   row in the `hermes_leads` table and return a JSON string containing `lead_id` and `status`.

5. WHEN `create_lead` is called for a `conversation_id` that already has a row in `hermes_leads`,
   THE CRMTools SHALL update the existing row rather than creating a duplicate.

6. WHEN `update_lead_stage` is called with a `stage` value that is one of `new_lead`,
   `qualified_lead`, `hot_lead`, `warm_lead`, or `cold_lead`, THE CRMTools SHALL update the
   `stage` column of the matching `hermes_leads` row and return
   `{"updated": true, "stage": "<value>"}`.

7. WHEN `update_lead_stage` is called with a `stage` value that is not in the valid set, THE
   CRMTools SHALL return a JSON string with an `error` key describing the invalid stage and SHALL
   NOT write to the database.

8. IF any database error occurs during `create_lead` or `update_lead_stage`, THEN THE CRMTools
   SHALL return a JSON string with an `error` key and SHALL NOT raise an exception.

---

### Requirement 4: Follow-Up Scheduling Tool and Worker

**User Story:** As a sales agent, I want the chatbot to schedule deferred re-engagement messages
for users who ask to be contacted later, so that no interested lead is lost due to timing.

#### Acceptance Criteria

1. WHEN `schedule_followup` is called with a `delay_hours` value in `[1, 720]`, THE
   FollowUpTools SHALL validate the value is within bounds, then insert a row into
   `hermes_followups` with `status = 'pending'` and `scheduled_at` equal to the current UTC
   time plus `delay_hours`.

2. WHEN `schedule_followup` is called with a `delay_hours` value less than 1, THE FollowUpTools
   SHALL clamp `delay_hours` to `1` before computing `scheduled_at`.

3. WHEN `schedule_followup` is called with a `delay_hours` value greater than 720, THE
   FollowUpTools SHALL clamp `delay_hours` to `720` before computing `scheduled_at`.

4. THE FollowUpTools SHALL always produce a `scheduled_at` timestamp that is strictly greater
   than the current UTC time at the moment of the call.

5. WHEN `schedule_followup` returns successfully, THE FollowUpTools SHALL return a JSON string
   containing `followup_id` and `scheduled_at` in ISO 8601 format.

6. IF any database error occurs during `schedule_followup`, THEN THE FollowUpTools SHALL return
   a JSON string with an `error` key and SHALL NOT raise an exception.

7. WHILE the FollowUpWorker is running, THE FollowUpWorker SHALL poll the `hermes_followups`
   table for rows where `status = 'pending'` and `scheduled_at <= NOW()` at an interval of no
   more than 5 minutes.

8. WHEN the FollowUpWorker finds a due follow-up row, THE FollowUpWorker SHALL send the follow-up
   message to the corresponding Chatwoot conversation via `ChatwootClient.send_message()` and
   update the row `status` to `'sent'` and set `sent_at` to the current timestamp.

---

### Requirement 5: Migration Compatibility Constraints

**User Story:** As a system operator, I want the migration to preserve all existing external
contracts, so that the live production system continues to function without any breaking changes
during each phase.

#### Acceptance Criteria

1. THE Webhook SHALL expose the same `POST /webhook` route signature, accept the same Chatwoot
   payload shape, and return the same HTTP response codes after the migration as it did before.

2. THE HermesAgentService SHALL call `ChatwootClient.send_message()` with the same
   `(account_id, conversation_id, content)` signature and `ChatwootClient.set_conversation_labels()`
   with the same `(account_id, conversation_id, labels)` signature as the pre-migration code.

3. THE DatabaseService auction table schema (`free_banks_auctions_stage_2_22_38_05_08_06_26`)
   SHALL remain unmodified by the migration; all tool access to this table SHALL be read-only.

4. THE StateStore `hermes_conversations` and `hermes_messages` tables SHALL remain unmodified
   in schema and continue to be written and read by `HermesAgentService` through Phase 3 of
   the migration.

5. WHERE the `HERMES_ENABLED` environment variable is set to `"false"`, THE Webhook SHALL route
   incoming messages through the legacy `handle_conversation` code path, fall back to sending
   the result via `ChatwootClient.send_message()`, and SHALL NOT invoke `HermesAgentService`.

6. WHERE the `HERMES_ENABLED` environment variable is set to `"true"`, THE Webhook SHALL route
   incoming messages through `HermesAgentService.run()`, send the result via
   `ChatwootClient.send_message()`, and SHALL NOT invoke the legacy `handle_conversation`
   function.

---

### Requirement 6: Hermes Agent Configuration

**User Story:** As a developer, I want the Hermes `AIAgent` to be consistently configured with
the correct model, safety limits, and tool whitelist, so that every conversation uses the
intended LLM and only the real-estate tools.

#### Acceptance Criteria

1. WHEN `HermesAgentService` creates an `AIAgent` instance, THE HermesAgentService SHALL set
   `model` to `"groq/llama-3.3-70b-versatile"` and `base_url` to
   `"https://api.groq.com/openai/v1"`.

2. WHEN `HermesAgentService` creates an `AIAgent` instance for Phases 1 through 3, THE
   HermesAgentService SHALL set `quiet_mode=True`, `skip_context_files=True`, and
   `skip_memory=True`.

3. WHEN `HermesAgentService` creates an `AIAgent` instance, THE HermesAgentService SHALL pass
   `enabled_toolsets=["real_estate"]` to restrict the agent to the custom real-estate toolset
   only.

4. WHEN `HermesAgentService` creates an `AIAgent` instance, THE HermesAgentService SHALL pass
   `max_iterations=10` to cap the maximum number of LLM reasoning steps per request.

5. WHEN `HermesAgentService` creates an `AIAgent` instance, THE HermesAgentService SHALL inject
   the `REAL_ESTATE_SYSTEM_PROMPT` constant as the `ephemeral_system_prompt` parameter.

6. WHEN `HermesAgentService.run()` augments the user message before passing it to `AIAgent`,
   THE HermesAgentService SHALL prepend the `account_id` and `conversation_id` as a context
   prefix so that tools can access these values without requiring the user to supply them.

---

### Requirement 7: Data Model — New Tables

**User Story:** As a developer, I want the new CRM and follow-up tables to be created
automatically with the correct schema, so that the application can persist lead and scheduling
data without manual database setup.

#### Acceptance Criteria

1. WHEN the application initialises, THE StateStore SHALL create the `hermes_leads` table if it
   does not exist, with columns: `id` (UUID primary key, default `gen_random_uuid()`),
   `conversation_id` (TEXT, UNIQUE NOT NULL), `account_id` (INTEGER NOT NULL), `name` (TEXT),
   `phone` (TEXT), `city` (TEXT), `budget` (TEXT), `intent` (TEXT),
   `stage` (TEXT NOT NULL, default `'new_lead'`), `notes` (TEXT),
   `created_at` (TIMESTAMPTZ, default NOW()), `updated_at` (TIMESTAMPTZ, default NOW()).

2. WHEN the application initialises, THE StateStore SHALL create the `hermes_followups` table if
   it does not exist, with columns: `id` (SERIAL primary key), `conversation_id` (TEXT NOT NULL),
   `account_id` (INTEGER NOT NULL), `note` (TEXT), `scheduled_at` (TIMESTAMPTZ NOT NULL),
   `sent_at` (TIMESTAMPTZ), `status` (TEXT NOT NULL, default `'pending'`).

3. WHEN the `hermes_followups` table is created, THE StateStore SHALL create an index on
   `(scheduled_at)` filtered to rows where `status = 'pending'` to optimise worker polling
   queries.

4. IF any table or index creation fails during application initialisation, THEN THE StateStore
   SHALL roll back all initialisation changes made in that transaction so the database is not
   left in a partially initialised state.

---

### Requirement 8: Tool Output Contract

**User Story:** As a developer integrating with the Hermes tool registry, I want every tool
handler to always return a parseable JSON string and never raise an unhandled exception, so that
the agent runtime can reliably process tool results without crashing.

#### Acceptance Criteria

1. THE Tool_Handler SHALL always return a value that is parseable by `json.loads()` — never a
   raw Python dict, never `None`, and never a plain text string.

2. IF any Tool_Handler encounters an unhandled internal error, THEN THE Tool_Handler SHALL return
   a JSON string containing an `error` key with a human-readable description and SHALL NOT
   propagate the exception to the Hermes runtime.

3. THE Tool_Handler SHALL return a response within the timeout imposed by `max_iterations=10`
   on the parent `AIAgent`; individual tool calls do not have a separate timeout requirement
   beyond the database and HTTP client default timeouts.

---

### Requirement 9: Testing Coverage

**User Story:** As a developer, I want the migration to include property-based, unit, and
integration tests for all new components, so that correctness is verified automatically and
regressions are caught early.

#### Acceptance Criteria

1. THE test suite SHALL include `hypothesis`-based property tests for `search_properties`,
   `schedule_followup`, `assign_chatwoot_labels`, and `update_lead_stage` that verify their
   respective invariants across a wide range of generated inputs.

2. THE test suite SHALL include unit tests with mocked `DatabaseService` and `ChatwootClient`
   for every Tool_Handler, covering at least: successful execution, missing/invalid input, and
   database or HTTP error conditions.

3. THE test suite SHALL include an integration test that exercises a full conversation turn from
   `POST /webhook` through `HermesAgentService.run()`, a tool call, the database query, and the
   `ChatwootClient.send_message()` call against a seeded local PostgreSQL instance.

4. THE test suite SHALL include an integration test that verifies two sequential `search_properties`
   calls with `offset=0` and `offset=5` return non-overlapping result sets.

5. THE test suite SHALL include an integration test that verifies the label round-trip:
   `assign_chatwoot_labels` creates a new label in Chatwoot and `get_all_labels` returns that
   label in the subsequent fetch.

6. THE test suite SHALL include an integration test for the FollowUpWorker that inserts a
   `hermes_followups` row with `scheduled_at` in the past and verifies the worker processes it
   and marks the row `status = 'sent'`.
