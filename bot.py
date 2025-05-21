# Advanced Telegram Movie Bot with Inline, CAPTCHA, Fuzzy Search, Download Count

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from pymongo import MongoClient, ASCENDING
from flask import Flask
from threading import Thread
import os, re, asyncio, random, string
from datetime import datetime

# Configs
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
users_col = db["users"]
verify_col = db["verify"]

movies_col.create_index([("title", ASCENDING)])
movies_col.create_index("message_id")

# Flask app for uptime
flask_app = Flask(__name__)
@flask_app.route("/")
def home(): return "Bot is running!"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

# Utils
def clean_text(text): return re.sub(r"[^a-zA-Z0-9]", "", text.lower())
def extract_year(text): match = re.search(r"(19|20)\\d{2}", text); return match.group() if match else None
def extract_language(text): langs = ["Bengali", "Hindi", "English"]; return next((l for l in langs if l.lower() in text.lower()), "Unknown")
def generate_code(): return ''.join(random.choices(string.digits, k=4))

# CAPTCHA
@app.on_message(filters.private & filters.command("start"))
async def start_cmd(_, msg: Message):
    user_id = msg.from_user.id
    if not users_col.find_one({"_id": user_id}):
        code = generate_code()
        verify_col.update_one({"_id": user_id}, {"$set": {"code": code}}, upsert=True)
        await msg.reply(f"Please verify you are human.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(code, callback_data=f"verify_{code}")]]))
    else:
        await msg.reply("Welcome back! Send movie name to search.")

@app.on_callback_query(filters.regex("^verify_"))
async def verify_user(_, cq: CallbackQuery):
    code = cq.data.split("_", 1)[1]
    user_id = cq.from_user.id
    doc = verify_col.find_one({"_id": user_id})
    if doc and doc.get("code") == code:
        users_col.insert_one({"_id": user_id, "joined": datetime.utcnow()})
        verify_col.delete_one({"_id": user_id})
        await cq.message.edit("Verified! Now you can search movies.")
    else:
        await cq.answer("Wrong or expired code.", show_alert=True)

# Save movies from channel
@app.on_message(filters.chat(CHANNEL_ID))
async def save(_, msg):
    text = msg.text or msg.caption
    if not text: return
    movie = {
        "message_id": msg.id,
        "title": text,
        "date": msg.date,
        "year": extract_year(text),
        "language": extract_language(text),
        "downloads": 0
    }
    movies_col.update_one({"message_id": msg.id}, {"$set": movie}, upsert=True)

# Search command (inline or text)
@app.on_message(filters.private & filters.text)
async def search(_, msg):
    query = clean_text(msg.text)
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1}))
    exact = [m for m in all_movies if clean_text(m["title"]) == query]
    if exact:
        for m in exact:
            fwd = await app.forward_messages(msg.chat.id, CHANNEL_ID, m["message_id"])
            await movies_col.update_one({"message_id": m["message_id"]}, {"$inc": {"downloads": 1}})
        return
    # Fuzzy match
    suggestions = [m for m in all_movies if query in clean_text(m["title"])]
    if suggestions:
        buttons = [[InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")] for m in suggestions[:10]]
        await msg.reply("Select your movie:", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await msg.reply("Not found. Try again or use /feedback")

@app.on_callback_query(filters.regex("^movie_"))
async def send_movie(_, cq):
    mid = int(cq.data.split("_", 1)[1])
    fwd = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
    await movies_col.update_one({"message_id": mid}, {"$inc": {"downloads": 1}})
    await cq.answer("Sent!")

@app.on_inline_query()
async def inline_search(_, iq: InlineQuery):
    query = clean_text(iq.query)
    results = []
    for m in movies_col.find():
        if query in clean_text(m["title"]):
            results.append(
                InlineQueryResultArticle(
                    title=m["title"][:50],
                    input_message_content=InputTextMessageContent(f"{m['title']}", disable_web_page_preview=True)
                )
            )
    await iq.answer(results[:30], cache_time=3)

# Admin stats
@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg):
    await msg.reply(f"Users: {users_col.count_documents({})}\nMovies: {movies_col.count_documents({})}")

if __name__ == "__main__":
    print("Bot running...")
    app.run()
