import asyncio
import threading
from flask import Flask
from bot import app as bot_app

flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)

def run_bot():
    bot_app.run()

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    run_bot()
