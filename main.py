from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient
import asyncio
import os
import re
from datetime import datetime

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS","").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
users_col = db["users"]
feedback_col = db["feedback"]
settings_col = db["settings"]

# --- Utilities ---
def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

async def delete_message_later(chat_id, message_id, delay=600):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except:
        pass

# --- Start handler ---
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    # Add user to DB
    users_col.update_one({"_id": message.from_user.id}, {"$set": {"joined": datetime.utcnow(), "notify": True}}, upsert=True)
    buttons = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Update Channel", url="https://t.me/CTGMovieOfficial")],
         [InlineKeyboardButton("Contact Admin", url="https://t.me/ctgmovies23")]]
    )
    await message.reply("Welcome! Send me a movie name to search.", reply_markup=buttons)

# --- Movie saving (from channel posts) ---
@app.on_message(filters.chat(CHANNEL_ID))
async def save_movie_post(client, message):
    text = message.text or message.caption
    if not text:
        return
    movie_data = {
        "message_id": message.id,
        "title": text,
        "date": message.date,
        "language": "Unknown",  # optionally extract language
    }
    movies_col.update_one({"message_id": message.id}, {"$set": movie_data}, upsert=True)

# --- Search ---
@app.on_message(filters.text & ~filters.command)
async def search_movies(client, message):
    query = message.text.strip()
    cleaned = clean_text(query)

    # Search exact match first
    movie = movies_col.find_one({"title": {"$regex": re.escape(query), "$options": "i"}})
    if movie:
        await client.forward_messages(message.chat.id, CHANNEL_ID, movie["message_id"])
        return

    # Fuzzy / partial matches
    matches = list(movies_col.find({"title": {"$regex": query, "$options": "i"}}).limit(10))
    if matches:
        buttons = [
            [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")]
            for m in matches
        ]
        await message.reply("Found multiple matches, select one:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    # No results found - notify admin & suggest Google search
    google_url = "https://www.google.com/search?q=" + re.sub(" ", "+", query)
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Search on Google", url=google_url)]
    ])
    await message.reply("No movie found. You can try Google search.", reply_markup=buttons)

    # Notify admins with inline buttons to reply/request movie
    admin_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Exists", callback_data=f"admin_yes_{message.from_user.id}_{query}"),
            InlineKeyboardButton("❌ Not found", callback_data=f"admin_no_{message.from_user.id}_{query}")
        ],
        [
            InlineKeyboardButton("⏳ Coming Soon", callback_data=f"admin_soon_{message.from_user.id}_{query}"),
            InlineKeyboardButton("✏️ Wrong Name", callback_data=f"admin_wrong_{message.from_user.id}_{query}")
        ]
    ])
    for admin_id in ADMIN_IDS:
        await client.send_message(admin_id, f"User {message.from_user.first_name} requested movie: {query}", reply_markup=admin_buttons)

# --- Callback Query for movie selection and admin replies ---
@app.on_callback_query()
async def callback_handler(client, cq: CallbackQuery):
    data = cq.data
    if data.startswith("movie_"):
        message_id = int(data.split("_")[1])
        await client.forward_messages(cq.message.chat.id, CHANNEL_ID, message_id)
        await cq.answer("Here is your movie.")

    elif data.startswith("admin_"):
        # Admin feedback on movie requests
        parts = data.split("_")
        action = parts[1]
        user_id = int(parts[2])
        query = "_".join(parts[3:])
        if cq.from_user.id not in ADMIN_IDS:
            await cq.answer("You are not authorized.", show_alert=True)
            return
        reply_text = ""
        if action == "yes":
            reply_text = f"Admin says: Movie '{query}' is available."
        elif action == "no":
            reply_text = f"Admin says: Sorry, movie '{query}' is not found."
        elif action == "soon":
            reply_text = f"Admin says: Movie '{query}' will be available soon."
        elif action == "wrong":
            reply_text = f"Admin says: Please check the movie name again."

        try:
            await client.send_message(user_id, reply_text)
            await cq.answer("User notified.")
        except:
            await cq.answer("Failed to notify user.")

# --- Feedback ---
@app.on_message(filters.command("feedback"))
async def feedback_handler(client, message):
    text = message.text.split(None, 1)
    if len(text) < 2:
        await message.reply("Please write feedback after /feedback.")
        return
    feedback_col.insert_one({
        "user_id": message.from_user.id,
        "feedback": text[1],
        "time": datetime.utcnow()
    })
    await message.reply("Thanks for your feedback!")

# --- Admin commands: /broadcast, /stats, /deletemovie ---
@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(client, message):
    if len(message.command) < 2:
        await message.reply("Usage: /broadcast your message here")
        return
    text = message.text.split(None, 1)[1]
    count = 0
    for user in users_col.find():
        try:
            await client.send_message(user["_id"], text)
            count += 1
        except:
            continue
    await message.reply(f"Broadcast sent to {count} users.")

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(client, message):
    users_count = users_col.count_documents({})
    movies_count = movies_col.count_documents({})
    feedback_count = feedback_col.count_documents({})
    await message.reply(f"Users: {users_count}\nMovies: {movies_count}\nFeedback: {feedback_count}")

@app.on_message(filters.command("deletemovie") & filters.user(ADMIN_IDS))
async def deletemovie(client, message):
    if len(message.command) < 2:
        await message.reply("Usage: /deletemovie <message_id>")
        return
    try:
        msg_id = int(message.command[1])
    except ValueError:
        await message.reply("Provide a valid message ID.")
        return
    result = movies_col.delete_one({"message_id": msg_id})
    if result.deleted_count:
        await message.reply(f"Deleted movie with message_id {msg_id}.")
    else:
        await message.reply("No movie found with that ID.")

if __name__ == "__main__":
    app.run()
