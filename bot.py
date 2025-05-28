# ✅ Import libraries
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

# ✅ Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Configs from environment
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "0").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")

# ✅ Pyrogram Bot
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ✅ MongoDB setup
mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
users_col = db["users"]
subscribers_col = db["subscribers"]

# ✅ Indexes
movies_col.create_index([("title", ASCENDING)])
movies_col.create_index("message_id")
movies_col.create_index("language")

# ✅ Flask for uptime
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ Bot is running!"

Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

# ✅ Helpers
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
@app.on_message(filters.text & ~filters.command(["start", "subscribe", "unsubscribe", "stats", "delete_movie", "delete_all_movies"]) & (filters.private | filters.group))
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
        await message.reply("আপনার মুভির সাথে মিল পাওয়া গেছে, সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await loading.delete()
        for admin_id in ADMIN_IDS:
            try:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ আপনি ভুল নাম দিছেন", callback_data=f"reply_wrong_{message.from_user.id}_{query_raw[:30]}")],
                    [InlineKeyboardButton("⏳ মুভিটা এখনো আসেনি", callback_data=f"reply_notyet_{message.from_user.id}_{query_raw[:30]}")],
                    [InlineKeyboardButton("✅ মুভিটা চ্যানেলে আছে", callback_data=f"reply_exist_{message.from_user.id}_{query_raw[:30]}")],
                    [InlineKeyboardButton("🚀 মুভি আসছে শিগগিরই", callback_data=f"reply_soon_{message.from_user.id}_{query_raw[:30]}")],
                ])
                await app.send_message(admin_id, f"👤 ইউজার: {message.from_user.first_name} (@{message.from_user.username}) [{message.from_user.id}]\n🔍 সার্চ: {query_raw}\n📋 Action required: নিচে বাটন আছে, বেছে নিন।", reply_markup=keyboard)
            except Exception as e:
                logger.error(f"Failed to notify admin: {e}")
        await message.reply("😢 কিছু পাওয়া যায়নি, দয়া করে আবার চেষ্টা করুন। আপনার অনুরোধটি এডমিনদের জানানো হয়েছে।")

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

    elif data.startswith("reply_"):
        _, reason, user_id, query = data.split("_", 3)
        response_map = {
            "wrong": "❌ এডমিন জানিয়েছে: আপনি ভুল নাম দিছেন।",
            "notyet": "⏳ এডমিন জানিয়েছে: মুভিটা এখনো আসেনি।",
            "exist": "✅ এডমিন জানিয়েছে: মুভিটা চ্যানেলে আপলোড করা আছে, সঠিক নাম দিন।",
            "soon": "🚀 এডমিন জানিয়েছে: মুভিটা শিগগির আপলোড করা হবে।"
        }
        try:
            await app.send_message(int(user_id), response_map.get(reason, "⚠️ এডমিনের কাছ থেকে উত্তর পাওয়া যায়নি।"))
            await callback.answer("✅ ইউজারকে জানানো হয়েছে।")
        except Exception as e:
            logger.error(f"Failed to reply to user: {e}")
            await callback.answer("❌ ইউজারকে জানানো যায়নি।", show_alert=True)

# ✅ Admin-only delete commands
@app.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_IDS))
async def delete_all_movies(client, message):
    movies_col.delete_many({})
    await message.reply("🗑️ সব মুভি ডিলিট করা হয়েছে।")

@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_movie(client, message):
    if len(message.command) < 2:
        return await message.reply("⚠️ ব্যবহার: /delete_movie <movie name>")
    query = " ".join(message.command[1:]).lower()
    result = movies_col.delete_one({"title": {"$regex": query, "$options": "i"}})
    if result.deleted_count:
        await message.reply("✅ মুভি ডিলিট করা হয়েছে।")
    else:
        await message.reply("❌ মুভি খুঁজে পাওয়া যায়নি।")

# ✅ Subscribe / Unsubscribe / Stats / Start
@app.on_message(filters.command("subscribe") & (filters.private | filters.group))
async def subscribe(client, message):
    user_id = message.from_user.id
    if not subscribers_col.find_one({"user_id": user_id}):
        subscribers_col.insert_one({"user_id": user_id})
        await message.reply("✅ সাবস্ক্রিপশন সফল।")
    else:
        await message.reply("ℹ️ আপনি ইতিমধ্যে সাবস্ক্রাইব করেছেন।")

@app.on_message(filters.command("unsubscribe") & (filters.private | filters.group))
async def unsubscribe(client, message):
    subscribers_col.delete_one({"user_id": message.from_user.id})
    await message.reply("❌ আপনি আনসাবস্ক্রাইব করেছেন।")

@app.on_message(filters.command("stats") & (filters.private | filters.group))
async def stats(client, message):
    stats_text = (
        f"📊 পরিসংখ্যান:\n"
        f"👤 ইউজার: {users_col.count_documents({})}\n"
        f"🔔 সাবস্ক্রাইবার: {subscribers_col.count_documents({})}\n"
        f"🎬 মুভি: {movies_col.count_documents({})}"
    )
    await message.reply(stats_text)

@app.on_message(filters.command("start") & (filters.private | filters.group))
async def start(client, message):
    await message.reply(
        f"হ্যালো {message.from_user.first_name}!\n"
        "আমি একটি মুভি সার্চ বট। শুধু মুভির নাম লিখো, আমি খুঁজে দিবো।\n"
        f"🔔 আপডেট পেতে: {UPDATE_CHANNEL}"
    )

# ✅ Run bot
app.run()
