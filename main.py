from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient, ASCENDING
from flask import Flask
from threading import Thread
import os
import re
from datetime import datetime
import asyncio
from difflib import SequenceMatcher

# Configs
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")
START_PIC = os.getenv("START_PIC", "https://i.ibb.co/prnGXMr3/photo-2025-05-16-05-15-45-7504908428624527364.jpg")

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# MongoDB setup
mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
feedback_col = db["feedback"]
users_col = db["users"]
settings_col = db["settings"]

# Index for faster search
movies_col.create_index([("title", ASCENDING)])
movies_col.create_index("message_id")
movies_col.create_index("language")

# Flask for uptime
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Bot is running!"

Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

# Helpers
def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

def extract_year(text):
    match = re.search(r"(19|20)\d{2}", text)
    return match.group() if match else None

def extract_language(text):
    langs = ["Bengali", "Hindi", "English"]
    return next((lang for lang in langs if lang.lower() in text.lower()), "Unknown")

def get_similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

async def delete_message_later(chat_id, message_id, delay=600):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except:
        pass

# Save posts from channel to DB
@app.on_message(filters.chat(CHANNEL_ID))
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
        "clean_title": clean_text(text)
    }
    movies_col.update_one({"message_id": msg.id}, {"$set": movie}, upsert=True)

    setting = settings_col.find_one({"key": "global_notify"})
    if setting and setting.get("value"):
        for user in users_col.find({"notify": {"$ne": False}}):
            try:
                await app.send_message(
                    user["_id"],
                    f"নতুন মুভি আপলোড হয়েছে:\n{text.splitlines()[0][:100]}\nএখনই সার্চ করে দেখুন!"
                )
            except:
                pass

# Start command
@app.on_message(filters.command("start"))
async def start(_, msg: Message):
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"joined": datetime.utcnow()}},
        upsert=True
    )
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("Update Channel", url=UPDATE_CHANNEL)],
        [InlineKeyboardButton("Contact Admin", url="https://t.me/ctgmovies23")]
    ])
    await msg.reply_photo(photo=START_PIC, caption="Send me a movie name to search.", reply_markup=btns)

# Feedback command
@app.on_message(filters.command("feedback") & filters.private)
async def feedback(_, msg):
    if len(msg.command) < 2:
        return await msg.reply("Please write something after /feedback.")
    feedback_col.insert_one({
        "user": msg.from_user.id,
        "text": msg.text.split(None, 1)[1],
        "time": datetime.utcnow()
    })
    m = await msg.reply("Thanks for your feedback!")
    asyncio.create_task(delete_message_later(m.chat.id, m.id, delay=60))

# Broadcast command
@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(_, msg):
    if len(msg.command) < 2:
        return await msg.reply("Usage: /broadcast Your message here")
    count = 0
    for user in users_col.find():
        try:
            await app.send_message(user["_id"], msg.text.split(None, 1)[1])
            count += 1
        except:
            pass
    await msg.reply(f"Broadcast sent to {count} users.")

# Stats command
@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg):
    await msg.reply(
        f"Users: {users_col.count_documents({})}\n"
        f"Movies: {movies_col.count_documents({})}\n"
        f"Feedbacks: {feedback_col.count_documents({})}"
    )

# Notify toggle command
@app.on_message(filters.command("notify") & filters.user(ADMIN_IDS))
async def notify_command(_, msg: Message):
    if len(msg.command) != 2 or msg.command[1] not in ["on", "off"]:
        return await msg.reply("ব্যবহার: /notify on  অথবা  /notify off")
    new_value = True if msg.command[1] == "on" else False
    settings_col.update_one(
        {"key": "global_notify"},
        {"$set": {"value": new_value}},
        upsert=True
    )
    status = "enabled" if new_value else "disabled"
    await msg.reply(f"✅ Global notifications {status}!")

# Search command (main logic)
@app.on_message(filters.text & ~filters.command)
async def search(_, msg):
    raw_query = msg.text.strip()
    query = clean_text(raw_query)

    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"last_search": datetime.utcnow()}},
        upsert=True
    )

    loading = await msg.reply("🔎 লোড হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")

    # Find movies with clean_title matching query (case-insensitive exact match)
    exact_matches = list(movies_col.find({"clean_title": query}))

    if exact_matches:
        await loading.delete()
        for movie in exact_matches[:RESULTS_COUNT]:
            fwd = await app.forward_messages(msg.chat.id, CHANNEL_ID, movie["message_id"])
            warning = await msg.reply(
                f"⚠️ এটি অস্থায়ী মেসেজ। **১০ মিনিট** পরে ডিলিট হয়ে যাবে।",
                reply_to_message_id=fwd.id
            )
            asyncio.create_task(delete_message_later(msg.chat.id, fwd.id))
            asyncio.create_task(delete_message_later(warning.chat.id, warning.id))
            # Sleep removed for speed optimization
        return

    # If no exact match, do fuzzy search on titles with similarity > 0.7
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1}))
    fuzzy_matches = []
    for m in all_movies:
        title = m.get("title", "")
        sim = get_similarity(raw_query, title)
        if sim > 0.7:
            fuzzy_matches.append((sim, m))

    fuzzy_matches.sort(key=lambda x: x[0], reverse=True)

    if fuzzy_matches:
        await loading.delete()
        for _, movie in fuzzy_matches[:RESULTS_COUNT]:
            fwd = await app.forward_messages(msg.chat.id, CHANNEL_ID, movie["message_id"])
            warning = await msg.reply(
                f"⚠️ এটি অস্থায়ী মেসেজ। **১০ মিনিট** পরে ডিলিট হয়ে যাবে।",
                reply_to_message_id=fwd.id
            )
            asyncio.create_task(delete_message_later(msg.chat.id, fwd.id))
            asyncio.create_task(delete_message_later(warning.chat.id, warning.id))
            # Sleep removed for speed optimization
        return

    await loading.edit("কিছু পাওয়া যায়নি। অনুগ্রহ করে আবার চেষ্টা করুন।")

# Callback query handler (if needed)
@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data

    if data.startswith("movie_"):
        mid = int(data.split("_")[1])
        fwd = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
        warning = await cq.message.reply(
            f"⚠️ এটি অস্থায়ী মেসেজ। **১০ মিনিট** পরে ডিলিট হয়ে যাবে।",
            reply_to_message_id=fwd.id
        )
        asyncio.create_task(delete_message_later(cq.message.chat.id, fwd.id))
        asyncio.create_task(delete_message_later(warning.chat.id, warning.id))
        await cq.answer("মুভি পাঠানো হয়েছে।")

if __name__ == "__main__":
    print("Bot is starting...")
    app.run()
