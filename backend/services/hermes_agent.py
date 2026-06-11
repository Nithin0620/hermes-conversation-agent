import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from run_agent import AIAgent
from debug_trace import BUILD_MARKER, dbg
from services.state_store import StateStore
from services.rate_limiter import get_bucket
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
        model: str = "llama-3.3-70b-versatile",
        api_key: str | None = None,
        base_url: str | None = None,
        max_iterations: int = 2,
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

    def _tool_registry_snapshot(self) -> dict:
        snapshot = {
            "real_estate_property_tools_loaded": "real_estate_tools.property_tools" in sys.modules,
            "real_estate_crm_tools_loaded": "real_estate_tools.crm_tools" in sys.modules,
            "registered_tool_names": [],
            "real_estate_tool_count": 0,
        }
        try:
            from tools.registry import registry  # noqa: PLC0415

            names = sorted(getattr(registry, "_tools", {}).keys())
            snapshot["registered_tool_names"] = names
            snapshot["real_estate_tool_count"] = sum(
                1 for name in names if name.startswith("search_") or name.startswith("get_") or name in {
                    "create_lead", "update_lead_stage", "assign_chatwoot_labels", "schedule_followup"
                }
            )
        except Exception as exc:
            snapshot["registry_error"] = type(exc).__name__
        return snapshot

    def run(
        self,
        conversation_id: str,
        user_message: str,
        account_id: int,
    ) -> str:
        started = time.monotonic()
        try:
            history_rows = self._store.get_history(conversation_id, limit=6)
            hermes_history = self._history_to_hermes(history_rows)

            summary = (self._store.load_state(conversation_id) or {}).get("summary", "")
            augmented_message = (
                f"[context: account_id={account_id}, conversation_id={conversation_id}]\n"
                + (f"Conversation Summary:\n{summary}\n\n" if summary else "")
                + f"Current User Message:\n{user_message}"
            )

            # #region agent log
            dbg(
                "hermes_agent.py:run:pre_agent",
                "Starting HermesAgentService.run",
                {
                    "build_marker": BUILD_MARKER,
                    "conversation_id": conversation_id,
                    "account_id": account_id,
                    "user_message_len": len(user_message),
                    "history_len": len(hermes_history),
                    "history_roles": [h.get("role") for h in hermes_history[:5]],
                    "model": self._model,
                    "base_url": self._base_url,
                    "skip_memory": False,
                    "session_db_is_none": self._session_db is None,
                    "tool_registry": self._tool_registry_snapshot(),
                },
                hypothesis_id="H3,H4,H5",
            )
            # #endregion

            agent = self._make_agent()

            result = agent.run_conversation(
                user_message=augmented_message,
                conversation_history=hermes_history,
                task_id=conversation_id,
            )

            elapsed_ms = int((time.monotonic() - started) * 1000)
            final_response = result.get("final_response")
            reply = final_response or "I'm here to help. What are you looking for?"

            # #region agent log
            dbg(
                "hermes_agent.py:run:post_agent",
                "Agent run_conversation completed",
                {
                    "elapsed_ms": elapsed_ms,
                    "final_response_present": bool(final_response),
                    "final_response_len": len(final_response) if isinstance(final_response, str) else 0,
                    "reply_used_fallback": not bool(final_response),
                    "api_calls": result.get("api_calls"),
                    "failed": result.get("failed"),
                    "completed": result.get("completed"),
                    "turn_exit_reason": result.get("turn_exit_reason"),
                    "model": result.get("model"),
                    "total_tokens": result.get("total_tokens"),
                },
                hypothesis_id="H2,H3",
            )
            # #endregion

            self._store.add_message(conversation_id, "user", user_message)
            self._store.add_message(conversation_id, "assistant", reply)
            self._update_summary(conversation_id, user_message, reply)
            return reply

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            # #region agent log
            dbg(
                "hermes_agent.py:run:exception",
                "HermesAgentService.run raised",
                {
                    "elapsed_ms": elapsed_ms,
                    "exc_type": type(exc).__name__,
                    "exc_msg": str(exc)[:300],
                },
                hypothesis_id="H2,H3",
            )
            # #endregion
            import traceback
            print(f"[HermesAgent] run() FAILED for conv={conversation_id}: {exc}", flush=True)
            traceback.print_exc()
            logger.exception("[HermesAgent] run() failed for conv=%s: %s", conversation_id, exc)
            return "Sorry, I encountered an error. Please try again."

    # ------------------------------------------------------------------
    # Conversation summary — keeps prompts stable: stores extracted facts
    # so we never send more than 6 raw messages per turn.
    # ------------------------------------------------------------------

    _SUMMARY_CITIES = [
        "mumbai", "delhi", "bangalore", "pune", "hyderabad", "chennai",
        "kolkata", "ahmedabad", "jaipur", "lucknow", "surat", "noida",
        "gurgaon", "indore", "bhopal", "chandigarh", "nagpur",
    ]
    _SUMMARY_PROPERTIES = ["flat", "apartment", "house", "villa", "plot", "shop", "office", "land"]
    _SUMMARY_CATEGORIES = ["residential", "commercial", "land"]

    def _update_summary(self, conversation_id: str, user_message: str, reply: str) -> None:
        state = self._store.load_state(conversation_id) or {}
        old = state.get("summary", "")
        lower = user_message.lower()
        facts = []

        for city in self._SUMMARY_CITIES:
            if city in lower:
                facts.append(f"interested in {city}")

        for pt in self._SUMMARY_PROPERTIES:
            if pt in lower:
                facts.append(f"looking for {pt}")

        for cat in self._SUMMARY_CATEGORIES:
            if cat in lower:
                facts.append(f"category: {cat}")

        m = re.search(r'(?:budget|rs\.?|inr|₹)\s*(\d[\d,]*\s*(?:lakh|crore|k|thousand|million)?)', lower)
        if m:
            facts.append(f"budget: {m.group(0)}")

        if re.search(r'\b(buy|purchase|interested|intend)\b', lower):
            facts.append("buying intent shown")

        if facts:
            new_line = "; ".join(facts) + "."
            summary = f"{old}\n{new_line}" if old else new_line
            if len(summary) > 600:
                summary = summary[-600:]
            state["summary"] = summary
            self._store.save_state(conversation_id, state)

    def run_label_update(
        self,
        conversation_id: str,
        account_id: int,
    ) -> None:
        try:
            history_rows = self._store.get_history(conversation_id, limit=6)
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


# ---------------------------------------------------------------------------
# httpx monkey-patch: rate-limit every LLM API call at the HTTP transport layer.
# The Hermes agent makes multiple internal calls per turn (tool-calling loop).
# Patching httpx.Client.send catches ALL of them, not just the entry point.
# ---------------------------------------------------------------------------

def _is_chat_completions(request: object) -> bool:
    try:
        url = str(request.url) if hasattr(request, "url") else ""
        return "/chat/completions" in url
    except Exception:
        return False


def _estimate_from_request(request: object) -> int:
    try:
        body = json.loads(request.content)
        messages = body.get("messages", [])
        char_count = sum(
            len(str(m.get("content", ""))) if isinstance(m.get("content"), str) else 0
            for m in messages
        )
        est = char_count // 4
        est += body.get("max_tokens", 500) or 500
        return max(est, 500)
    except Exception:
        return 3000


def _record_from_response(response: object) -> None:
    try:
        content_type = (response.headers.get("content-type", "") or "")
        if content_type.startswith("text/event-stream"):
            return
        body = json.loads(response.read())
        usage = body.get("usage", {}) or {}
        total = (usage.get("prompt_tokens", 0) or 0) + (usage.get("completion_tokens", 0) or 0)
        if total:
            get_bucket().record(total)
    except Exception:
        pass


def _patch_httpx_rate_limiting() -> None:
    import httpx as _httpx
    import functools as _functools

    _original_send = _httpx.Client.send

    @_functools.wraps(_original_send)
    def _rate_limited_send(self, request, *args, **kwargs):
        is_llm = _is_chat_completions(request)
        if is_llm:
            est = _estimate_from_request(request)
            get_bucket().wait(estimated=est)

        response = _original_send(self, request, *args, **kwargs)

        if is_llm and not kwargs.get("stream", False):
            _record_from_response(response)

        return response

    _httpx.Client.send = _rate_limited_send
    logger.info("[RateLimit] httpx.Client.send patched — per-call LLM rate limiting active")


_patch_httpx_rate_limiting()
