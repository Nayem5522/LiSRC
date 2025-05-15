import asyncio
from start_web import start_web
from bot import app

import threading

def run():
    # ওয়েব সার্ভার রান করাও
    threading.Thread(target=start_web, daemon=True).start()

    # বট রান করাও
    app.run()

if __name__ == "__main__":
    run()
