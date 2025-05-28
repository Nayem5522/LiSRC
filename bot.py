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
users_col = db["users"]
subscribers_col = db["subscribers"]

movies_col.create_index([("title", ASCENDING)])
movies_col.create_index("message_id")
movies_col.create_index("language")

# Flask app for uptime
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Bot is running!"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

# Helpers
def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

async def delete_message_later(chat_id, message_id, delay=600):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except:
        pass

async def notify_subscribers(movie_title):
    subscribers = subscribers_col.find()
    for subscriber in subscribers:
        await app.send_message(subscriber["user_id"], f"🎬 নতুন মুভি পোস্ট হয়েছে: {movie_title}\n\n{UPDATE_CHANNEL}")

# Auto save new movie when posted in channel
@app.on_message(filters.channel & filters.text)
async def save_movie(client, message):
    movie_title = message.text.splitlines()[0]  # First line is the movie title
    movie_language = "Unknown"  # You can implement language detection or make it dynamic later

    movie_data = {
        "title": movie_title,
        "message_id": message.message_id,
        "language": movie_language,
        "posted_at": datetime.utcnow(),
    }
    
    # Save to MongoDB
    movies_col.insert_one(movie_data)

    # Notify all subscribers
    await notify_subscribers(movie_title)

# Search Handler with Fuzzy Matching
@app.on_message(filters.private & filters.text)
async def search_handler(client, message):
    query_raw = message.text.strip()
    query_clean = clean_text(query_raw)
    
    # Log or update user's last search
    users_col.update_one(
        {"_id": message.from_user.id},
        {"$set": {"last_search": datetime.utcnow()}},
        upsert=True
    )

    loading_msg = await message.reply("🔎 লোড হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")
    
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1, "language": 1}))
    
    # 1. Check exact match
    exact_matches = [m for m in all_movies if clean_text(m.get("title", "")) == query_clean]
    if exact_matches:
        await loading_msg.delete()
        for m in exact_matches[:RESULTS_COUNT]:
            fwd_msg = await app.forward_messages(message.chat.id, CHANNEL_ID, m["message_id"])
            await message.reply(f"🎬 আপনার জন্য পাওয়া গেছে: {m['title']}\n\n⚠️ মেসেজটি ১০ মিনিট পরে অটো ডিলিট হবে।")
            asyncio.create_task(delete_message_later(message.chat.id, fwd_msg.id))
            await asyncio.sleep(0.7)
        return
    
    # 2. Fuzzy matching suggestions
    choices = {m["title"]: m for m in all_movies}
    fuzzy_results = process.extract(query_raw, choices.keys(), scorer=fuzz.partial_ratio, limit=RESULTS_COUNT)
    
    # Filter results above threshold (70)
    filtered_suggestions = [choices[title] for title, score, _ in fuzzy_results if score >= 70]

    if filtered_suggestions:
        await loading_msg.delete()
        buttons = [
            [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")] for m in filtered_suggestions
        ]
        # Add language filter buttons
        lang_buttons = [
            InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{query_raw}"),
            InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{query_raw}"),
            InlineKeyboardButton("English", callback_data=f"lang_English_{query_raw}")
        ]
        buttons.append(lang_buttons)
        
        await message.reply(
            "আপনার মুভির নামের সাথে মিল পাওয়া গেছে, নিচের থেকে সিলেক্ট করুন:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return
    
    await loading_msg.edit("দুঃখিত, কোনো ফলাফল পাওয়া যায়নি। দয়া করে সঠিক নাম লিখুন অথবা পরে আবার চেষ্টা করুন।")

# Callback handler for buttons
@app.on_callback_query()
async def callback_handler(client, callback_query):
    data = callback_query.data

    if data.startswith("movie_"):
        msg_id = int(data.split("_")[1])
        # Forward the movie message from channel to user
        fwd_msg = await app.forward_messages(callback_query.message.chat.id, CHANNEL_ID, msg_id)
        await callback_query.answer("মুভি পাঠানো হয়েছে!")
        asyncio.create_task(delete_message_later(callback_query.message.chat.id, fwd_msg.id))

    elif data.startswith("lang_"):
        parts = data.split("_")
        lang = parts[1]
        query = "_".join(parts[2:])
        
        # Filter movies by language & query
        lang_movies = list(movies_col.find(
            {"language": lang},
            {"title": 1, "message_id": 1}
        ))

        # Fuzzy match within filtered language movies
        choices = {m["title"]: m for m in lang_movies}
        fuzzy_results = process.extract(query, choices.keys(), scorer=fuzz.partial_ratio, limit=RESULTS_COUNT)
        filtered = [choices[title] for title, score, _ in fuzzy_results if score >= 70]

        if filtered:
            buttons = [
                [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")] for m in filtered
            ]
            await callback_query.message.edit_text(
                f"ভাষা: {lang} এর জন্য ফলাফল:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await callback_query.answer("দুঃখিত, এই ভাষায় কোনো মিল পাওয়া যায়নি।", show_alert=True)

# Subscription System
@app.on_message(filters.command("subscribe") & filters.private)
async def subscribe(client, message):
    user_id = message.from_user.id
    if not subscribers_col.find_one({"user_id": user_id}):
        subscribers_col.insert_one({"user_id": user_id})
        await message.reply("আপনি সফলভাবে সাবস্ক্রাইব করেছেন। এখন থেকে নতুন মুভি পোস্ট হলে আপনাকে নোটিফাই করা হবে।")
    else:
        await message.reply("আপনি ইতিমধ্যে সাবস্ক্রাইব করেছেন।")

@app.on_message(filters.command("unsubscribe") & filters.private)
async def unsubscribe(client, message):
    user_id = message.from_user.id
    subscribers_col.delete_one({"user_id": user_id})
    await message.reply("আপনি সফলভাবে আনসাবস্ক্রাইব করেছেন। নতুন মুভি নোটিফিকেশন আর পাবেন না।")

# Stats Command
@app.on_message(filters.command("stats") & filters.private)
async def stats(client, message):
    user_count = users_col.count_documents({})
    subscriber_count = subscribers_col.count_documents({})
    movie_count = movies_col.count_documents({})
    
    stats_message = (
        f"সর্বমোট ইউজার: {user_count}\n"
        f"সাবস্ক্রাইবার: {subscriber_count}\n"
        f"মুভির সংখ্যা: {movie_count}"
    )
    await message.reply(stats_message)

# Start command
@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    text = (
        f"হ্যালো {message.from_user.first_name}!\n"
        "আমি তোমার মুভি সার্চ বট।\n"
        "তুমি শুধু মুভির নাম পাঠাও, আমি তোমাকে খুঁজে দিব।\n"
        f"আপডেট পেতে: {UPDATE_CHANNEL}"
    )
    await message.reply(text)

# Run the bot
app.run()
