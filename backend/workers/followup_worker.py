"""
Follow-up Worker — polls hermes_followups and sends due re-engagement messages.

Run from the backend/ directory:
    python workers/followup_worker.py

The worker:
- Polls every 5 minutes for rows where status='pending' AND scheduled_at <= NOW()
- For each due row: calls HermesAgentService.run() to generate a re-engagement message
- Sends the reply via ChatwootClient.send_message()
- Marks the row as sent (status='sent', sent_at=NOW())
- Handles per-row failures gracefully: logs the error and moves on
- Shuts down cleanly on SIGTERM or SIGINT
"""

import logging
import os
import signal
import sys
import time

# ---------------------------------------------------------------------------
# Logging setup — configure before any other imports so that logger
# instances created at import time pick up the right level / format.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("followup_worker")

# Ensure the backend/ directory is on sys.path when this script is run
# directly as: python workers/followup_worker.py from backend/
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from services.state_store import _get_shared_store  # noqa: E402
from services.chatwoot import ChatwootClient  # noqa: E402
from services.hermes_agent import HermesAgentService  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
POLL_INTERVAL_SECONDS = 300  # 5 minutes

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_stop_flag = False


def _handle_signal(signum: int, frame) -> None:  # type: ignore[type-arg]
    global _stop_flag
    sig_name = signal.Signals(signum).name
    logger.info("Received %s — shutting down after current poll cycle.", sig_name)
    _stop_flag = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def _process_row(row: dict, chatwoot: ChatwootClient) -> None:
    """Process a single due follow-up row.

    Steps:
    1. Build a re-engagement prompt from the follow-up note.
    2. Instantiate HermesAgentService and call run() to generate a reply.
    3. Send the reply via ChatwootClient.
    4. Mark the row as sent in the database.

    Raises:
        Any exception — callers should wrap in try/except and log.
    """
    followup_id = row["id"]
    conversation_id = str(row["conversation_id"])
    account_id = int(row["account_id"])
    note = row.get("note") or ""

    logger.info(
        "Processing follow-up id=%s conv=%s account=%s",
        followup_id, conversation_id, account_id,
    )

    # Build a context message that gives the agent enough information to
    # compose a warm re-engagement message without requiring a live user turn.
    if note:
        user_message = (
            f"[Follow-up context] The user previously requested a follow-up. "
            f"Note: {note}. "
            "Please send a warm, personalised re-engagement message to the user."
        )
    else:
        user_message = (
            "[Follow-up context] The user previously requested a follow-up. "
            "Please send a warm re-engagement message asking if they are still "
            "looking for properties and how you can help."
        )

    store = _get_shared_store()

    api_key = os.getenv("GROQ_API_KEY")
    base_url = "https://api.groq.com/openai/v1"

    agent_service = HermesAgentService(
        state_store=store,
        api_key=api_key,
        base_url=base_url,
    )

    reply = agent_service.run(
        conversation_id=conversation_id,
        user_message=user_message,
        account_id=account_id,
    )

    chatwoot.send_message(account_id, conversation_id, reply)
    logger.info("Reply sent for follow-up id=%s", followup_id)

    store.mark_followup_sent(followup_id)
    logger.info("Follow-up id=%s marked as sent.", followup_id)


def run_poll_cycle(chatwoot: ChatwootClient) -> int:
    """Execute one poll cycle.

    Returns the number of rows processed (regardless of success/failure).
    """
    store = _get_shared_store()
    due_rows = store.get_due_followups()

    if not due_rows:
        logger.debug("No due follow-ups found.")
        return 0

    logger.info("Found %d due follow-up(s).", len(due_rows))

    for row in due_rows:
        try:
            _process_row(row, chatwoot)
        except Exception:
            logger.exception(
                "Failed to process follow-up id=%s — skipping.", row.get("id")
            )

    return len(due_rows)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Follow-up worker starting. Poll interval: %ds.", POLL_INTERVAL_SECONDS)

    chatwoot = ChatwootClient()

    while not _stop_flag:
        try:
            run_poll_cycle(chatwoot)
        except Exception:
            logger.exception("Unexpected error during poll cycle — will retry next interval.")

        # Sleep in small increments so SIGTERM/SIGINT wakes us quickly.
        elapsed = 0
        while elapsed < POLL_INTERVAL_SECONDS and not _stop_flag:
            time.sleep(1)
            elapsed += 1

    logger.info("Follow-up worker stopped.")


if __name__ == "__main__":
    main()
