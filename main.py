import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from pymongo import MongoClient
from flask import Flask
from threading import Thread

# Configs
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("DATABASE_URL")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))

RESULTS_COUNT = 5

app = Client("movie-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
db = MongoClient(MONGO_URL)["movie_bot"]
movies_col = db["movies"]
feedback_col = db["feedback"]
usage_col = db["usage"]

# Web server for Render
flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "Bot is running!"

def run_web():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

Thread(target=run_web).start()

# Save new messages from channel
@app.on_message(filters.channel & filters.chat(CHANNEL_ID))
async def save_channel_message(client, message):
    title = message.caption or message.text
    if not title:
        return
    movies_col.insert_one({
        "title": title,
        "message_id": message.message_id,
        "language": "Bengali" if "Bengali" in title else "Hindi" if "Hindi" in title else "English"
    })

# Start command
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply("Welcome to the Movie Bot! Send me a movie name to search.")

# Search handler
@app.on_message(filters.text & ~filters.private)
async def ignore_group(client, message):
    await message.reply("Please message me in private.")

@app.on_message(filters.private & filters.text & ~filters.command(["start", "stats", "broadcast"]))
async def search_movie(client, message):
    query = message.text
    usage_col.update_one({"user_id": message.from_user.id}, {"$inc": {"count": 1}}, upsert=True)

    query_regex = {"$regex": query, "$options": "i"}
    results = list(movies_col.find({"title": query_regex}, {"title": 1, "message_id": 1, "language": 1}))

    if results:
        buttons = [[InlineKeyboardButton(res["title"][:40], callback_data=f"movie_{res['message_id']}")] for res in results[:RESULTS_COUNT]]
        lang_buttons = [
            InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{query}"),
            InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{query}"),
            InlineKeyboardButton("English", callback_data=f"lang_English_{query}")
        ]
        buttons.append(lang_buttons)
        await message.reply("Search results:", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await message.reply("No results found.")
        for admin_id in ADMIN_IDS:
            try:
                await client.send_message(admin_id, f"No results for: {query}")
            except:
                pass

# Callback query handler
@app.on_callback_query()
async def handle_callback(client, cq):
    data = cq.data

    if data.startswith("movie_"):
        msg_id = int(data.split("_")[1])
        try:
            await client.copy_message(chat_id=cq.message.chat.id, from_chat_id=CHANNEL_ID, message_id=msg_id)
        except:
            await cq.message.reply("Couldn't forward the movie.")
        await cq.answer()

    elif data.startswith("lang_"):
        _, lang, query = data.split("_", 2)
        query_regex = {"$regex": query, "$options": "i"}
        filtered_movies = list(movies_col.find({"language": lang, "title": query_regex}, {"title": 1, "message_id": 1}))

        if filtered_movies:
            buttons = [[InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")] for m in filtered_movies[:RESULTS_COUNT]]
            await cq.message.edit_text(f"ফলাফল '{lang}' ভাষায়:", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await cq.message.edit_text("এই ভাষায় কিছুই পাওয়া যায়নি।")
        await cq.answer()

# Broadcast command
@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(client, message):
    if not message.reply_to_message:
        await message.reply("Reply to a message to broadcast.")
        return

    users = usage_col.find()
    count = 0
    for user in users:
        try:
            await message.reply_to_message.copy(user["user_id"])
            count += 1
        except:
            pass
    await message.reply(f"Broadcast sent to {count} users.")

# Stats command
@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(client, message):
    total_users = usage_col.count_documents({})
    total_movies = movies_col.count_documents({})
    total_feedback = feedback_col.count_documents({})
    await message.reply(f"Users: {total_users}\nMovies: {total_movies}\nFeedback: {total_feedback}")

# Feedback
@app.on_message(filters.command("feedback"))
async def feedback(client, message):
    if len(message.command) < 2:
        await message.reply("Usage: /feedback [your message]")
        return
    feedback_col.insert_one({
        "user_id": message.from_user.id,
        "message": message.text.split(None, 1)[1]
    })
    await message.reply("Thanks for your feedback!")

# Run bot
app.run()
