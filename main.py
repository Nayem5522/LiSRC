from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from flask import Flask
from threading import Thread
import os
import re
import asyncio
from datetime import datetime

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/yourchannel")
START_PIC = os.getenv("START_PIC")

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

movie_cache = []

# Web server for Render/Koyeb
flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "Bot is Running"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

def clean(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

@app.on_message(filters.chat(CHANNEL_ID))
async def cache_movie(_, msg: Message):
    title = msg.caption or msg.text
    if not title:
        return
    movie_cache.append({
        "title": title,
        "clean": clean(title),
        "message_id": msg.id
    })

@app.on_message(filters.command("start"))
async def start(_, msg: Message):
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("Update Channel", url=UPDATE_CHANNEL)],
        [InlineKeyboardButton("Contact Admin", url="https://t.me/ctgmovies23")]
    ])
    await msg.reply_photo(photo=START_PIC, caption="Send me a movie name to search.", reply_markup=btn)

@app.on_message(filters.text & filters.private)
async def search(_, msg: Message):
    query = clean(msg.text.strip())
    loading = await msg.reply("🔎 Searching, please wait...")

    matched = [m for m in movie_cache if query in m["clean"]]
    if not matched:
        await loading.edit("❌ No results found. Try a different name.")
        return

    buttons = [
        [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")]
        for m in matched[:RESULTS_COUNT]
    ]
    await loading.edit("Found results. Select one:", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query()
async def cb_handler(_, cq: CallbackQuery):
    if cq.data.startswith("movie_"):
        mid = int(cq.data.split("_")[1])
        try:
            fwd = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
            await cq.answer("Movie sent.")
        except:
            await cq.answer("Failed to forward. Might be deleted.", show_alert=True)

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
