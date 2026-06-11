"""NDJSON debug logging for Cursor debug session af21db."""
import json
import sys
import time
from pathlib import Path

_backend_root = Path(__file__).resolve().parent
LOG_PATH = _backend_root / ".cursor" / "debug-af21db.log"
BUILD_MARKER = "debug-af21db-v5"


def dbg(
    location: str,
    message: str,
    data: dict | None = None,
    hypothesis_id: str = "",
    run_id: str = "pre-fix",
) -> None:
    # #region agent log
    payload = {
        "sessionId": "af21db",
        "id": f"log_{int(time.time() * 1000)}_{hypothesis_id or 'x'}",
        "timestamp": int(time.time() * 1000),
        "location": location,
        "message": message,
        "data": data or {},
        "runId": run_id,
        "hypothesisId": hypothesis_id,
    }
    line = json.dumps(payload, default=str) + "\n"
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    print(f"[DBG af21db] {message} {payload.get('data')}", file=sys.stderr, flush=True)
    # #endregion
