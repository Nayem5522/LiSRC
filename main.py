import json
import os
import re
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from flask import Flask
from threading import Thread

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))  # চ্যানেল আইডি -100... ফরম্যাটে দিতে হবে
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")
DELETE_DELAY = int(os.getenv("DELETE_DELAY", 60))
START_PIC = "https://i.ibb.co/prnGXMr3/photo-2025-05-16-05-15-45-7504908428624527364.jpg"

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

MOVIE_DB = "movies.json"
USER_DB = "users.json"

def load_data(file):
    return json.load(open(file)) if os.path.exists(file) else []

def save_data(file, data):
    json.dump(data, open(file, "w"))

movie_cache = load_data(MOVIE_DB)
user_cache = set(load_data(USER_DB))

flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "Bot is Running"

Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

def clean(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

def detect_language(text):
    return "bn" if re.search(r'[\u0980-\u09FF]', text) else "en"

async def is_user_joined(user_id):
    try:
        member = await app.get_chat_member(chat_id=UPDATE_CHANNEL.split("/")[-1], user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False

# চ্যানেল থেকে মুভি ক্যাশিং
@app.on_message(filters.chat(CHANNEL_ID))
async def cache_movie(_, msg: Message):
    title = msg.caption or msg.text
    if not title:
        return
    movie_cache.append({
        "title": title,
        "clean": clean(title),
        "message_id": msg.message_id,
        "lang": detect_language(title)
    })
    save_data(MOVIE_DB, movie_cache)

# স্টার্ট কমান্ড
@app.on_message(filters.command("start") & filters.private)
async def start(_, msg: Message):
    if not await is_user_joined(msg.from_user.id):
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join Update Channel", url=UPDATE_CHANNEL)],
            [InlineKeyboardButton("Try Again", callback_data="refresh")]
        ])
        return await msg.reply("Please join our update channel first.", reply_markup=btn)

    user_cache.add(msg.chat.id)
    save_data(USER_DB, list(user_cache))

    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("Update Channel", url=UPDATE_CHANNEL)],
        [InlineKeyboardButton("Contact Admin", url="https://t.me/ctgmovies23")]
    ])
    if START_PIC:
        await msg.reply_photo(START_PIC, "Send me a movie name to search.", reply_markup=btn)
    else:
        await msg.reply("Send me a movie name to search.", reply_markup=btn)

# রিফ্রেশ কলব্যাক
@app.on_callback_query(filters.regex("refresh"))
async def refresh(_, cq: CallbackQuery):
    if await is_user_joined(cq.from_user.id):
        await cq.message.delete()
        await start(_, cq.message)
    else:
        await cq.answer("You must join the update channel!", show_alert=True)

# সার্চ মুভি
@app.on_message(filters.text & filters.private)
async def search(_, msg: Message):
    query = clean(msg.text.strip())
    lang = detect_language(msg.text)
    loading = await msg.reply("🔎 Searching, please wait...")
    user_cache.add(msg.chat.id)
    save_data(USER_DB, list(user_cache))

    matched = [m for m in movie_cache if query in m.get("clean", "") and m.get("lang") == lang]

    if not matched:
        await asyncio.sleep(DELETE_DELAY)
        await msg.delete()
        await loading.edit("❌ Movie not found. Admin has been notified. Please wait for an update.")
        # এখানে চাইলে এডমিন নোটিফাই করানো যাবে (বর্ধিত করা যাবে)
        return

    buttons = [[InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")] for m in matched[:RESULTS_COUNT]]
    result = await loading.edit("Found results. Select one:", reply_markup=InlineKeyboardMarkup(buttons))
    await asyncio.sleep(DELETE_DELAY)
    await msg.delete()
    await result.delete()

# মুভি ফরোয়ার্ড কলব্যাক
@app.on_callback_query()
async def cb_handler(_, cq: CallbackQuery):
    if cq.data.startswith("movie_"):
        mid = int(cq.data.split("_")[1])
        try:
            sent = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
            await cq.answer("Movie sent.")
            await asyncio.sleep(DELETE_DELAY)
            await sent.delete()
        except Exception:
            await cq.answer("Failed to forward. Might be deleted.", show_alert=True)

# স্ট্যাটস কমান্ড
@app.on_message(filters.command("stats") & filters.private)
async def stats(_, msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return await msg.reply("❌ You are not authorized.")
    await msg.reply(f"📊 Stats:\n• Total Movies: {len(movie_cache)}\n• Unique Users: {len(user_cache)}")

# ব্রডকাস্ট কমান্ড
@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast(_, msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return await msg.reply("❌ You are not authorized.")
    if not msg.reply_to_message:
        return await msg.reply("Reply to a message to broadcast it.")
    success = fail = 0
    for user_id in user_cache:
        try:
            await msg.reply_to_message.copy(chat_id=user_id)
            success += 1
        except:
            fail += 1
    await msg.reply(f"✅ Broadcast complete.\nSuccess: {success}, Failed: {fail}")

# রিক্যাশ কমান্ড - চ্যানেল থেকে পুনরায় সব মুভি লোড করবে
@app.on_message(filters.command("recache") & filters.private)
async def recache(_, msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return await msg.reply("❌ You are not authorized.")
    global movie_cache
    movie_cache = []
    async for m in app.get_chat_history(CHANNEL_ID):
        title = m.caption or m.text
        if title:
            movie_cache.append({
                "title": title,
                "clean": clean(title),
                "message_id": m.message_id,
                "lang": detect_language(title)
            })
    save_data(MOVIE_DB, movie_cache)
    await msg.reply(f"✅ Recached {len(movie_cache)} movies.")

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
