# Testing Guide — Hermes Conversation Agent

Step-by-step guide to bring up the full stack, connect everything, and test the Hermes agent
end-to-end. Follow the sections in order.

---

## Prerequisites

Make sure these are installed on your machine:

- Docker + Docker Compose (v2)
- Python 3.12 (with pip)
- `ngrok` or `localtunnel` (to expose local ports to Chatwoot webhooks)
- Git

---

## Step 1 — Environment Files

You have two `.env` files. Both are already populated in this project. Review them once before
starting.

### `backend/.env` (used by the Flask backend and follow-up worker)

```
CHATWOOT_API_URL=https://despair-siberian-unwarlike.ngrok-free.dev   # your Chatwoot public URL
CHATWOOT_ACCESS_TOKEN=<your-chatwoot-agent-bot-token>
HERMES_PORT=5000
GROQ_API_KEY=<your-groq-api-key>
BACKEND_URL=https://shy-moles-cut.loca.lt                            # your backend public tunnel URL
DATABASE_URL=postgresql://Nithin:n%2F12344321@34.93.127.33:5432/foreclosureindia
STATE_DATABASE_URL=postgresql://Nithin:n%2F12344321@34.93.127.33:5432/chatwoot
```

**What each variable does:**

| Variable | Purpose |
|---|---|
| `CHATWOOT_API_URL` | Base URL of your Chatwoot instance (must be reachable from the backend container) |
| `CHATWOOT_ACCESS_TOKEN` | API token for the agent-bot integration in Chatwoot |
| `HERMES_PORT` | Port Flask listens on inside the container (default `5000`) |
| `GROQ_API_KEY` | API key for Groq LLM (used by Hermes AIAgent) |
| `BACKEND_URL` | Public tunnel URL so Chatwoot can POST webhooks to your Flask backend |
| `DATABASE_URL` | PostgreSQL connection string for the **auction/property database** (read-only from tools) |
| `STATE_DATABASE_URL` | PostgreSQL connection string for the **state/messages database** (hermes_conversations, hermes_messages, hermes_leads, hermes_followups tables) |

> ⚠️ **Both database URLs currently point to a remote GCP instance at `34.93.127.33`.
> These will be used as-is. If you want a local DB instead, see Step 3.**

### `.env` (root — used by docker-compose for Chatwoot's `SECRET_KEY_BASE`)

```
SECRET_KEY_BASE=<long-random-string>
DATABASE_URL=postgresql://Nithin:...   # used by Chatwoot's Rails app inside Docker
```

This file is already set. Do not change `SECRET_KEY_BASE` unless you're resetting Chatwoot.

---

## Step 2 — Start All Docker Services

From the project root (`hermes-conversation-agent/`):

```bash
docker compose up --build -d
```

This starts 6 services:

| Service | Port | Description |
|---|---|---|
| `postgres` | internal | PostgreSQL 15 (pgvector) used by Chatwoot Rails |
| `redis` | internal | Redis 7 used by Chatwoot Sidekiq worker |
| `chatwoot` | `3000` | Chatwoot Rails web server |
| `chatwoot-worker` | — | Chatwoot Sidekiq background job processor |
| `backend` | `5000` | Flask webhook server (Hermes agent) |
| `followup-worker` | — | Follow-up polling worker (runs every 5 min) |

**Check all services are healthy:**

```bash
docker compose ps
```

All should show `Up`. If any container crashed:

```bash
docker compose logs <service-name>
# e.g.
docker compose logs backend
docker compose logs chatwoot
```

---

## Step 3 — Database Setup

### Option A — Use the existing remote DB (default, zero setup)

The `DATABASE_URL` and `STATE_DATABASE_URL` in `backend/.env` point to the live GCP instance
at `34.93.127.33`. If you have network access to it, no action is needed. The app will
auto-create the `hermes_leads`, `hermes_followups`, `hermes_conversations`, and
`hermes_messages` tables on first startup.

**Verify tables were created** (run from your machine with psql, or inside the backend container):

```bash
docker compose exec backend python -c "
from services.state_store import StateStore
s = StateStore()
print('Tables created OK')
"
```

### Option B — Use the Docker Compose postgres instead

If you want everything local, change `STATE_DATABASE_URL` in `backend/.env` to:

```
STATE_DATABASE_URL=postgresql://chatwoot:chatwoot@postgres:5432/chatwoot
```

> Note: `DATABASE_URL` (the auction DB) can't be replaced with the local postgres unless you
> load auction data into it. Leave it pointing to the remote GCP instance.

---

## Step 4 — Set Up Chatwoot

### 4.1 Open Chatwoot

Navigate to `http://localhost:3000` in your browser.

On first run you'll see a setup wizard:
1. Create an admin account (email + password)
2. Create a workspace/account name (e.g. `BanksAuctions`)

### 4.2 Run DB migrations (first time only)

```bash
docker compose exec chatwoot bundle exec rails db:chatwoot_prepare
```

Wait for this to complete before proceeding.

### 4.3 Create a WhatsApp / API Inbox

1. Go to **Settings → Inboxes → Add Inbox**
2. Choose **API** (for testing without real WhatsApp) or **WhatsApp** (for production)
3. Give it a name: `Hermes Bot`
4. Copy the **Inbox ID** shown after creation — you'll need this

### 4.4 Create an Agent Bot

1. Go to **Settings → Integrations → Agent Bots**
2. Click **Add new agent bot**
3. Name: `Hermes`
4. Webhook URL: `https://shy-moles-cut.loca.lt/webhook`
   - This must be your publicly accessible backend URL (see Step 5)
5. Save — copy the **Access Token** shown
6. Update `backend/.env`: set `CHATWOOT_ACCESS_TOKEN=<paste-token-here>`

### 4.5 Connect the Bot to the Inbox

1. Go to **Settings → Inboxes → (your inbox) → Configuration**
2. Scroll to **Agent Bot** section
3. Select `Hermes` from the dropdown
4. Save

---

## Step 5 — Expose the Backend Publicly (Tunnel)

Chatwoot needs to POST webhooks to your Flask backend. Since the backend runs on `localhost:5000`,
you need a public tunnel.

### Option A — localtunnel (already used in .env)

```bash
npx localtunnel --port 5000 --subdomain shy-moles-cut
```

This gives you `https://shy-moles-cut.loca.lt` — which matches `BACKEND_URL` in your `.env`.

If that subdomain is taken:

```bash
npx localtunnel --port 5000
# then update BACKEND_URL and the Chatwoot webhook URL with the new URL
```

### Option B — ngrok

```bash
ngrok http 5000
```

Copy the `https://xxxx.ngrok-free.app` URL and:
1. Update `BACKEND_URL` in `backend/.env`
2. Update the webhook URL in Chatwoot → Agent Bot settings

After updating `.env`, restart the backend:

```bash
docker compose restart backend followup-worker
```

---

## Step 6 — Run the Automated Test Suite

These tests run entirely offline with mocked DB/HTTP — no live services needed.

```bash
cd /home/nithin/Projects/hermes-conversation-agent/backend
.venv/bin/python -m pytest tests/ -v
```

Expected output:

```
tests/test_hermes_agent_property.py::test_run_never_raises_on_success PASSED
tests/test_hermes_agent_property.py::test_search_properties_limit_clamping PASSED
tests/test_hermes_agent_property.py::test_assign_chatwoot_labels_count_cap PASSED
...
tests/test_hermes_agent_unit.py::test_run_success PASSED
...
25 passed in ~6s
```

---

## Step 7 — Run the Smoke Test (against live DB)

This hits the real databases and confirms all tool functions return valid JSON.

```bash
cd /home/nithin/Projects/hermes-conversation-agent/backend
.venv/bin/python scripts/test_tools.py
```

What it tests:
- `search_properties` — no filters, city filter, limit clamping (999 → 10)
- `get_property_details` — real listing ID + missing ID error path
- `create_lead` — upsert a test lead row
- `update_lead_stage` — valid stage + invalid stage (must return error JSON)
- `schedule_followup` — normal delay + extreme delay (9999 → 720h clamped)
- `assign_chatwoot_labels` — may return error if Chatwoot unreachable; that's acceptable

Expected: `All tests PASSED.`

---

## Step 8 — Send a Test Webhook (Manual End-to-End)

Simulate a message arriving from Chatwoot. Replace `account_id` and `conversation_id` with real
values from your Chatwoot instance.

```bash
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "content": "Show me flats in Mumbai under 1 crore",
    "account": {"id": 1},
    "conversation": {"id": "42"}
  }'
```

Expected response:

```json
{"status": "success"}
```

Check backend logs to see the agent reasoning:

```bash
docker compose logs -f backend
```

You should see the Hermes agent calling `search_properties` and returning a formatted reply.

---

## Step 9 — Send a Real WhatsApp Message (Production Test)

1. Open Chatwoot at `http://localhost:3000`
2. Open any conversation coming in on the **Hermes Bot** inbox
3. The reply from the Hermes agent should appear automatically in the conversation

If no reply appears:
- Check `docker compose logs backend` for errors
- Check that the tunnel is running and the webhook URL in Chatwoot is correct
- Check that `CHATWOOT_ACCESS_TOKEN` is the token for the agent bot (not a user token)

---

## Step 10 — Test the Follow-Up Worker

The follow-up worker polls every 5 minutes. To test it immediately:

### Insert a due follow-up row manually

Connect to the state database (remote or local) and run:

```sql
INSERT INTO hermes_followups (conversation_id, account_id, note, scheduled_at, status)
VALUES ('42', 1, 'User asked to follow up tomorrow', NOW() - INTERVAL '1 minute', 'pending');
```

### Trigger one poll cycle immediately

```bash
docker compose exec followup-worker python -c "
import sys
sys.path.insert(0, '.')
from services.chatwoot import ChatwootClient
from workers.followup_worker import run_poll_cycle
count = run_poll_cycle(ChatwootClient())
print(f'Processed {count} follow-up(s)')
"
```

### Verify the row was processed

```sql
SELECT id, status, sent_at FROM hermes_followups WHERE conversation_id = '42';
```

Expected: `status = 'sent'` and `sent_at` is set.

---

## Troubleshooting

### Backend won't start

```bash
docker compose logs backend
```

Common causes:
- `DATABASE_URL` or `STATE_DATABASE_URL` is unreachable (check GCP firewall / VPN)
- `hermes-agent` package failed to install from GitHub — check network during `docker compose build`

### Chatwoot shows no bot reply

1. Check the tunnel is alive: `curl https://shy-moles-cut.loca.lt/webhook` should return `405 Method Not Allowed` (correct — GET is not allowed, but the tunnel is up)
2. Verify the agent bot webhook URL matches your tunnel URL exactly (including `https://`)
3. Check `CHATWOOT_ACCESS_TOKEN` — it must be the bot token, not a user API token

### `hermes_agent` import fails

The `run_agent` package installs from GitHub. If it's missing:

```bash
docker compose exec backend pip install "hermes-agent @ git+https://github.com/NousResearch/hermes-agent.git"
```

Or rebuild the image:

```bash
docker compose build --no-cache backend
docker compose up -d backend followup-worker
```

### Tables not created

```bash
docker compose exec backend python -c "
from services.state_store import StateStore
s = StateStore()
print('OK')
"
```

If this errors with a DB connection issue, check `STATE_DATABASE_URL` is correct and the
GCP instance at `34.93.127.33` is accessible.

---

## Quick Reference — Useful Commands

```bash
# Start everything
docker compose up --build -d

# Stop everything
docker compose down

# View logs (live)
docker compose logs -f backend
docker compose logs -f followup-worker
docker compose logs -f chatwoot

# Restart just the backend after .env changes
docker compose restart backend followup-worker

# Run unit + property tests (offline)
cd backend && .venv/bin/python -m pytest tests/ -v

# Run smoke tests (requires live DB)
cd backend && .venv/bin/python scripts/test_tools.py

# Open a Python shell inside the backend container
docker compose exec backend python
```
