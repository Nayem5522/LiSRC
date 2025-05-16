import re
import asyncio
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pymongo import MongoClient

# ==== CONFIGURATION ====
BOT_TOKEN = "YOUR_BOT_TOKEN"
API_ID = 1234567
API_HASH = "your_api_hash"
ADMIN_IDS = [123456789]  # Your Telegram user ID(s)
MONGO_URI = "your_mongodb_uri"
DB_NAME = "movie_bot"

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

mongo = MongoClient(MONGO_URI)
db = mongo[DB_NAME]
movies_col = db.movies
users_col = db.users
ratings_col = db.ratings
feedback_col = db.feedback
stats_col = db.stats
settings_col = db.settings  # For global notification on/off etc.

RESULTS_LIMIT = 10

# Helper: Auto delete message after seconds
async def auto_delete_after(message: Message, seconds: int):
    await asyncio.sleep(seconds)
    try:
        await message.delete()
    except:
        pass

# Start command
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    text = ("Welcome to MovieBot!\n"
            "Send me a movie name to search.\n"
            "/favorites - Show your favorite movies\n"
            "/mystats - Your usage stats\n"
            "/notify - Toggle new movie notifications\n")
    await message.reply(text)

# Search movies with language filter buttons
@app.on_message(filters.private & ~filters.command)
async def search_movie(client, message: Message):
    query = message.text.strip()
    if not query:
        return await message.reply("Please send a movie name.")

    # Save user search count
    stats_col.update_one({"_id": message.from_user.id}, {"$inc": {"search_count": 1}}, upsert=True)

    # Regex search
    regex = re.compile(re.escape(query), re.IGNORECASE)
    results = list(movies_col.find({"title": regex}).limit(RESULTS_LIMIT))

    if not results:
        # Notify admin about no results (optional)
        await message.reply(f"No movies found for '{query}'.")
        return

    # Build language filter buttons
    langs = ["Bengali", "Hindi", "English"]
    lang_buttons = [[InlineKeyboardButton(lang, callback_data=f"langfilter|{lang}|{query}")] for lang in langs]

    # First movie buttons (favorite, rate)
    first_movie = results[0]
    movie_buttons = [
        [InlineKeyboardButton("Add to Favorites", callback_data=f"fav|{first_movie['message_id']}")],
        [InlineKeyboardButton("Rate 👍/👎", callback_data=f"rate|{first_movie['message_id']}")]
    ]

    buttons = lang_buttons + movie_buttons
    markup = InlineKeyboardMarkup(buttons)

    # Reply with top 5 results
    text = f"Found {len(results)} results for '{query}':\n\n"
    for i, movie in enumerate(results[:5], 1):
        text += f"{i}. {movie['title']} ({movie.get('year', 'Unknown')}) [{movie.get('language', 'Unknown')}]\n"

    sent_msg = await message.reply(text, reply_markup=markup)
    # Auto delete reply after 5 minutes
    asyncio.create_task(auto_delete_after(sent_msg, 300))

# Callback query handler
@app.on_callback_query()
async def callback_handler(client, cq: CallbackQuery):
    data = cq.data
    user_id = cq.from_user.id

    if data.startswith("langfilter"):
        _, lang, original_query = data.split("|")
        regex = re.compile(re.escape(original_query), re.IGNORECASE)
        filtered = list(movies_col.find({"title": regex, "language": lang}).limit(RESULTS_LIMIT))
        if not filtered:
            await cq.answer(f"No results in {lang}.", show_alert=True)
            return
        text = f"Results for '{original_query}' in {lang}:\n"
        for i, movie in enumerate(filtered[:5], 1):
            text += f"{i}. {movie['title']} ({movie.get('year', 'Unknown')})\n"
        await cq.message.edit_text(text)
        await cq.answer()

    elif data.startswith("fav"):
        _, mid = data.split("|")
        mid = int(mid)
        users_col.update_one({"_id": user_id}, {"$addToSet": {"favorites": mid}}, upsert=True)
        await cq.answer("Added to favorites!")

    elif data.startswith("rate"):
        _, mid = data.split("|")
        mid = int(mid)
        # Send rating options
        rating_buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("1⭐", callback_data=f"rate_val|{mid}|1"),
             InlineKeyboardButton("2⭐", callback_data=f"rate_val|{mid}|2"),
             InlineKeyboardButton("3⭐", callback_data=f"rate_val|{mid}|3"),
             InlineKeyboardButton("4⭐", callback_data=f"rate_val|{mid}|4"),
             InlineKeyboardButton("5⭐", callback_data=f"rate_val|{mid}|5")]
        ])
        await cq.message.reply("Please rate the movie:", reply_markup=rating_buttons)
        await cq.answer()

    elif data.startswith("rate_val"):
        _, mid, rating = data.split("|")
        mid = int(mid)
        rating = int(rating)
        ratings_col.update_one(
            {"movie_id": mid, "user_id": user_id},
            {"$set": {"rating": rating, "timestamp": datetime.utcnow()}},
            upsert=True
        )
        await cq.answer(f"Thanks for rating {rating} stars!")

    elif data == "toggle_notify":
        user = users_col.find_one({"_id": user_id}) or {}
        current = user.get("notify", True)
        users_col.update_one({"_id": user_id}, {"$set": {"notify": not current}}, upsert=True)
        await cq.answer("Notification toggled.")

# Show favorite movies
@app.on_message(filters.command("favorites") & filters.private)
async def show_favorites(client, message: Message):
    user = users_col.find_one({"_id": message.from_user.id})
    favs = user.get("favorites", []) if user else []
    if not favs:
        return await message.reply("You have no favorite movies.")

    movies = movies_col.find({"message_id": {"$in": favs}})
    text = "Your Favorite Movies:\n"
    for movie in movies:
        text += f"- {movie['title']} ({movie.get('year', 'Unknown')})\n"

    await message.reply(text)

# User stats
@app.on_message(filters.command("mystats") & filters.private)
async def user_stats(client, message: Message):
    user_id = message.from_user.id
    stats = stats_col.find_one({"_id": user_id}) or {}
    searches = stats.get("search_count", 0)
    user = users_col.find_one({"_id": user_id}) or {}
    favorites = len(user.get("favorites", []))
    await message.reply(f"Your stats:\nSearches: {searches}\nFavorites: {favorites}")

# Feedback command
@app.on_message(filters.command("feedback") & filters.private)
async def user_feedback(client, message: Message):
    text = message.text.split(None, 1)
    if len(text) < 2:
        return await message.reply("Please provide feedback text.")
    feedback_text = text[1]
    feedback_col.insert_one({
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "feedback": feedback_text,
        "time": datetime.utcnow(),
        "reply": None,
        "reply_time": None
    })
    await message.reply("Thanks for your feedback!")

# Admin reply feedback
@app.on_message(filters.command("replyfeedback") & filters.user(ADMIN_IDS))
async def admin_reply_feedback(client, message: Message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply("Use: /replyfeedback <feedback_id> <reply_text>")
    fid = args[1]
    reply_text = args[2]
    try:
        fid = feedback_col.find_one({"_id": fid})
        if not fid:
            return await message.reply("Feedback not found.")
        feedback_col.update_one({"_id": fid["_id"]}, {"$set": {"reply": reply_text, "reply_time": datetime.utcnow()}})
        await message.reply("Reply saved.")
    except Exception as e:
        await message.reply(f"Error: {e}")

# Admin delete movie
@app.on_message(filters.command("delmovie") & filters.user(ADMIN_IDS))
async def admin_delete_movie(client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply("Use: /delmovie <message_id>")
    mid = int(args[1])
    res = movies_col.delete_one({"message_id": mid})
    if res.deleted_count:
        await message.reply(f"Deleted movie with id {mid}")
    else:
        await message.reply("Movie not found.")

# Admin update movie
@app.on_message(filters.command("updatemovie") & filters.user(ADMIN_IDS))
async def admin_update_movie(client, message: Message):
    args = message.text.split(None, 2)
    if len(args) < 3:
        return await message.reply("Use: /updatemovie <message_id> <new_title>")
    mid = int(args[1])
    new_title = args[2]
    res = movies_col.update_one({"message_id": mid}, {"$set": {"title": new_title}})
    if res.modified_count:
        await message.reply(f"Movie updated to '{new_title}'")
        # Notify users if global notify enabled
        setting = settings_col.find_one({"key": "global_notify"})
        if setting and setting.get("value", True):
            await broadcast_message(client, f"Movie updated: {new_title}")
    else:
        await message.reply("Update failed or no change.")

# Broadcast command with optional photo
@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def admin_broadcast(client, message: Message):
    args = message.text.split(None, 2)
    if len(args) < 2:
        return await message.reply("Use: /broadcast <text or photo_url> [caption]")
    content = args[1]
    caption = args[2] if len(args) > 2 else None

    users = users_col.find({"notify": True})
    count = 0
    for u in users:
        try:
            if content.startswith("http") and (content.endswith(".jpg") or content.endswith(".png") or content.endswith(".jpeg")):
                await client.send_photo(u["_id"], content, caption=caption)
            else:
                await client.send_message(u["_id"], content)
            count += 1
        except:
            continue
    await message.reply(f"Broadcast sent to {count} users.")

# Toggle notification setting
@app.on_message(filters.command("notify") & filters.private)
async def toggle_notify_cmd(client, message: Message):
    user = users_col.find_one({"_id": message.from_user.id}) or {}
    current = user.get("notify", True)
    users_col.update_one({"_id": message.from_user.id}, {"$set": {"notify": not current}}, upsert=True)
    await message.reply(f"Notification {'enabled' if not current else 'disabled'}.")

# Auto-delete any bot replies except movies after 5 minutes
@app.on_message(filters.private & filters.incoming)
async def auto_delete_replies(client, message: Message):
    if message.from_user.is_bot:
        # Assuming movie messages have "movie" in text or other checks
        if "movie" not in (message.text or "").lower():
            asyncio.create_task(auto_delete_after(message, 300))

# Broadcast helper
async def broadcast_message(client, text):
    users = users_col.find({"notify": True})
    for u in users:
        try:
            await client.send_message(u["_id"], text)
        except:
            continue

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
