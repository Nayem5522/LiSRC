# main.py
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from flask import Flask
from threading import Thread
import os
import re
import asyncio
import urllib.parse
from datetime import datetime

# Configs
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")
START_PIC = os.getenv("START_PIC", "https://i.ibb.co/prnGXMr3/photo-2025-05-16-05-15-45-7504908428624527364.jpg")

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Flask for Render/Koyeb
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Bot is running!"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

# Utils
def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

@app.on_message(filters.command("start"))
async def start(_, msg: Message):
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("Update Channel", url=UPDATE_CHANNEL)],
        [InlineKeyboardButton("Contact Admin", url="https://t.me/ctgmovies23")]
    ])
    await msg.reply_photo(photo=START_PIC, caption="Send me a movie name to search.", reply_markup=btns)

@app.on_message(filters.text & filters.private)
async def search(_, msg: Message):
    query = clean_text(msg.text.strip())
    loading = await msg.reply("🔎 Searching, please wait...")

    messages = await app.get_chat_history(CHANNEL_ID, limit=300)
    results = []
    for m in messages:
        title = m.caption or m.text or ""
        if re.search(re.escape(msg.text), title, re.IGNORECASE):
            results.append(m)
            if len(results) >= RESULTS_COUNT:
                break

    await loading.delete()
    if results:
        for m in results:
            fwd = await app.forward_messages(msg.chat.id, CHANNEL_ID, m.id)
            asyncio.create_task(delete_later(msg.chat.id, fwd.id))
    else:
        google_url = "https://www.google.com/search?q=" + urllib.parse.quote(msg.text)
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("Search on Google", url=google_url)]
        ])
        m = await msg.reply("No results found. Try Google search.", reply_markup=buttons)
        asyncio.create_task(delete_later(m.chat.id, m.id))

async def delete_later(chat_id, msg_id, delay=600):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, msg_id)
    except:
        pass

if __name__ == "__main__":
    print("Bot is starting...")
    app.run()
