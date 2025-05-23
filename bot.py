import os
import re
import asyncio
import urllib.parse
import logging
from datetime import datetime
from threading import Thread

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient, ASCENDING
from flask import Flask
from fuzzywuzzy import process # Added for fuzzy matching

# --- Configure Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- Configuration ---
# All essential bot configurations are loaded from environment variables.
# This makes the bot flexible and secure, as sensitive information isn't hardcoded.
try:
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    CHANNEL_ID = int(os.getenv("CHANNEL_ID")) # Channel where movies are posted
    RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10)) # Number of search results to show
    ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) # List of bot admin IDs
    DATABASE_URL = os.getenv("DATABASE_URL") # MongoDB connection URL
    UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial") # Link to update channel
    START_PIC = os.getenv("START_PIC", "https://i.ibb.co/prnGXMr/photo-2025-05-16-05-15-45-7504908428624527364.jpg") # Start message image
except Exception as e:
    logger.error(f"Failed to load environment variables. Please check your .env file or environment setup: {e}")
    exit(1) # Exit if essential environment variables are missing or incorrect

# --- Bot and Database Initialization ---
# Initialize the Pyrogram client for the bot.
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Initialize MongoDB client and collections.
# Data is stored in different collections for better organization.
try:
    mongo = MongoClient(DATABASE_URL)
    db = mongo["movie_bot"]
    movies_col = db["movies"] # Stores movie information
    feedback_col = db["feedback"] # Stores user feedback
    stats_col = db["stats"] # For bot statistics (though not fully utilized in this snippet)
    users_col = db["users"] # Stores user information
    settings_col = db["settings"] # Stores bot settings like global notifications

    # Create indexes for efficient data retrieval.
    # This significantly speeds up searches and other database operations.
    movies_col.create_index([("title", ASCENDING)])
    movies_col.create_index("message_id")
    movies_col.create_index("language")
    logger.info("MongoDB initialized and indexes created.")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB or create indexes: {e}")
    exit(1) # Exit if database connection fails

# --- Web Server (Flask) ---
# A simple Flask web server to keep the bot alive on platforms like Heroku.
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Bot is running!"

# Run the Flask app in a separate thread to not block the bot.
def run_flask_app():
    port = int(os.getenv("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

Thread(target=run_flask_app).start()
logger.info(f"Flask web server started on port {os.getenv('PORT', 8080)}")

# --- Helper Functions ---
# Utility functions to process text and manage messages.
def clean_text(text):
    """Removes non-alphanumeric characters and converts text to lowercase for consistent searching."""
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

def extract_year(text):
    """Extracts a four-digit year (19xx or 20xx) from the text."""
    match = re.search(r"(19|20)\d{2}", text)
    return match.group() if match else None

def extract_language(text):
    """Identifies movie language (Bengali, Hindi, English) from text."""
    langs = ["Bengali", "Hindi", "English"]
    for lang in langs:
        if re.search(r'\b' + re.escape(lang.lower()) + r'\b', text.lower()):
            return lang
    return "Unknown"

async def delete_message_later(chat_id, message_id, delay=600):
    """Deletes a message after a specified delay (default 10 minutes)."""
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
        logger.info(f"Deleted message {message_id} in chat {chat_id} after {delay} seconds.")
    except Exception as e:
        logger.warning(f"Failed to delete message {message_id} in chat {chat_id}: {e}")
        pass # Ignore errors if message is already deleted or inaccessible

# --- Message Handlers ---

@app.on_message(filters.chat(CHANNEL_ID))
async def save_post(_, msg: Message):
    """
    Automatically saves movie posts from the designated channel to the database.
    Also sends notifications to users if global notifications are enabled.
    """
    text = msg.text or msg.caption
    if not text:
        logger.info(f"Skipping non-text/non-caption message in channel {CHANNEL_ID}.")
        return
    
    movie = {
        "message_id": msg.id,
        "title": text,
        "date": msg.date,
        "year": extract_year(text),
        "language": extract_language(text)
    }
    
    try:
        movies_col.update_one({"message_id": msg.id}, {"$set": movie}, upsert=True)
        logger.info(f"Saved/Updated movie '{text.splitlines()[0]}' (ID: {msg.id}) from channel.")

        setting = settings_col.find_one({"key": "global_notify"})
        if setting and setting.get("value"):
            # Notify users about new movie uploads
            for user in users_col.find({"notify": {"$ne": False}}): # Exclude users who opted out
                try:
                    await app.send_message(
                        user["_id"],
                        f"নতুন মুভি আপলোড হয়েছে:\n{text.splitlines()[0][:100]}...\nএখনই সার্চ করে দেখুন!"
                    )
                    logger.debug(f"Notification sent to user {user['_id']}")
                except Exception as e:
                    logger.warning(f"Failed to send notification to user {user['_id']}: {e}")
                    pass # Ignore if user blocked bot
    except Exception as e:
        logger.error(f"Error saving movie or sending global notification: {e}")

@app.on_message(filters.command("start"))
async def start(_, msg: Message):
    """
    Handles the /start command, welcoming new users and providing initial options.
    Records user's join time in the database.
    """
    try:
        users_col.update_one(
            {"_id": msg.from_user.id},
            {"$set": {"joined": datetime.utcnow(), "first_name": msg.from_user.first_name}},
            upsert=True
        )
        btns = InlineKeyboardMarkup([
            [InlineKeyboardButton("Update Channel", url=UPDATE_CHANNEL)],
            [InlineKeyboardButton("Contact Admin", url="https://t.me/ctgmovies23")]
        ])
        await msg.reply_photo(photo=START_PIC, caption="Send me a movie name to search.", reply_markup=btns)
        logger.info(f"User {msg.from_user.id} started the bot.")
    except Exception as e:
        logger.error(f"Error handling /start for user {msg.from_user.id}: {e}")

@app.on_message(filters.command("feedback") & filters.private)
async def feedback(_, msg: Message):
    """Allows users to send feedback to the bot admins."""
    if len(msg.command) < 2:
        return await msg.reply("Please write something after /feedback.", quote=True)
    try:
        feedback_col.insert_one({
            "user_id": msg.from_user.id,
            "username": msg.from_user.username,
            "text": msg.text.split(None, 1)[1],
            "time": datetime.utcnow()
        })
        m = await msg.reply("Thanks for your feedback!")
        asyncio.create_task(delete_message_later(m.chat.id, m.id))
        logger.info(f"Feedback received from user {msg.from_user.id}.")
    except Exception as e:
        logger.error(f"Error handling /feedback from user {msg.from_user.id}: {e}")
        await msg.reply("An error occurred while saving your feedback. Please try again later.")

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(_, msg: Message):
    """Admins can use this to send messages to all bot users."""
    if len(msg.command) < 2:
        return await msg.reply("Usage: /broadcast Your message here", quote=True)
    
    broadcast_text = msg.text.split(None, 1)[1]
    count = 0
    failed_count = 0
    
    await msg.reply("Starting broadcast...")
    
    for user in users_col.find():
        try:
            await app.send_message(user["_id"], broadcast_text)
            count += 1
            await asyncio.sleep(0.1) # Small delay to avoid FloodWait
        except Exception as e:
            failed_count += 1
            logger.warning(f"Failed to send broadcast to user {user['_id']}: {e}")
            pass
    await msg.reply(f"Broadcast completed. Sent to {count} users, failed for {failed_count} users.")
    logger.info(f"Broadcast initiated by admin {msg.from_user.id}. Sent to {count} users, failed for {failed_count}.")


@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg: Message):
    """Provides bot statistics (number of users, movies, and feedbacks) to admins."""
    try:
        await msg.reply(
            f"Users: {users_col.count_documents({})}\n"
            f"Movies: {movies_col.count_documents({})}\n"
            f"Feedbacks: {feedback_col.count_documents({})}"
        )
        logger.info(f"Stats requested by admin {msg.from_user.id}.")
    except Exception as e:
        logger.error(f"Error retrieving stats for admin {msg.from_user.id}: {e}")
        await msg.reply("An error occurred while fetching statistics.")

@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_movie(_, msg: Message):
    """Allows admins to delete a movie by its message ID."""
    if len(msg.command) != 2:
        return await msg.reply("ব্যবহার: /delete_movie <movie_id>", quote=True)
    try:
        movie_id = int(msg.command[1])
        result = movies_col.delete_one({"message_id": movie_id})
        if result.deleted_count:
            await msg.reply(f"✅ মুভি (ID: {movie_id}) ডিলিট করা হয়েছে।")
            logger.info(f"Movie ID {movie_id} deleted by admin {msg.from_user.id}.")
        else:
            await msg.reply("❌ এই ID-এর কোনো মুভি পাওয়া যায়নি।")
            logger.warning(f"Admin {msg.from_user.id} tried to delete non-existent movie ID {movie_id}.")
    except ValueError:
        await msg.reply("⚠️ Movie ID একটি সংখ্যা হওয়া প্রয়োজন।")
        logger.warning(f"Admin {msg.from_user.id} provided invalid movie ID: {msg.command[1]}.")
    except Exception as e:
        await msg.reply(f"An error occurred: {e}")
        logger.error(f"Error deleting movie by admin {msg.from_user.id}: {e}")

@app.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_IDS))
async def delete_all_movies(_, msg: Message):
    """Admins can use this to delete all movies from the database."""
    try:
        result = movies_col.delete_many({})
        await msg.reply(f"🗑️ মোট {result.deleted_count} টি মুভি ডিলিট করা হয়েছে।")
        logger.info(f"All {result.deleted_count} movies deleted by admin {msg.from_user.id}.")
    except Exception as e:
        await msg.reply(f"An error occurred: {e}")
        logger.error(f"Error deleting all movies by admin {msg.from_user.id}: {e}")

@app.on_message(filters.command("notify") & filters.user(ADMIN_IDS))
async def notify_command(_, msg: Message):
    """Admins can toggle global new movie notifications."""
    if len(msg.command) != 2 or msg.command[1].lower() not in ["on", "off"]:
        return await msg.reply("ব্যবহার: /notify on  অথবা  /notify off", quote=True)
    
    new_value = True if msg.command[1].lower() == "on" else False
    try:
        settings_col.update_one(
            {"key": "global_notify"},
            {"$set": {"value": new_value}},
            upsert=True
        )
        status = "enabled" if new_value else "disabled"
        await msg.reply(f"✅ Global notifications {status}!")
        logger.info(f"Global notifications set to {status} by admin {msg.from_user.id}.")
    except Exception as e:
        logger.error(f"Error toggling global notifications by admin {msg.from_user.id}: {e}")
        await msg.reply("An error occurred while changing notification settings.")

@app.on_message(filters.text & filters.private & ~filters.command(["start", "feedback", "broadcast", "stats", "delete_movie", "delete_all_movies", "notify", "search"]))
async def search_movies(_, msg: Message):
    """
    Handles regular text messages as movie search queries.
    Performs an exact match search first, then suggests using fuzzy matching.
    """
    raw_query = msg.text.strip()
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"last_search": datetime.utcnow()}},
        upsert=True
    )
    logger.info(f"User {msg.from_user.id} searching for: '{raw_query}'")

    loading = await msg.reply("🔎 লোড হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")
    
    try:
        # Try exact match first
        exact_match_regex = re.compile(f"^{re.escape(raw_query)}$", re.IGNORECASE)
        exact_matches = list(movies_col.find({"title": exact_match_regex}))
        
        if exact_matches:
            await loading.delete()
            for m in exact_matches[:RESULTS_COUNT]:
                try:
                    fwd = await app.forward_messages(msg.chat.id, CHANNEL_ID, m["message_id"])
                    await msg.reply("⚠️ এই মুভিটি 10 মিনিট পর অটো ডিলিট হয়ে যাবে।")
                    asyncio.create_task(delete_message_later(msg.chat.id, fwd.id))
                    await asyncio.sleep(0.7) # Add a small delay between forwarding
                except Exception as e:
                    await msg.reply(f"Failed to forward movie: {m.get('title', 'N/A')} (ID: {m['message_id']}). Error: {e}")
                    logger.error(f"Error forwarding exact match movie {m['message_id']} to {msg.chat.id}: {e}")
            logger.info(f"Exact match found for '{raw_query}'. Forwarded {len(exact_matches)} movies.")
            return

        # If no exact match, try fuzzy matching with suggestions
        all_titles_with_ids = [(m["title"], m["message_id"]) for m in movies_col.find({}, {"title": 1, "message_id": 1})]
        
        if not all_titles_with_ids:
            await loading.edit("❌ No movies found in database.")
            logger.info(f"No movies in database for search '{raw_query}'.")
            return

        # Use fuzzywuzzy to find close matches
        # Get more matches initially to ensure enough valid ones after filtering
        top_matches = process.extract(raw_query, dict(all_titles_with_ids), limit=RESULTS_COUNT * 5) 
        
        # Filter matches with a score above 50 (can be adjusted)
        suggestions = [(title, mid) for title, score, mid in top_matches if score >= 50]

        if suggestions:
            await loading.delete()
            # Add language filter buttons
            lang_buttons = [
                InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{urllib.parse.quote(raw_query)}"),
                InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{urllib.parse.quote(raw_query)}"),
                InlineKeyboardButton("English", callback_data=f"lang_English_{urllib.parse.quote(raw_query)}")
            ]
            
            # Create buttons for suggested movies
            buttons = [
                [InlineKeyboardButton(title[:40], callback_data=f"movie_{mid}")]
                for title, mid in suggestions[:RESULTS_COUNT]
            ]
            
            if buttons: # Only add language buttons if there are movie suggestions
                buttons.append(lang_buttons)

            m = await msg.reply("আপনার মুভির নাম মিলতে পারে, নিচের থেকে সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(buttons))
            asyncio.create_task(delete_message_later(m.chat.id, m.id)) # Delete suggestion message after a delay
            logger.info(f"Fuzzy matches found for '{raw_query}'. Sent {len(suggestions)} suggestions.")
            return

        # If no results or suggestions, inform user and notify admin
        await loading.delete()
        Google Search_url = "https://www.google.com/search?q=" + urllib.parse.quote(raw_query)
        google_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("Search on Google", url=Google Search_url)]
        ])
        alert = await msg.reply(
            "কোনও ফলাফল পাওয়া যায়নি। অ্যাডমিনকে জানানো হয়েছে। নিচের বাটনে ক্লিক করে গুগলে সার্চ করুন।",
            reply_markup=google_button
        )
        asyncio.create_task(delete_message_later(alert.chat.id, alert.id))
        logger.info(f"No results or fuzzy matches for '{raw_query}'. Notifying admins.")

        # Notify admins about failed search
        btn = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ মুভি আছে", callback_data=f"has_{msg.chat.id}_{msg.id}_{urllib.parse.quote(raw_query)}"),
                InlineKeyboardButton("❌ নেই", callback_data=f"no_{msg.chat.id}_{msg.id}_{urllib.parse.quote(raw_query)}")
            ],
            [
                InlineKeyboardButton("⏳ আসবে", callback_data=f"soon_{msg.chat.id}_{msg.id}_{urllib.parse.quote(raw_query)}"),
                InlineKeyboardButton("✏️ ভুল নাম", callback_data=f"wrong_{msg.chat.id}_{msg.id}_{urllib.parse.quote(raw_query)}")
            ]
        ])
        for admin_id in ADMIN_IDS:
            try:
                await app.send_message(
                    admin_id,
                    f"❗ ইউজার `{msg.from_user.id}` `{msg.from_user.first_name}` খুঁজেছে: **{raw_query}**\nফলাফল পাওয়া যায়নি। নিচে বাটন থেকে উত্তর দিন।",
                    reply_markup=btn
                )
            except Exception as e:
                logger.warning(f"Failed to notify admin {admin_id} about search query '{raw_query}': {e}")
                pass
    except Exception as e:
        logger.error(f"Error during movie search for '{raw_query}' by user {msg.from_user.id}: {e}")
        await loading.edit("An unexpected error occurred during search. Please try again.")

@app.on_message(filters.command("search") & filters.private)
async def command_search(_, msg: Message):
    """
    Handles the /search command for explicit movie searches, using fuzzy matching.
    """
    if len(msg.command) < 2:
        return await msg.reply("Usage: `/search movie name`", quote=True)
    
    query = " ".join(msg.command[1:]).strip()
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"last_search": datetime.utcnow()}},
        upsert=True
    )
    logger.info(f"User {msg.from_user.id} used /search for: '{query}'")

    loading = await msg.reply("🔍 Searching...")
    try:
        all_titles_with_ids = [(m["title"], m["message_id"]) for m in movies_col.find({}, {"title": 1, "message_id": 1})]
        
        if not all_titles_with_ids:
            await loading.edit("❌ No movies found in database.")
            logger.info(f"No movies in database for /search '{query}'.")
            return

        # Use fuzzywuzzy to find close matches
        top_matches = process.extract(query, dict(all_titles_with_ids), limit=RESULTS_COUNT * 5)
        
        # Filter matches with a score above 50 (can be adjusted)
        buttons_data = [
            (title, mid) for title, score, mid in top_matches if score >= 50
        ]
        
        if buttons_data:
            buttons = [
                [InlineKeyboardButton(title[:40], callback_data=f"movie_{mid}")]
                for title, mid in buttons_data[:RESULTS_COUNT]
            ]
            
            await loading.edit(
                f"📽️ Results for: **{query}**\nSelect one below:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            logger.info(f"Fuzzy matches found for /search '{query}'. Sent {len(buttons_data)} suggestions.")
        else:
            await loading.edit("❌ No sufficiently close matches found.")
            logger.info(f"No sufficiently close matches for /search '{query}'.")
    except Exception as e:
        logger.error(f"Error during /search command for '{query}' by user {msg.from_user.id}: {e}")
        await loading.edit("An unexpected error occurred during search. Please try again.")


# --- Callback Query Handler ---
@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    """Handles all inline keyboard button presses."""
    data = cq.data
    logger.info(f"Callback query received from user {cq.from_user.id}: {data}")

    if data.startswith("movie_"):
        # User selected a movie from search results
        mid = int(data.split("_")[1])
        try:
            fwd = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
            await cq.message.reply("⚠️ এই মুভিটি 10 মিনিট পর অটো ডিলিট হয়ে যাবে।")
            asyncio.create_task(delete_message_later(cq.message.chat.id, fwd.id))
            await cq.answer("মুভি পাঠানো হয়েছে।")
            logger.info(f"Forwarded movie ID {mid} to user {cq.message.chat.id}.")
        except Exception as e:
            await cq.answer(f"Failed to send movie. Error: {e}", show_alert=True)
            logger.error(f"Error forwarding movie ID {mid} to chat {cq.message.chat.id}: {e}")

    elif data.startswith("lang_"):
        # User filtered results by language
        _, lang, raw_query = data.split("_", 2)
        query = urllib.parse.unquote(raw_query)

        # Find movies matching the query and selected language
        all_lang_movies = list(movies_col.find({"language": lang}, {"title": 1, "message_id": 1}))
        
        # Use fuzzywuzzy to find matches within the language
        top_matches_lang = process.extract(query, dict([(m["title"], m["message_id"]) for m in all_lang_movies]), limit=RESULTS_COUNT * 5)
        
        matches = [(title, mid) for title, score, mid in top_matches_lang if score >= 50]

        if matches:
            buttons = [
                [InlineKeyboardButton(title[:40], callback_data=f"movie_{mid}")]
                for title, mid in matches[:RESULTS_COUNT]
            ]
            await cq.message.edit_text(
                f"ফলাফল ({lang}) - নিচের থেকে সিলেক্ট করুন:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            logger.info(f"Language filter '{lang}' applied for query '{query}'. Sent {len(matches)} results.")
        else:
            await cq.answer("এই ভাষায় কিছু পাওয়া যায়নি।", show_alert=True)
            logger.info(f"No results for language filter '{lang}' for query '{query}'.")

    elif "_" in data:
        # Admin feedback on user's search query (has/no/soon/wrong)
        parts = data.split("_", 3)
        if len(parts) == 4:
            action, uid_str, mid_str, raw_query_encoded = parts
            uid = int(uid_str)
            raw_query = urllib.parse.unquote(raw_query_encoded) # Decode the query

            responses = {
                "has": f"✅ @{cq.from_user.username or cq.from_user.first_name} জানিয়েছেন যে **{raw_query}** মুভিটি ডাটাবেজে আছে। সঠিক নাম লিখে আবার চেষ্টা করুন।",
                "no": f"❌ @{cq.from_user.username or cq.from_user.first_name} জানিয়েছেন যে **{raw_query}** মুভিটি ডাটাবেজে নেই।",
                "soon": f"⏳ @{cq.from_user.username or cq.from_user.first_name} জানিয়েছেন যে **{raw_query}** মুভিটি শীঘ্রই আসবে।",
                "wrong": f"✏️ @{cq.from_user.username or cq.from_user.first_name} বলছেন যে আপনি ভুল নাম লিখেছেন: **{raw_query}**।"
            }
            if action in responses:
                try:
                    m = await app.send_message(uid, responses[action])
                    asyncio.create_task(delete_message_later(m.chat.id, m.id))
                    await cq.answer("অ্যাডমিনের পক্ষ থেকে উত্তর পাঠানো হয়েছে।")
                    logger.info(f"Admin {cq.from_user.id} responded to user {uid} about query '{raw_query}' with action '{action}'.")
                except Exception as e:
                    await cq.answer(f"Failed to send response to user: {e}", show_alert=True)
                    logger.error(f"Error sending admin response to user {uid} for query '{raw_query}': {e}")
            else:
                await cq.answer() # Answer unrecognized callback queries to prevent loading state
                logger.warning(f"Unrecognized callback query action: {action}")
        else:
            await cq.answer()
            logger.warning(f"Malformed callback query data: {data}")


# --- Main Execution ---
if __name__ == "__main__":
    logger.info("Bot is starting...")
    app.run() # Starts the Pyrogram bot
    logger.info("Bot stopped.")

