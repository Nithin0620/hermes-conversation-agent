import os
import json
import logging
import psycopg2
import psycopg2.extras
from uuid import UUID

logger = logging.getLogger(__name__)

# Module-level singleton
_shared_store: "StateStore | None" = None


def _get_shared_store() -> "StateStore":
    """Return the module-level singleton StateStore, creating it on first call."""
    global _shared_store
    if _shared_store is None:
        _shared_store = StateStore()
    return _shared_store


class StateStore:
    def __init__(self):
        self.dsn = os.getenv("STATE_DATABASE_URL")
        self._conn = None
        self._ensure_tables()

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.dsn)
            self._conn.autocommit = True
        return self._conn

    def _ensure_tables(self):
        """Create all required tables and indexes in a single transaction.

        All DDL statements run inside one explicit transaction so that any
        failure causes a full rollback, leaving the database in a clean state.
        """
        conn = self._get_conn()
        # Disable autocommit so we can wrap everything in a single transaction.
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS hermes_conversations (
                        conversation_id TEXT PRIMARY KEY,
                        state JSONB NOT NULL DEFAULT '{}',
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS hermes_messages (
                        id SERIAL PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_messages_conv
                    ON hermes_messages (conversation_id, created_at)
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS hermes_leads (
                        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        conversation_id TEXT NOT NULL UNIQUE,
                        account_id      INTEGER NOT NULL,
                        name            TEXT,
                        phone           TEXT,
                        city            TEXT,
                        budget          TEXT,
                        intent          TEXT,
                        stage           TEXT NOT NULL DEFAULT 'new_lead',
                        notes           TEXT,
                        created_at      TIMESTAMPTZ DEFAULT NOW(),
                        updated_at      TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS hermes_followups (
                        id              SERIAL PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        account_id      INTEGER NOT NULL,
                        note            TEXT,
                        scheduled_at    TIMESTAMPTZ NOT NULL,
                        sent_at         TIMESTAMPTZ,
                        status          TEXT NOT NULL DEFAULT 'pending'
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_followups_scheduled
                    ON hermes_followups (scheduled_at) WHERE status = 'pending'
                """)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            # Restore autocommit for normal DML operations.
            conn.autocommit = True

    def load_state(self, conversation_id):
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT state FROM hermes_conversations WHERE conversation_id = %s",
                (conversation_id,)
            )
            row = cur.fetchone()
            if row:
                return row["state"]
            return None

    def save_state(self, conversation_id, state):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO hermes_conversations (conversation_id, state, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (conversation_id)
                DO UPDATE SET state = %s::jsonb, updated_at = NOW()
            """, (conversation_id, json.dumps(state), json.dumps(state)))

    def add_message(self, conversation_id, role, content):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO hermes_messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conversation_id, role, content)
            )

    def get_history(self, conversation_id, limit=50):
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT role, content, created_at FROM hermes_messages
                WHERE conversation_id = %s
                ORDER BY created_at ASC
                LIMIT %s
            """, (conversation_id, limit))
            return [{"role": r["role"], "content": r["content"]} for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # hermes_leads helpers
    # ------------------------------------------------------------------

    def upsert_lead(
        self,
        conversation_id: str,
        account_id: int,
        name: str | None = None,
        phone: str | None = None,
        intent: str | None = None,
        city: str | None = None,
        budget: str | None = None,
    ) -> UUID:
        """Insert or update a lead row, refreshing updated_at on conflict.

        Returns the UUID primary key of the upserted row.
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hermes_leads
                    (conversation_id, account_id, name, phone, intent, city, budget)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (conversation_id) DO UPDATE SET
                    account_id  = EXCLUDED.account_id,
                    name        = COALESCE(EXCLUDED.name,   hermes_leads.name),
                    phone       = COALESCE(EXCLUDED.phone,  hermes_leads.phone),
                    intent      = COALESCE(EXCLUDED.intent, hermes_leads.intent),
                    city        = COALESCE(EXCLUDED.city,   hermes_leads.city),
                    budget      = COALESCE(EXCLUDED.budget, hermes_leads.budget),
                    updated_at  = NOW()
                RETURNING id
                """,
                (conversation_id, account_id, name, phone, intent, city, budget),
            )
            row = cur.fetchone()
            return row[0]

    def update_lead_stage(
        self,
        conversation_id: str,
        stage: str,
        notes: str | None = None,
    ) -> None:
        """Update the stage (and optionally notes) of an existing lead."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE hermes_leads
                SET stage      = %s,
                    notes      = COALESCE(%s, notes),
                    updated_at = NOW()
                WHERE conversation_id = %s
                """,
                (stage, notes, conversation_id),
            )

    # ------------------------------------------------------------------
    # hermes_followups helpers
    # ------------------------------------------------------------------

    def insert_followup(
        self,
        conversation_id: str,
        account_id: int,
        note: str | None,
        scheduled_at: str,
    ) -> int:
        """Insert a scheduled follow-up row and return its serial id.

        Args:
            scheduled_at: ISO 8601 timestamp string (e.g. from datetime.isoformat()).
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hermes_followups
                    (conversation_id, account_id, note, scheduled_at)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (conversation_id, account_id, note, scheduled_at),
            )
            row = cur.fetchone()
            return row[0]

    def get_due_followups(self) -> list[dict]:
        """Return all pending follow-ups whose scheduled_at is at or before NOW()."""
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, conversation_id, account_id, note, scheduled_at, status
                FROM hermes_followups
                WHERE status = 'pending'
                  AND scheduled_at <= NOW()
                ORDER BY scheduled_at ASC
                """
            )
            return [dict(row) for row in cur.fetchall()]

    def mark_followup_sent(self, followup_id: int) -> None:
        """Mark a follow-up row as sent and record the sent timestamp."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE hermes_followups
                SET status = 'sent',
                    sent_at = NOW()
                WHERE id = %s
                """,
                (followup_id,),
            )

    # ------------------------------------------------------------------

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
