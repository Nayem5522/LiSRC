from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient, ASCENDING
from flask import Flask
from threading import Thread
import os
import re
from datetime import datetime
import asyncio
import urllib.parse
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
stats_col = db["stats"]
users_col = db["users"]
settings_col = db["settings"]

# Index
movies_col.create_index([("title", ASCENDING)])
movies_col.create_index("message_id")
movies_col.create_index("language")

# Flask
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Bot is running!"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

# Helpers
def clean_text(text):
    return re.sub(r'\s+', '', re.sub(r'[^a-zA-Z0-9 ]', '', text.lower()))

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
        "language": extract_language(text)
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
    asyncio.create_task(delete_message_later(m.chat.id, m.id))

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

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg):
    await msg.reply(
        f"Users: {users_col.count_documents({})}\n"
        f"Movies: {movies_col.count_documents({})}\n"
        f"Feedbacks: {feedback_col.count_documents({})}"
    )

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

@app.on_message(filters.text)
async def search(_, msg):
    raw_query = msg.text.strip()
    query = clean_text(raw_query)
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"last_search": datetime.utcnow()}},
        upsert=True
    )

    loading = await msg.reply("🔎 লোড হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1, "language": 1}))
    exact_match = [m for m in all_movies if clean_text(m.get("title", "")) == query]

    if exact_match:
        await loading.delete()
        for m in exact_match[:RESULTS_COUNT]:
            fwd = await app.forward_messages(msg.chat.id, CHANNEL_ID, m["message_id"])
            warning = await msg.reply(
                f"⚠️ এটি অস্থায়ী মেসেজ। **10 মিনিট** পরে ডিলিট হয়ে যাবে।",
                reply_to_message_id=fwd.id
            )
            asyncio.create_task(delete_message_later(msg.chat.id, fwd.id))
            asyncio.create_task(delete_message_later(warning.chat.id, warning.id))
            await asyncio.sleep(0.5)
        return

    partial_matches = [m for m in all_movies if query in clean_text(m.get("title", ""))]
    results = [m for m in partial_matches if get_similarity(query, clean_text(m.get("title", ""))) > 0.25][:RESULTS_COUNT]

    await loading.delete()
    if not results:
        return await msg.reply("দুঃখিত, কিছুই পাওয়া যায়নি।")

    for m in results:
        fwd = await app.forward_messages(msg.chat.id, CHANNEL_ID, m["message_id"])
        warning = await msg.reply(
            f"⚠️ এটি অস্থায়ী মেসেজ। **10 মিনিট** পরে ডিলিট হয়ে যাবে।",
            reply_to_message_id=fwd.id
        )
        asyncio.create_task(delete_message_later(msg.chat.id, fwd.id))
        asyncio.create_task(delete_message_later(warning.chat.id, warning.id))
        await asyncio.sleep(0.5)

@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data

    if data.startswith("movie_"):
        mid = int(data.split("_")[1])
        fwd = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
        warning = await cq.message.reply(
            f"⚠️ এটি অস্থায়ী মেসেজ। **10 মিনিট** পরে ডিলিট হয়ে যাবে।",
            reply_to_message_id=fwd.id
        )
        asyncio.create_task(delete_message_later(cq.message.chat.id, fwd.id))
        asyncio.create_task(delete_message_later(warning.chat.id, warning.id))
        await cq.answer("মুভি পাঠানো হয়েছে।")

if __name__ == "__main__":
    print("Bot is starting...")
    app.run()
