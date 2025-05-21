# Updated movie bot with features 1, 2, 4, and 7

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from pymongo import MongoClient, ASCENDING
from flask import Flask
from threading import Thread
import os
import re
from datetime import datetime
import asyncio
import urllib.parse
from uuid import uuid4
from rapidfuzz import fuzz

# Configs
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# MongoDB setup
mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
stats_col = db["stats"]
users_col = db["users"]
requests_col = db["requests"]

# Index
movies_col.create_index([("title", ASCENDING)])

# Flask
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Bot is running!"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

# Helpers
def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

def fuzzy_search(query, movies):
    return sorted(
        movies,
        key=lambda m: fuzz.partial_ratio(query, m['title']),
        reverse=True
    )

async def delete_message_later(chat_id, message_id, delay=600):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except:
        pass

@app.on_message(filters.text & filters.private)
async def search(_, msg: Message):
    raw_query = msg.text.strip()
    query = clean_text(raw_query)
    users_col.update_one({"_id": msg.from_user.id}, {"$set": {"last_search": datetime.utcnow()}}, upsert=True)

    loading = await msg.reply("Searching... please wait")
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1}))
    matches = fuzzy_search(query, all_movies)[:RESULTS_COUNT]

    if matches:
        page_data = [matches[i:i+5] for i in range(0, len(matches), 5)]
        buttons = [[InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")] for m in page_data[0]]
        if len(page_data) > 1:
            buttons.append([InlineKeyboardButton("Next ➔", callback_data=f"page_1_{query}")])
        m = await msg.reply("Select a movie:", reply_markup=InlineKeyboardMarkup(buttons))
        asyncio.create_task(delete_message_later(m.chat.id, m.id))
    else:
        await loading.delete()
        google_button = InlineKeyboardMarkup([[InlineKeyboardButton("Search on Google", url="https://www.google.com/search?q=" + urllib.parse.quote(raw_query))]])
        alert = await msg.reply("No results found. Click below to search on Google.", reply_markup=google_button)
        asyncio.create_task(delete_message_later(alert.chat.id, alert.id))
        for admin_id in ADMIN_IDS:
            await app.send_message(admin_id, f"User `{msg.from_user.id}` searched for: **{raw_query}** (No result)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Add to Request", callback_data=f"req_{msg.from_user.id}_{raw_query}")]]))

@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data

    if data.startswith("movie_"):
        mid = int(data.split("_", 1)[1])
        fwd = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
        stats_col.update_one({"movie_id": mid}, {"$inc": {"count": 1}}, upsert=True)
        await cq.answer("Movie sent.")
        asyncio.create_task(delete_message_later(cq.message.chat.id, fwd.id))

    elif data.startswith("page_"):
        _, page, query = data.split("_", 2)
        page = int(page)
        all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1}))
        matches = fuzzy_search(clean_text(query), all_movies)
        page_data = [matches[i:i+5] for i in range(0, len(matches), 5)]
        if page < len(page_data):
            buttons = [[InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")] for m in page_data[page]]
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"page_{page-1}_{query}"))
            if page + 1 < len(page_data):
                nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}_{query}"))
            if nav_buttons:
                buttons.append(nav_buttons)
            await cq.message.edit_text(f"Page {page + 1} Results:", reply_markup=InlineKeyboardMarkup(buttons))
        await cq.answer()

    elif data.startswith("req_"):
        _, uid, q = data.split("_", 2)
        uid = int(uid)
        requests_col.insert_one({"user_id": uid, "query": q, "time": datetime.utcnow(), "admin": cq.from_user.id})
        m = await app.send_message(uid, f"Your request for **{q}** has been added. We will try to upload soon.")
        asyncio.create_task(delete_message_later(m.chat.id, m.id))
        await cq.answer("Request saved.")

@app.on_inline_query()
async def inline_query_handler(_, iq: InlineQuery):
    query = clean_text(iq.query.strip())
    if not query:
        return
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1}))
    matches = fuzzy_search(query, all_movies)[:10]
    results = [
        InlineQueryResultArticle(
            title=m["title"],
            input_message_content=InputTextMessageContent(f"{m['title']}")
        ) for m in matches
    ]
    await iq.answer(results, cache_time=1)

if __name__ == "__main__":
    print("Bot is starting...")
    app.run()
