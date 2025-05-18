import os
import re
import asyncio
import urllib.parse
import logging
from datetime import datetime

from flask import Flask
from threading import Thread

from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from pymongo import MongoClient, ASCENDING
from fuzzywuzzy import process

# -------------------
# Configuration
# -------------------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", "10"))
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")
START_PIC = os.getenv(
    "START_PIC",
    "https://i.ibb.co/prnGXMr3/photo-2025-05-16-05-15-45-7504908428624527364.jpg",
)
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Safely parse ADMIN_IDS
admin_ids_env = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x) for x in admin_ids_env.split(",") if x.isdigit()]

# -------------------
# Logging
# -------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# -------------------
# MongoDB setup
# -------------------
mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
feedback_col = db["feedback"]
stats_col = db["stats"]
users_col = db["users"]
settings_col = db["settings"]

# Ensure indexes
movies_col.create_index([("title", ASCENDING)])
movies_col.create_index("message_id")
movies_col.create_index("language")

# -------------------
# Flask for health check
# -------------------
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)

# -------------------
# Pyrogram client
# -------------------
bot = Client(
    "movie_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    sleep_threshold=60,
)

def clean_text(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", text.lower())

def extract_year(text: str) -> str | None:
    match = re.search(r"(19|20)\d{2}", text)
    return match.group() if match else None

def extract_language(text: str) -> str:
    langs = ["Bengali", "Hindi", "English"]
    for lang in langs:
        if lang.lower() in text.lower():
            return lang
    return "Unknown"

async def delete_message_later(chat_id: int, message_id: int, delay: int = 600):
    await asyncio.sleep(delay)
    try:
        await bot.delete_messages(chat_id, message_id)
    except Exception:
        pass

# -------------------
# Handlers
# -------------------
@bot.on_message(filters.chat(CHANNEL_ID))
async def save_post(_, msg: Message):
    text = msg.text or msg.caption
    if not text:
        return
    movie = {
        "message_id": msg.id,
        "title": text,
        "date": msg.date,
        "year": extract_year(text),
        "language": extract_language(text),
    }
    movies_col.update_one(
        {"message_id": msg.id}, {"$set": movie}, upsert=True
    )

    setting = settings_col.find_one({"key": "global_notify"})
    if setting and setting.get("value"):
        for user in users_col.find({"notify": {"$ne": False}}):
            try:
                await bot.send_message(
                    user["_id"],
                    f"নতুন মুভি আপলোড হয়েছে:\n{text.splitlines()[0][:100]}\nএখনই সার্চ করে দেখুন!",
                )
            except Exception:
                pass

@bot.on_message(filters.command("start") & filters.private)
async def start(_, msg: Message):
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"joined": datetime.utcnow()}},
        upsert=True
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Update Channel", url=UPDATE_CHANNEL)],
        [InlineKeyboardButton("Contact Admin", url="https://t.me/ctgmovies23")],
    ])
    await msg.reply_photo(
        photo=START_PIC,
        caption="Send me a movie name to search.",
        reply_markup=buttons,
    )

@bot.on_message(filters.command("feedback") & filters.private)
async def feedback(_, msg: Message):
    if len(msg.command) < 2:
        return await msg.reply("Please write something after /feedback.")
    text = msg.text.split(None, 1)[1]
    feedback_col.insert_one({
        "user": msg.from_user.id,
        "text": text,
        "time": datetime.utcnow()
    })
    m = await msg.reply("Thanks for your feedback!")
    asyncio.create_task(delete_message_later(m.chat.id, m.id))

@bot.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(_, msg: Message):
    if len(msg.command) < 2:
        return await msg.reply("Usage: /broadcast Your message here")
    text = msg.text.split(None, 1)[1]
    count = 0
    for user in users_col.find():
        try:
            await bot.send_message(user["_id"], text)
            count += 1
        except Exception:
            pass
    await msg.reply(f"Broadcast sent to {count} users.")

@bot.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg: Message):
    user_count = users_col.count_documents({})
    movie_count = movies_col.count_documents({})
    fb_count = feedback_col.count_documents({})
    await msg.reply(
        f"Users: {user_count}\n"
        f"Movies: {movie_count}\n"
        f"Feedbacks: {fb_count}"
    )

@bot.on_message(filters.command("notify") & filters.user(ADMIN_IDS))
async def notify_command(_, msg: Message):
    parts = msg.command
    if len(parts) != 2 or parts[1] not in ("on", "off"):
        return await msg.reply("ব্যবহার: /notify on  অথবা  /notify off")
    new_value = parts[1] == "on"
    settings_col.update_one(
        {"key": "global_notify"},
        {"$set": {"value": new_value}},
        upsert=True
    )
    status = "enabled" if new_value else "disabled"
    await msg.reply(f"✅ Global notifications {status}!")

# -------------------
# Search Handler
# -------------------
@bot.on_message(filters.text & ~filters.regex(r"^/"))
async def search(_, msg: Message):
    raw_query = msg.text.strip()
    query = clean_text(raw_query)
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"last_search": datetime.utcnow()}},
        upsert=True
    )

    loading = await msg.reply("🔎 লোড হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1, "language": 1}))

    # Exact match
    exact = [m for m in all_movies if clean_text(m["title"]) == query]
    if exact:
        await loading.delete()
        buttons = [
            [InlineKeyboardButton(m["title"][[:40]], callback_data=f"movie_{m['message_id']}")]
            for m in exact[:RESULTS_COUNT]
        ]
        res = await msg.reply("নিচের ফলাফল থেকে বেছে নিন:", reply_markup=InlineKeyboardMarkup(buttons))
        asyncio.create_task(delete_message_later(res.chat.id, res.id))
        return

    # Substring suggestions
    suggested = [
        m for m in all_movies
        if re.search(re.escape(raw_query), m['title'], re.IGNORECASE)
    ]
    if suggested:
        await loading.delete()
        lang_row = [
            InlineKeyboardButton(lang, callback_data=f"lang_{lang}_{query}")
            for lang in ("Bengali", "Hindi", "English")
        ]
        buttons = [
            [InlineKeyboardButton(m["title"][[:40]], callback_data=f"movie_{m['message_id']}")]
            for m in suggested[:RESULTS_COUNT]
        ]
        buttons.append(lang_row)
        res = await msg.reply(
            "আপনার মুভির নাম মিলতে পারে, নিচের থেকে সিলেক্ট করুন:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        asyncio.create_task(delete_message_later(res.chat.id, res.id))
        return

    # Fuzzy match
    titles = [m['title'] for m in all_movies]
    fuzzy = process.extractOne(raw_query, titles)
    if fuzzy and fuzzy[1] > 75:
        matched = fuzzy[0]
        fuzzy_matches = [m for m in all_movies if m['title'] == matched]
        if fuzzy_matches:
            await loading.delete()
            buttons = [
                [InlineKeyboardButton(m["title"][[:40]], callback_data=f"movie_{m['message_id']}")]
                for m in fuzzy_matches[:RESULTS_COUNT]
            ]
            res = await msg.reply("ফাজি ম্যাচ পাওয়া গেছে:", reply_markup=InlineKeyboardMarkup(buttons))
            asyncio.create_task(delete_message_later(res.chat.id, res.id))
            return

    # No results
    await loading.delete()
    google_url = "https://www.google.com/search?q=" + urllib.parse.quote(raw_query)
    alert = await msg.reply(
        "কোনও ফলাফল পাওয়া যায়নি। অ্যাডমিনকে জানানো হয়েছে। নিচের বাটনে ক্লিক করে গুগলে সার্চ করুন।",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Search on Google", url=google_url)]])
    )
    asyncio.create_task(delete_message_later(alert.chat.id, alert.id))

    feedback_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ মুভি আছে", callback_data=f"has_{msg.chat.id}_{msg.id}_{raw_query}"),
            InlineKeyboardButton("❌ নেই", callback_data=f"no_{msg.chat.id}_{msg.id}_{raw_query}")
        ],
        [
            InlineKeyboardButton("⏳ আসবে", callback_data=f"soon_{msg.chat.id}_{msg.id}_{raw_query}"),
            InlineKeyboardButton("✏️ ভুল নাম", callback_data=f"wrong_{msg.chat.id}_{msg.id}_{raw_query}")
        ]
    ])
    for admin in ADMIN_IDS:
        await bot.send_message(
            admin,
            f"❗ ইউজার `{msg.from_user.id}` `{msg.from_user.first_name}` খুঁজেছে: **{raw_query}**\nফলাফল পাওয়া যায়নি। নিচে বাটন থেকে উত্তর দিন.",
            reply_markup=feedback_buttons
        )

@bot.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data or ""
    if data.startswith("movie_"):
        mid = int(data.split("_", 1)[1])
        fwd = await bot.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
        asyncio.create_task(delete_message_later(cq.message.chat.id, fwd.id))
        await cq.answer("মুভি পাঠানো হয়েছে।")
        return

    if data.startswith("lang_"):
        _, lang, query = data.split("_", 2)
        lang_movies = list(movies_col.find({"language": lang}))
        matches = [
            m for m in lang_movies
            if re.search(re.escape(query), m.get("title", ""), re.IGNORECASE)
        ]
        if matches:
            buttons = [
                [InlineKeyboardButton(m["title"][[:40]], callback_data=f"movie_{m['message_id']}")]
                for m in matches[:RESULTS_COUNT]
            ]
            await cq.message.edit_text(
                f"ফলাফল ({lang}) - নিচের থেকে সিলেক্ট করুন:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await cq.answer("এই ভাষায় কিছু পাওয়া যায়নি।", show_alert=True)
        return

    parts = data.split("_", 3)
    if len(parts) == 4:
        action, uid, mid, raw_query = parts
        uid = int(uid)
        user_tag = cq.from_user.username or cq.from_user.first_name
        resp_map = {
            "has":   f"✅ @{user_tag} জানিয়েছেন যে **{raw_query}** মুভি আছে।",
            "no":    f"❌ @{user_tag} জানিয়েছেন যে **{raw_query}** মুভি নেই।",
            "soon":  f"⏳ @{user_tag} জানিয়েছেন যে **{raw_query}** আসবে।",
            "wrong": f"✏️ @{user_tag} জানিয়েছেন যে **{raw_query}** নাম ভুল।",
        }
        if action in resp_map:
            await bot.send_message(uid, resp_map[action])
            await cq.answer("রিপোর্ট পাঠানো হয়েছে।")
            await cq.message.delete()

# -------------------
# Main entrypoint
# -------------------
if __name__ == "__main__":
    logger.info(f"Starting Flask thread and bot. Admin IDs: {ADMIN_IDS}")
    Thread(target=run_flask, daemon=True).start()
    bot.run()
