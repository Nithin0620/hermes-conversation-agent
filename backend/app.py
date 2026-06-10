import os
import atexit
from dotenv import load_dotenv

load_dotenv()

from flask import Flask
from routes.webhook import webhook_bp
from services.database import DatabaseService
from services.state_store import StateStore

app = Flask(__name__)
app.register_blueprint(webhook_bp)

db = DatabaseService()
state_store = StateStore()
atexit.register(db.close)
atexit.register(state_store.close)

if __name__ == "__main__":
    port = int(os.getenv("HERMES_PORT", 5000))
    app.run(host="0.0.0.0", port=port)
