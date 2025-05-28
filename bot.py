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

# Flask for uptime
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
            "message_id": message.id,
            "language": "Unknown",
            "posted_at": datetime.utcnow()
        }
        movies_col.insert_one(movie_data)
        logger.info(f"✅ Saved movie: {movie_title}")
        await notify_subscribers(movie_title)
    except Exception as e:
        logger.error(f"❌ Movie save failed: {e}")

# ✅ Search Handler
@app.on_message(filters.text & ~filters.command(["start", "subscribe", "unsubscribe", "stats", "delete_all_movies", "delete_movie"]) & (filters.private | filters.group))
async def search_handler(client, message):
    query_raw = message.text.strip()
    query_clean = clean_text(query_raw)
    users_col.update_one({"_id": message.from_user.id}, {"$set": {"last_search": datetime.utcnow()}}, upsert=True)
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
        short_query = query_raw[:30]
        buttons.append([
            InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{short_query}"),
            InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{short_query}"),
            InlineKeyboardButton("English", callback_data=f"lang_English_{short_query}")
        ])
        await message.reply("আপনার মুভির সাথে মিল পাওয়া গেছে, সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await loading.edit("😢 কিছু পাওয়া যায়নি, দয়া করে আবার চেষ্টা করুন।")
        buttons = [
            [InlineKeyboardButton("❌ আপনি ভুল নাম দিছেন", callback_data=f"nofind_wrong_{query_raw[:30]}")],
            [InlineKeyboardButton("⏳ মুভিটা এখনো আসেনি", callback_data=f"nofind_notyet_{query_raw[:30]}")],
            [InlineKeyboardButton("✅ মুভিটা চ্যানেলে আপলোড করা আছে", callback_data=f"nofind_exist_{query_raw[:30]}")],
            [InlineKeyboardButton("🚀 এডমিন অনেক তাড়াতাড়ি এই মুভি ডাউনলোড করবে", callback_data=f"nofind_soon_{query_raw[:30]}")],
        ]
        await message.reply("আপনার মুভিটি খুঁজে পাওয়া যায়নি। নিচের অপশনগুলোর যেকোনো একটি নির্বাচন করুন:", reply_markup=InlineKeyboardMarkup(buttons))

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
    elif data.startswith("nofind_"):
        reason, query = data.split("_")[1], "_".join(data.split("_")[2:])
        user = callback.from_user
        reason_text = {
            "wrong": "❌ আপনি ভুল নাম দিছেন",
            "notyet": "⏳ মুভিটা এখনো আসেনি",
            "exist": "✅ মুভিটা চ্যানেলে আপলোড করা আছে",
            "soon": "🚀 এডমিন অনেক তাড়াতাড়ি এই মুভি ডাউনলোড করবে"
        }.get(reason, "Unknown")
        for admin_id in ADMIN_IDS:
            try:
                await app.send_message(
                    admin_id,
                    f"📩 নতুন রিপোর্ট এসেছে:\n\n👤 ইউজার: {user.first_name} (@{user.username}) [{user.id}]\n🔎 সার্চ কীওয়ার্ড: {query}\n📋 কারণ: {reason_text}"
                )
            except Exception as e:
                logger.error(f"Admin notify failed: {e}")
        await callback.answer("✅ এডমিনকে জানানো হয়েছে। ধন্যবাদ।", show_alert=True)

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

# ✅ Delete all movies (admin only)
@app.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_IDS))
async def delete_all_movies(client, message):
    result = movies_col.delete_many({})
    await message.reply(f"🗑️ মোট {result.deleted_count}টি মুভি ডিলিট করা হয়েছে।")

# ✅ Delete specific movie (admin only)
@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_movie(client, message):
    if len(message.command) < 2:
        await message.reply("⚠️ দয়া করে একটি মুভির নাম দিন। যেমন:\n`/delete_movie Avengers`")
        return
    title_query = " ".join(message.command[1:]).strip().lower()
    all_movies = list(movies_col.find({}, {"_id": 1, "title": 1}))
    to_delete = None
    for movie in all_movies:
        if movie["title"].lower() == title_query:
            to_delete = movie["_id"]
            break
    if to_delete:
        movies_col.delete_one({"_id": to_delete})
        await message.reply("✅ মুভিটি সফলভাবে ডিলিট হয়েছে।")
    else:
        await message.reply("❌ মুভিটি খুঁজে পাওয়া যায়নি।")

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
