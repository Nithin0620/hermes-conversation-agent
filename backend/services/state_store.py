import os
import json
import psycopg2
import psycopg2.extras


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
        conn = self._get_conn()
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

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
