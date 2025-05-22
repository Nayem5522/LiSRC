# telegram_movie_bot_web.py

import os
import asyncio
import logging
from datetime import datetime, timedelta
from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient
from fuzzywuzzy import process
import random

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot config
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMINS", "").split()]
DB_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "movie_bot")
LOG_CHANNEL = int(os.getenv("LOG_CHANNEL", 0))
MOVIE_CHANNEL = os.getenv("MOVIE_CHANNEL")
AUTO_DELETE_TIME = int(os.getenv("AUTO_DELETE_TIME", 10))

# Flask app for web service
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

# Pyrogram bot
bot = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = MongoClient(DB_URI)
db = mongo[DB_NAME]
users_col = db.users
movies_col = db.movies
feedback_col = db.feedback

# Helper Functions
async def add_user(user):
    if not users_col.find_one({"_id": user.id}):
        users_col.insert_one({
            "_id": user.id,
            "name": user.first_name,
            "joined": datetime.utcnow(),
            "notify": True
        })

async def get_movies():
    return [x['title'] for x in movies_col.find()]

async def get_movie_data(title):
    return movies_col.find_one({"title": title})

async def delete_message_later(chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_messages(chat_id, message_id)
    except:
        pass

captcha_answers = {}

@bot.on_message(filters.private & filters.command("start"))
async def start_handler(client, message):
    await add_user(message.from_user)
    if message.from_user.id not in captcha_answers:
        a, b = random.randint(1, 10), random.randint(1, 10)
        captcha_answers[message.from_user.id] = a + b
        await message.reply(
            f"Welcome, {message.from_user.first_name}!\nPlease solve: {a} + {b} = ?",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Verify", callback_data="verify_captcha")]]
            )
        )
    else:
        await message.reply("You're already verified. Send movie name to search.")

@bot.on_callback_query(filters.regex("verify_captcha"))
async def verify_captcha(client, query: CallbackQuery):
    user_id = query.from_user.id
    answer = captcha_answers.get(user_id)
    if answer:
        await query.message.reply("Send the correct answer as a message.")

@bot.on_message(filters.private & filters.text)
async def captcha_check(client, message):
    user_id = message.from_user.id
    if user_id in captcha_answers:
        try:
            if int(message.text.strip()) == captcha_answers[user_id]:
                del captcha_answers[user_id]
                await message.reply("✅ Verified! Now you can search movies.")
            else:
                await message.reply("❌ Wrong answer. Try /start again.")
        except:
            await message.reply("Please send a number as answer.")
        return

    query = message.text.strip()
    all_movies = await get_movies()
    results = process.extract(query, all_movies, limit=10)
    if not results:
        await message.reply("No movies found.")
        return

    buttons = [
        [InlineKeyboardButton(f"{title} ({score}%)", callback_data=f"movie_{title}")]
        for title, score in results
    ]
    msg = await message.reply(
        "Select the movie:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    asyncio.create_task(delete_message_later(msg.chat.id, msg.id, AUTO_DELETE_TIME * 60))

@bot.on_callback_query(filters.regex("movie_"))
async def movie_callback(client, query: CallbackQuery):
    title = query.data.replace("movie_", "")
    data = await get_movie_data(title)
    if not data:
        await query.answer("Movie not found.", show_alert=True)
        return
    caption = f"**{data['title']}**\n{data.get('description', 'No description.')}"
    btns = [[InlineKeyboardButton("Watch Now", url=data['link'])]]
    msg = await query.message.reply_photo(
        photo=data.get("photo", "https://placehold.co/600x400?text=Movie"),
        caption=caption,
        reply_markup=InlineKeyboardMarkup(btns)
    )
    asyncio.create_task(delete_message_later(msg.chat.id, msg.id, AUTO_DELETE_TIME * 60))

@bot.on_message(filters.command("myinfo") & filters.private)
async def myinfo_handler(_, m):
    user = users_col.find_one({"_id": m.from_user.id})
    if not user:
        return await m.reply("You're not in database.")
    await m.reply(
        f"**User Info**\nID: `{user['_id']}`\nName: `{user['name']}`\nJoined: `{user['joined']}`\nNotify: `{user['notify']}`"
    )

@bot.on_message(filters.command("panel") & filters.user(ADMIN_IDS))
async def panel_handler(_, m):
    user_count = users_col.count_documents({})
    movie_count = movies_col.count_documents({})
    await m.reply(
        f"**Admin Panel**\nTotal Users: `{user_count}`\nTotal Movies: `{movie_count}`",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Broadcast", callback_data="admin_broadcast")],
            [InlineKeyboardButton("Feedback", callback_data="admin_feedback")]
        ])
    )

@bot.on_callback_query(filters.regex("admin_feedback"))
async def feedback_handler(_, q):
    feedbacks = list(feedback_col.find().sort("_id", -1).limit(10))
    if not feedbacks:
        return await q.message.reply("No feedbacks yet.")
    text = "\n\n".join([f"**{x['user']}**: {x['text']}" for x in feedbacks])
    await q.message.reply(text)

@bot.on_message(filters.command("feedback") & filters.private)
async def feedback(_, m):
    fb = m.text.split(" ", 1)
    if len(fb) < 2:
        return await m.reply("Send your feedback like: /feedback great bot!")
    feedback_col.insert_one({"user": m.from_user.first_name, "text": fb[1]})
    await m.reply("Thanks for your feedback!")

# Start both Flask and Pyrogram
if __name__ == "__main__":
    import threading

    threading.Thread(target=bot.run).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
