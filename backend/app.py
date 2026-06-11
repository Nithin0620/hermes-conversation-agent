import os
import logging
import atexit
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Register Hermes real-estate tools at startup (registry.register runs on import).
import real_estate_tools.crm_tools  # noqa: F401,E402
import real_estate_tools.followup_tools  # noqa: F401,E402
import real_estate_tools.property_tools  # noqa: F401,E402

from flask import Flask
from debug_trace import BUILD_MARKER, dbg
from routes.webhook import webhook_bp
from services.database import DatabaseService
from services.state_store import StateStore

# #region agent log
dbg(
    "app.py:startup",
    "Flask app importing webhook blueprint",
    {
        "build_marker": BUILD_MARKER,
        "hermes_model": os.getenv("HERMES_MODEL"),
        "hermes_base_url": os.getenv("HERMES_BASE_URL"),
        "groq_key_set": bool(os.getenv("GROQ_API_KEY")),
    },
    hypothesis_id="H1",
)
# #endregion

app = Flask(__name__)
app.register_blueprint(webhook_bp)

db = DatabaseService()
state_store = StateStore()
atexit.register(db.close)
atexit.register(state_store.close)

if __name__ == "__main__":
    port = int(os.getenv("HERMES_PORT", 5000))
    app.run(host="0.0.0.0", port=port)
