from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, InlineQuery, InlineQueryResultArticle, InputTextMessageContent
)
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
search_log_col = db["search_logs"]

# Create indexes for faster queries
movies_col.create_index([("title", ASCENDING)])
movies_col.create_index("message_id")
movies_col.create_index("language")

# Flask keep-alive
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

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

async def delete_message_later(chat_id, message_id, delay=600):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except:
        pass

# Trending: update count for searched movie titles
def update_trending(title):
    key = clean_text(title)
    stats_col.update_one({"_id": key}, {"$inc": {"count": 1}}, upsert=True)

# Start command
@app.on_message(filters.command("start") & filters.private)
async def start_command(_, msg: Message):
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

# Help command
@app.on_message(filters.command("help") & filters.private)
async def help_command(_, msg: Message):
    help_text = (
        "📌 *Movie Bot Help*\n\n"
        "/start - Bot শুরু করুন\n"
        "/help - এই মেসেজ\n"
        "/feedback - মতামত দিন\n"
        "/mystats - আপনার সার্চ স্ট্যাটস\n"
        "/notify on|off - Global notification চালু/বন্ধ (Admin)\n"
        "/broadcast - Broadcast message পাঠান (Admin)\n"
        "/delete_movie <id> - মুভি ডিলিট করুন (Admin)\n"
        "/delete_all_movies - সব মুভি ডিলিট করুন (Admin)\n\n"
        "যে কোনো মুভির নাম পাঠালে সার্চ করবে।"
    )
    await msg.reply(help_text)

# Feedback command
@app.on_message(filters.command("feedback") & filters.private)
async def feedback_command(_, msg: Message):
    if len(msg.command) < 2:
        return await msg.reply("Please write something after /feedback.")
    feedback_col.insert_one({
        "user": msg.from_user.id,
        "text": msg.text.split(None, 1)[1],
        "time": datetime.utcnow()
    })
    m = await msg.reply("Thanks for your feedback!")
    asyncio.create_task(delete_message_later(m.chat.id, m.id))

# MyStats command: show user's own search stats
@app.on_message(filters.command("mystats") & filters.private)
async def mystats_command(_, msg: Message):
    user_id = msg.from_user.id
    stats = search_log_col.aggregate([
        {"$match": {"user_id": user_id}},
        {"$group": {"_id": "$query", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ])
    text = "🎯 আপনার শীর্ষ ১০ সার্চ:\n\n"
    count = 0
    for stat in stats:
        count += 1
        text += f"{count}. {stat['_id']} - {stat['count']} বার\n"
    if count == 0:
        text = "আপনি এখনো কিছু সার্চ করেননি।"
    await msg.reply(text)

# Notify command (admin only)
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

# Broadcast command (admin only)
@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast_command(_, msg: Message):
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

# Delete movie by message_id (admin only)
@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_movie_command(_, msg: Message):
    if len(msg.command) != 2:
        return await msg.reply("ব্যবহার: /delete_movie <movie_id>")
    try:
        movie_id = int(msg.command[1])
        result = movies_col.delete_one({"message_id": movie_id})
        if result.deleted_count:
            await msg.reply(f"✅ মুভি (ID: {movie_id}) ডিলিট করা হয়েছে।")
        else:
            await msg.reply("❌ এই ID-এর কোনো মুভি পাওয়া যায়নি।")
    except:
        await msg.reply("⚠️ Movie ID একটি সংখ্যা হওয়া প্রয়োজন।")

# Delete all movies (admin only)
@app.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_IDS))
async def delete_all_movies_command(_, msg: Message):
    result = movies_col.delete_many({})
    await msg.reply(f"🗑️ মোট {result.deleted_count} টি মুভি ডিলিট করা হয়েছে।")

# Save new posts from channel to DB and notify users if enabled
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
        for user in users_col.find():
            try:
                await app.send_message(user["_id"], f"New Movie Added:\n\n{text}")
            except:
                pass

# Search Handler (private chat)
@app.on_message(filters.private & filters.text)
async def search_handler(_, msg: Message):
    query = msg.text.strip()
    user_id = msg.from_user.id

    # Save user info
    users_col.update_one({"_id": user_id}, {"$set": {"last_seen": datetime.utcnow()}}, upsert=True)

    # Log search
    search_log_col.insert_one({"user_id": user_id, "query": query, "time": datetime.utcnow()})

    # Update trending stats
    update_trending(query)

    # Search priority: Exact -> Regex -> Fuzzy

    # 1. Exact match (case insensitive)
    exact_results = list(movies_col.find({"title": {"$regex": f"^{re.escape(query)}$", "$options": "i"}}).limit(RESULTS_COUNT))
    if exact_results:
        await send_search_results(msg, exact_results)
        return

    # 2. Regex suggestions (titles containing query anywhere)
    regex_results = list(movies_col.find({"title": {"$regex": re.escape(query), "$options": "i"}}).limit(RESULTS_COUNT))
    if regex_results:
        await send_search_results(msg, regex_results)
        return

    # 3. Fuzzy matching with similarity score threshold
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1}).limit(1000))  # limit for performance
    scored = []
    for movie in all_movies:
        score = similar(clean_text(query), clean_text(movie["title"]))
        if score > 0.6:  # threshold
            scored.append((score, movie))
    scored.sort(key=lambda x: x[0], reverse=True)
    fuzzy_results = [m[1] for m in scored[:RESULTS_COUNT]]

    if fuzzy_results:
        await send_search_results(msg, fuzzy_results)
        return

    # No results found - notify admins
    for admin_id in ADMIN_IDS:
        try:
            await app.send_message(admin_id, f"❗️ No results found for search query: `{query}`")
        except:
            pass
    await msg.reply("Sorry, no results found for your query.")

async def send_search_results(msg: Message, results):
    buttons = []
    text = "Search results:\n\n"
    for movie in results:
        # Each movie button opens the channel post
        buttons.append([InlineKeyboardButton(movie["title"], url=f"https://t.me/c/{str(CHANNEL_ID)[4:]}/{movie['message_id']}")])
        text += f"• {movie['title']}\n"
    await msg.reply(text, reply_markup=InlineKeyboardMarkup(buttons))

# Callback query handler placeholder (can be extended)
@app.on_callback_query()
async def callback_handler(_, query: CallbackQuery):
    await query.answer("Action not defined.")

# Inline query handler
@app.on_inline_query()
async def inline_query_handler(_, inline_query: InlineQuery):
    query = inline_query.query.strip()
    if not query:
        return

    # Find matching movies (regex + fuzzy)
    regex_results = list(movies_col.find({"title": {"$regex": re.escape(query), "$options": "i"}}).limit(RESULTS_COUNT))
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1}).limit(1000))
    scored = []
    for movie in all_movies:
        score = similar(clean_text(query), clean_text(movie["title"]))
        if score > 0.6:
            scored.append((score, movie))
    scored.sort(key=lambda x: x[0], reverse=True)
    fuzzy_results = [m[1] for m in scored[:RESULTS_COUNT]]

    combined = {m["message_id"]: m for m in regex_results}
    for m in fuzzy_results:
        combined[m["message_id"]] = m

    results = []
    for movie in list(combined.values())[:RESULTS_COUNT]:
        results.append(
            InlineQueryResultArticle(
                title=movie["title"],
                input_message_content=InputTextMessageContent(movie["title"]),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Watch Movie", url=f"https://t.me/c/{str(CHANNEL_ID)[4:]}/{movie['message_id']}")]]
                )
            )
        )
    await inline_query.answer(results, cache_time=10)

# Run the bot
app.run()
