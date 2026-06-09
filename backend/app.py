import os
from flask import Flask
from dotenv import load_dotenv
from routes.webhook import webhook_bp

load_dotenv()

app = Flask(__name__)
app.register_blueprint(webhook_bp)

if __name__ == "__main__":
    port = int(os.getenv("HERMES_PORT", 5000))
    app.run(host="0.0.0.0", port=port)
