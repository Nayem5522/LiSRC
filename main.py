# Final Telegram Movie Bot with All Features

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from pymongo import MongoClient, ASCENDING
from flask import Flask
from threading import Thread
import os
import re
import asyncio
from datetime import datetime
import urllib.parse
import logging
from difflib import get_close_matches
import uuid

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

# MongoDB
mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
feedback_col = db["feedback"]
stats_col = db["stats"]
users_col = db["users"]
settings_col = db["settings"]
logs_col = db["logs"]

movies_col.create_index([("title", ASCENDING)])
movies_col.create_index("message_id")
movies_col.create_index("language")

# Flask
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Movie Bot is Running!"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

# Helpers
def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

def extract_language(text):
    langs = ["Bengali", "Hindi", "English"]
    return next((lang for lang in langs if lang.lower() in text.lower()), "Unknown")

def extract_year(text):
    match = re.search(r"(19|20)\\d{2}", text)
    return match.group() if match else None

async def delete_later(chat_id, message_id, delay=600):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except: pass

async def log_error(user_id, error_text):
    logs_col.insert_one({"user_id": user_id, "error": error_text, "time": datetime.utcnow()})

# Save Posts
download_stats = {}

@app.on_message(filters.chat(CHANNEL_ID))
async def index_movie(_, msg: Message):
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

# /start
@app.on_message(filters.command("start"))
async def start(_, msg):
    users_col.update_one({"_id": msg.from_user.id}, {"$set": {"joined": datetime.utcnow()}}, upsert=True)
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("Update Channel", url=UPDATE_CHANNEL)],
        [InlineKeyboardButton("Contact Admin", url="https://t.me/ctgmovies23")]
    ])
    await msg.reply_photo(START_PIC, caption="Send movie name or use inline mode to search.", reply_markup=btns)

# Feedback
@app.on_message(filters.command("feedback") & filters.private)
async def feedback(_, msg):
    if len(msg.command) < 2:
        return await msg.reply("Write something after /feedback")
    feedback_col.insert_one({
        "user": msg.from_user.id,
        "text": msg.text.split(None, 1)[1],
        "time": datetime.utcnow()
    })
    m = await msg.reply("Thanks for your feedback!")
    asyncio.create_task(delete_later(m.chat.id, m.id))

@app.on_message(filters.command("viewfeedback") & filters.user(ADMIN_IDS))
async def view_feedback(_, msg):
    feedbacks = feedback_col.find().sort("time", -1).limit(5)
    text = "".join([f"{f['text']} (by {f['user']})\n" for f in feedbacks]) or "No feedback found."
    await msg.reply(text)

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg):
    await msg.reply(f"Users: {users_col.count_documents({})}\nMovies: {movies_col.count_documents({})}")

# Inline Mode
@app.on_inline_query()
async def inline_search(_, iq: InlineQuery):
    query = clean_text(iq.query)
    results = []
    if query:
        all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1}))
        matched = get_close_matches(query, [clean_text(m["title"]) for m in all_movies], n=RESULTS_COUNT, cutoff=0.4)
        for m in all_movies:
            if clean_text(m["title"]) in matched:
                results.append(
                    InlineQueryResultArticle(
                        title=m["title"][:50],
                        input_message_content=InputTextMessageContent(f"#{m['message_id']}_movie"),
                        description="Click to get movie"
                    )
                )
    await iq.answer(results[:RESULTS_COUNT], cache_time=3)

# Inline Message Handler
@app.on_message(filters.regex(r"#(\\d+)_movie"))
async def send_movie(_, msg: Message):
    mid = int(re.findall(r"#(\\d+)_movie", msg.text)[0])
    fwd = await app.forward_messages(msg.chat.id, CHANNEL_ID, mid)
    download_stats[mid] = download_stats.get(mid, 0) + 1
    asyncio.create_task(delete_later(msg.chat.id, fwd.id))

# Text Search
@app.on_message(filters.text & filters.private)
async def search(_, msg):
    query = clean_text(msg.text)
    users_col.update_one({"_id": msg.from_user.id}, {"$set": {"last_search": datetime.utcnow()}}, upsert=True)
    loading = await msg.reply("Searching...")
    try:
        all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1, "language": 1}))
        exact = [m for m in all_movies if clean_text(m.get("title", "")) == query]
        if exact:
            await loading.delete()
            for m in exact[:RESULTS_COUNT]:
                fwd = await app.forward_messages(msg.chat.id, CHANNEL_ID, m["message_id"])
                download_stats[m["message_id"]] = download_stats.get(m["message_id"], 0) + 1
                asyncio.create_task(delete_later(msg.chat.id, fwd.id))
            return

        fuzzy = get_close_matches(query, [clean_text(m.get("title", "")) for m in all_movies], n=RESULTS_COUNT, cutoff=0.4)
        if fuzzy:
            matched_movies = [m for m in all_movies if clean_text(m.get("title", "")) in fuzzy]
            btns = [[InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")] for m in matched_movies]
            m = await msg.reply("Select your movie:", reply_markup=InlineKeyboardMarkup(btns))
            asyncio.create_task(delete_later(m.chat.id, m.id))
            await loading.delete()
            return

        await loading.delete()
        await msg.reply("No match found.")
    except Exception as e:
        await loading.delete()
        await log_error(msg.from_user.id, str(e))
        await msg.reply("Something went wrong.")

# Callback
@app.on_callback_query()
async def callback(_, cq: CallbackQuery):
    if cq.data.startswith("movie_"):
        mid = int(cq.data.split("_")[1])
        fwd = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
        download_stats[mid] = download_stats.get(mid, 0) + 1
        asyncio.create_task(delete_later(cq.message.chat.id, fwd.id))
        await cq.answer("Movie sent!")

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
