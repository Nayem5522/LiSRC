from flask import Flask
from threading import Thread
from bot import app

server = Flask(__name__)

@server.route('/')
def home():
    return "Bot is running!"

def run():
    server.run(host="0.0.0.0", port=8080)

def start_bot():
    app.run()

if __name__ == "__main__":
    Thread(target=run).start()
    start_bot()
