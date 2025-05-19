from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from flask import Flask
from threading import Thread
import os
import re
import asyncio

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")
DELETE_DELAY = int(os.getenv("DELETE_DELAY", 60))  # default: 60s

START_PIC = "https://i.ibb.co/prnGXMr3/photo-2025-05-16-05-15-45-7504908428624527364.jpg"

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

movie_cache = []

flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "Bot is Running"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

def clean(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

def detect_language(text):
    if re.search(r'[\u0980-\u09FF]', text):  # Bengali Unicode range
        return "bn"
    return "en"

@app.on_message(filters.chat(CHANNEL_ID))
async def cache_movie(_, msg: Message):
    title = msg.caption or msg.text
    if not title:
        return
    movie_cache.append({
        "title": title,
        "clean": clean(title),
        "message_id": msg.id,
        "lang": detect_language(title)
    })

@app.on_message(filters.command("start"))
async def start(_, msg: Message):
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("Update Channel", url=UPDATE_CHANNEL)],
        [InlineKeyboardButton("Contact Admin", url="https://t.me/ctgmovies23")]
    ])
    movie_cache.append({"chat_id": msg.chat.id})  # Track user
    if START_PIC:
        await msg.reply_photo(photo=START_PIC, caption="Send me a movie name to search.", reply_markup=btn)
    else:
        await msg.reply("Send me a movie name to search.", reply_markup=btn)

@app.on_message(filters.text & filters.private)
async def search(_, msg: Message):
    query = clean(msg.text.strip())
    lang = detect_language(msg.text)
    loading = await msg.reply("🔎 Searching, please wait...")
    movie_cache.append({"chat_id": msg.chat.id})  # Track user

    matched = [m for m in movie_cache if query in m.get("clean", "") and m.get("lang") == lang]
    if not matched:
        await asyncio.sleep(DELETE_DELAY)
        await msg.delete()
        await loading.delete()
        return

    buttons = [
        [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")]
        for m in matched[:RESULTS_COUNT]
    ]
    result = await loading.edit("Found results. Select one:", reply_markup=InlineKeyboardMarkup(buttons))

    await asyncio.sleep(DELETE_DELAY)
    await msg.delete()
    await result.delete()

@app.on_callback_query()
async def cb_handler(_, cq: CallbackQuery):
    if cq.data.startswith("movie_"):
        mid = int(cq.data.split("_")[1])
        try:
            sent = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
            await cq.answer("Movie sent.")
            await asyncio.sleep(DELETE_DELAY)
            await sent.delete()
        except:
            await cq.answer("Failed to forward. Might be deleted.", show_alert=True)

@app.on_message(filters.command("stats") & filters.private)
async def stats(_, msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return await msg.reply("❌ You are not authorized.")
    total_movies = len([m for m in movie_cache if "title" in m])
    total_users = len(set(m["chat_id"] for m in movie_cache if "chat_id" in m))
    await msg.reply(f"📊 Stats:\n• Total Movies: {total_movies}\n• Unique Users: {total_users}")

@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast(_, msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return await msg.reply("❌ You are not authorized.")
    if not msg.reply_to_message:
        return await msg.reply("Reply to a message to broadcast it.")

    success = 0
    fail = 0
    for user_id in set(u["chat_id"] for u in movie_cache if "chat_id" in u):
        try:
            await msg.reply_to_message.copy(chat_id=user_id)
            success += 1
        except:
            fail += 1
    await msg.reply(f"✅ Broadcast complete.\nSuccess: {success}, Failed: {fail}")

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
