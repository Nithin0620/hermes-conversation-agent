import logging
import os
from pathlib import Path
from run_agent import AIAgent
from services.state_store import StateStore
from config.system_prompt import REAL_ESTATE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def _build_session_db(memory_db_path: str | Path | None) -> object | None:
    """
    Create a Hermes SessionDB instance for the given SQLite path.

    Hermes uses SQLite for its internal memory/session store (hermes_state.SessionDB).
    The path defaults to a 'hermes_state.db' file alongside the STATE_DATABASE_URL
    postgres host, or to a local fallback when no env var is set.

    Returns a SessionDB instance, or None if hermes_state is unavailable.
    """
    try:
        from hermes_state import SessionDB

        if memory_db_path is None:
            # Use a project-local SQLite file for Hermes memory so it is
            # co-located with the application and not mixed with the user's
            # personal ~/.hermes/state.db.
            memory_db_path = Path(__file__).parent.parent / "hermes_memory.db"

        db_path = Path(memory_db_path) if not isinstance(memory_db_path, Path) else memory_db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return SessionDB(db_path=db_path)
    except Exception as exc:
        logger.warning(
            "[HermesAgent] Could not initialise SessionDB (memory disabled): %s", exc
        )
        return None


class HermesAgentService:
    def __init__(
        self,
        state_store: StateStore,
        model: str = "groq/llama-3.3-70b-versatile",
        api_key: str | None = None,
        base_url: str | None = None,
        max_iterations: int = 10,
        memory_db_path: str | Path | None = None,
    ) -> None:
        self._store = state_store
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._max_iterations = max_iterations
        # Hermes memory backend uses SQLite (hermes_state.SessionDB).
        # memory_db_path controls where the SQLite file is stored.
        # Defaults to hermes_memory.db in the backend directory.
        self._memory_db_path = memory_db_path or os.getenv(
            "HERMES_MEMORY_DB_PATH"
        )
        # Eagerly build a shared SessionDB; reused across _make_agent() calls
        # so all per-request AIAgent instances share the same memory store.
        self._session_db = _build_session_db(self._memory_db_path)

    def _history_to_hermes(self, rows: list[dict]) -> list[dict]:
        """Convert StateStore rows [{role, content}] to Hermes message format."""
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def _make_agent(self) -> AIAgent:
        return AIAgent(
            model=self._model,
            api_key=self._api_key,
            base_url=self._base_url,
            quiet_mode=True,
            skip_context_files=True,
            # Phase 4: enable Hermes persistent memory.
            # session_db provides the SQLite-backed SessionDB that Hermes uses
            # to persist and recall conversation memory across turns.
            skip_memory=False,
            session_db=self._session_db,
            ephemeral_system_prompt=REAL_ESTATE_SYSTEM_PROMPT,
            enabled_toolsets=["real_estate"],
            max_iterations=self._max_iterations,
            platform="whatsapp",
        )

    def run(
        self,
        conversation_id: str,
        user_message: str,
        account_id: int,
    ) -> str:
        try:
            history_rows = self._store.get_history(conversation_id, limit=20)
            hermes_history = self._history_to_hermes(history_rows)

            augmented_message = (
                f"[context: account_id={account_id}, conversation_id={conversation_id}]\n"
                f"{user_message}"
            )

            agent = self._make_agent()
            result = agent.run_conversation(
                user_message=augmented_message,
                conversation_history=hermes_history,
                task_id=conversation_id,
            )
            reply = result.get("final_response") or "I'm here to help. What are you looking for?"

            self._store.add_message(conversation_id, "user", user_message)
            self._store.add_message(conversation_id, "assistant", reply)
            return reply

        except Exception as exc:
            logger.exception("[HermesAgent] run() failed for conv=%s: %s", conversation_id, exc)
            return "Sorry, I encountered an error. Please try again."

    def run_label_update(
        self,
        conversation_id: str,
        account_id: int,
    ) -> None:
        try:
            history_rows = self._store.get_history(conversation_id, limit=20)
            hermes_history = self._history_to_hermes(history_rows)
            agent = self._make_agent()
            agent.run_conversation(
                user_message=(
                    f"[context: account_id={account_id}, conversation_id={conversation_id}]\n"
                    "Based on this conversation, call assign_chatwoot_labels with the most "
                    "appropriate CRM labels. Max 6 labels. Do not reply with text, only call the tool."
                ),
                conversation_history=hermes_history,
                task_id=f"{conversation_id}-labels",
            )
        except Exception as exc:
            logger.warning("[HermesAgent] run_label_update() failed for conv=%s: %s", conversation_id, exc)
