from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient, ASCENDING
from flask import Flask
from threading import Thread
import os
import re
import asyncio
from datetime import datetime
from rapidfuzz import fuzz, process
import logging

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configs from environment
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "0").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")

# Pyrogram Bot
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# MongoDB setup
mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
users_col = db["users"]
subscribers_col = db["subscribers"]

# Indexes
movies_col.create_index([("title", ASCENDING)])
movies_col.create_index("message_id")
movies_col.create_index("language")

# Flask for uptime (Replit or similar)
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "✅ Bot is running!"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

# Helpers
def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

async def delete_message_later(chat_id, message_id, delay=600):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except Exception as e:
        logger.warning(f"Auto delete failed: {e}")

async def notify_subscribers(movie_title):
    for sub in subscribers_col.find():
        try:
            await app.send_message(sub["user_id"], f"🎬 নতুন মুভি পোস্ট হয়েছে: {movie_title}\n\n{UPDATE_CHANNEL}")
        except Exception as e:
            logger.warning(f"Notify failed for {sub['user_id']}: {e}")

# ✅ Save new movie from channel
@app.on_message(filters.channel)
async def save_movie(client, message):
    try:
        if not message.text:
            return
        movie_title = message.text.splitlines()[0]
        movie_data = {
            "title": movie_title.strip(),
            "message_id": message.message_id,
            "language": "Unknown",
            "posted_at": datetime.utcnow()
        }
        movies_col.insert_one(movie_data)
        logger.info(f"✅ Saved movie: {movie_title}")
        await notify_subscribers(movie_title)
    except Exception as e:
        logger.error(f"❌ Movie save failed: {e}")

# ✅ Search Handler
@app.on_message(filters.text & ~filters.command(["start", "subscribe", "unsubscribe", "stats"]) & (filters.private | filters.group))
async def search_handler(client, message):
    query_raw = message.text.strip()
    query_clean = clean_text(query_raw)
    await users_col.update_one({"_id": message.from_user.id}, {"$set": {"last_search": datetime.utcnow()}}, upsert=True)
    
    loading = await message.reply("🔎 অনুসন্ধান চলছে...")

    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1, "language": 1}))
    exact_matches = [m for m in all_movies if clean_text(m["title"]) == query_clean]

    if exact_matches:
        await loading.delete()
        for m in exact_matches[:RESULTS_COUNT]:
            try:
                fwd = await app.forward_messages(message.chat.id, CHANNEL_ID, m["message_id"])
                await message.reply(f"🎬 {m['title']}\n\n⚠️ মেসেজটি ১০ মিনিট পরে অটো ডিলিট হবে।")
                asyncio.create_task(delete_message_later(message.chat.id, fwd.id))
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"Forward failed: {e}")
        return

    choices = {m["title"]: m for m in all_movies}
    fuzzy_results = process.extract(query_raw, choices.keys(), scorer=fuzz.partial_ratio, limit=RESULTS_COUNT)
    filtered = [choices[title] for title, score, _ in fuzzy_results if score >= 70]

    if filtered:
        await loading.delete()
        buttons = [[InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")] for m in filtered]
        buttons.append([
            InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{query_raw}"),
            InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{query_raw}"),
            InlineKeyboardButton("English", callback_data=f"lang_English_{query_raw}")
        ])
        await message.reply("আপনার মুভির সাথে মিল পাওয়া গেছে, সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await loading.edit("😢 কিছু পাওয়া যায়নি, দয়া করে আবার চেষ্টা করুন।")

# ✅ Callback handler
@app.on_callback_query()
async def callback_handler(client, callback):
    data = callback.data
    if data.startswith("movie_"):
        msg_id = int(data.split("_")[1])
        try:
            fwd = await app.forward_messages(callback.message.chat.id, CHANNEL_ID, msg_id)
            await callback.answer("✅ মুভি পাঠানো হয়েছে!")
            asyncio.create_task(delete_message_later(callback.message.chat.id, fwd.id))
        except Exception as e:
            await callback.answer("❌ মুভি পাঠানো যায়নি।", show_alert=True)
            logger.error(f"Forward error: {e}")
    elif data.startswith("lang_"):
        lang = data.split("_")[1]
        query = "_".join(data.split("_")[2:])
        lang_movies = list(movies_col.find({"language": lang}))
        choices = {m["title"]: m for m in lang_movies}
        fuzzy_results = process.extract(query, choices.keys(), scorer=fuzz.partial_ratio, limit=RESULTS_COUNT)
        filtered = [choices[title] for title, score, _ in fuzzy_results if score >= 70]
        if filtered:
            buttons = [[InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")] for m in filtered]
            await callback.message.edit_text(f"🔍 ভাষা: {lang} এর ফলাফল:", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await callback.answer("❌ কোনো ফলাফল পাওয়া যায়নি।", show_alert=True)

# ✅ Subscribe command
@app.on_message(filters.command("subscribe") & (filters.private | filters.group))
async def subscribe(client, message):
    user_id = message.from_user.id
    if not subscribers_col.find_one({"user_id": user_id}):
        subscribers_col.insert_one({"user_id": user_id})
        await message.reply("✅ সাবস্ক্রিপশন সফল।")
    else:
        await message.reply("ℹ️ আপনি ইতিমধ্যে সাবস্ক্রাইব করেছেন।")

# ✅ Unsubscribe command
@app.on_message(filters.command("unsubscribe") & (filters.private | filters.group))
async def unsubscribe(client, message):
    subscribers_col.delete_one({"user_id": message.from_user.id})
    await message.reply("❌ আপনি আনসাবস্ক্রাইব করেছেন।")

# ✅ Stats command
@app.on_message(filters.command("stats") & (filters.private | filters.group))
async def stats(client, message):
    stats_text = (
        f"📊 পরিসংখ্যান:\n"
        f"👤 ইউজার: {users_col.count_documents({})}\n"
        f"🔔 সাবস্ক্রাইবার: {subscribers_col.count_documents({})}\n"
        f"🎬 মুভি: {movies_col.count_documents({})}"
    )
    await message.reply(stats_text)

# ✅ Start command
@app.on_message(filters.command("start") & (filters.private | filters.group))
async def start(client, message):
    await message.reply(
        f"হ্যালো {message.from_user.first_name}!\n"
        "আমি একটি মুভি সার্চ বট। শুধু মুভির নাম লিখো, আমি খুঁজে দিবো।\n"
        f"🔔 আপডেট পেতে: {UPDATE_CHANNEL}"
    )

# ✅ Run bot
app.run()
