from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient, ASCENDING
from flask import Flask
from threading import Thread
import os
import re
from datetime import datetime
import asyncio
import urllib.parse
from fuzzywuzzy import process # Added for fuzzy matching

# Configs
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")
START_PIC = os.getenv("START_PIC", "https://i.ibb.co/prnGXMr/photo-2025-05-16-05-15-45-7504908428624527364.jpg")
FUZZY_MATCH_THRESHOLD = int(os.getenv("FUZZY_MATCH_THRESHOLD", 80)) # New config for fuzzy matching threshold

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# MongoDB setup
mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
feedback_col = db["feedback"]
stats_col = db["stats"]
users_col = db["users"]
settings_col = db["settings"]

# Index
movies_col.create_index([("title", ASCENDING)])
movies_col.create_index("message_id")
movies_col.create_index("language")

# Flask
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Bot is running!"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

# Helpers
def clean_text(text):
    # This function is now only for basic cleaning, more specific cleaning for query
    return re.sub(r'[^a-zA-Z0-9\s]', '', text).lower()

def clean_query(query):
    # Remove common extra words and symbols from the search query
    query = query.lower()
    query = re.sub(r'\b(movie|full|hd|online|free|download|watch)\b', '', query) # Remove common keywords
    query = re.sub(r'\.\w+', '', query) # Remove file extensions like .com, .mkv, .mp4
    query = re.sub(r'\d{4}', '', query) # Remove years (e.g., 2023) - if you want to ignore years in search
    query = re.sub(r'[^\w\s]', '', query) # Remove special characters
    query = re.sub(r'\s+', ' ', query).strip() # Replace multiple spaces with a single space
    return query

def extract_year(text):
    match = re.search(r"(19|20)\d{2}", text)
    return match.group() if match else None

def extract_language(text):
    langs = ["Bengali", "Hindi", "English"]
    return next((lang for lang in langs if lang.lower() in text.lower()), "Unknown")

async def delete_message_later(chat_id, message_id, delay=600):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except Exception as e:
        print(f"Error deleting message {message_id} in chat {chat_id}: {e}")

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
        for user in users_col.find({"notify": {"$ne": False}}):
            try:
                await app.send_message(
                    user["_id"],
                    f"নতুন মুভি আপলোড হয়েছে:\n{text.splitlines()[0][:100]}\nএখনই সার্চ করে দেখুন!"
                )
            except Exception as e:
                print(f"Error sending notification to user {user['_id']}: {e}")

@app.on_message(filters.command("start"))
async def start(_, msg: Message):
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

@app.on_message(filters.command("feedback") & filters.private)
async def feedback(_, msg):
    if len(msg.command) < 2:
        return await msg.reply("Please write something after /feedback.")
    feedback_col.insert_one({
        "user": msg.from_user.id,
        "text": msg.text.split(None, 1)[1],
        "time": datetime.utcnow()
    })
    m = await msg.reply("Thanks for your feedback!")
    asyncio.create_task(delete_message_later(m.chat.id, m.id))

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(_, msg):
    if len(msg.command) < 2:
        return await msg.reply("Usage: /broadcast Your message here")
    count = 0
    for user in users_col.find():
        try:
            await app.send_message(user["_id"], msg.text.split(None, 1)[1])
            count += 1
        except Exception as e:
            print(f"Error broadcasting to user {user['_id']}: {e}")
            pass
    await msg.reply(f"Broadcast sent to {count} users.")

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg):
    await msg.reply(
        f"Users: {users_col.count_documents({})}\n"
        f"Movies: {movies_col.count_documents({})}\n"
        f"Feedbacks: {feedback_col.count_documents({})}"
    )

@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_movie(_, msg):
    if len(msg.command) != 2:
        return await msg.reply("ব্যবহার: /delete_movie <movie_id>")
    try:
        movie_id = int(msg.command[1])
        result = movies_col.delete_one({"message_id": movie_id})
        if result.deleted_count:
            await msg.reply(f"✅ মুভি (ID: {movie_id}) ডিলিট করা হয়েছে।")
        else:
            await msg.reply("❌ এই ID-এর কোনো মুভি পাওয়া যায়নি।")
    except Exception as e:
        await msg.reply(f"⚠️ Movie ID একটি সংখ্যা হওয়া প্রয়োজন। ত্রুটি: {e}")

@app.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_IDS))
async def delete_all_movies(_, msg):
    result = movies_col.delete_many({})
    await msg.reply(f"🗑️ মোট {result.deleted_count} টি মুভি ডিলিট করা হয়েছে।")

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

@app.on_message(filters.text)
async def search(_, msg):
    raw_query = msg.text.strip()
    processed_query = clean_query(raw_query) # Cleaned query for fuzzy matching
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"last_search": datetime.utcnow()}},
        upsert=True
    )

    loading = await msg.reply("🔎 লোড হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")
    
    # Get all movie titles for fuzzy matching
    all_movie_titles = [m.get("title", "") for m in movies_col.find({}, {"title": 1})]
    
    # Perform fuzzy matching
    # results format: [('Movie Title 1', score), ('Movie Title 2', score), ...]
    fuzzy_results = process.extract(processed_query, all_movie_titles, limit=RESULTS_COUNT * 2) # Get more results to filter later

    # Filter out results below the threshold and get unique movie message_ids
    matched_movie_ids = []
    seen_movie_ids = set() # To store unique message_ids
    
    for title, score in fuzzy_results:
        if score >= FUZZY_MATCH_THRESHOLD:
            # Find the actual movie document using its title
            movie_doc = movies_col.find_one({"title": title}, {"message_id": 1})
            if movie_doc and movie_doc["message_id"] not in seen_movie_ids:
                matched_movie_ids.append(movie_doc["message_id"])
                seen_movie_ids.add(movie_doc["message_id"])
        
        if len(matched_movie_ids) >= RESULTS_COUNT: # Stop if we have enough
            break

    await loading.delete()

    if matched_movie_ids:
        # If there are direct or fuzzy matches, show them
        for movie_id in matched_movie_ids[:RESULTS_COUNT]:
            try:
                fwd = await app.forward_messages(msg.chat.id, CHANNEL_ID, movie_id)
                await msg.reply("⚠️ এই মুভিটি 10 মিনিট পর অটো ডিলিট হয়ে যাবে।")
                asyncio.create_task(delete_message_later(msg.chat.id, fwd.id))
                await asyncio.sleep(0.7) # Small delay to avoid flood waits
            except Exception as e:
                print(f"Error forwarding movie {movie_id}: {e}")
                pass
        return
    else:
        # No direct or fuzzy match, suggest language-based search or Google
        Google Search_url = "https://www.google.com/search?q=" + urllib.parse.quote(raw_query) # এই লাইনটি সঠিক করা হয়েছে
        google_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("Search on Google", url=Google Search_url)]
        ])
        
        # Original suggestion part for language-based searches (can be improved with fuzzy search on language too)
        # For simplicity, keeping the existing language filter for now if no fuzzy match is found
        lang_buttons = [
            InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{processed_query}"),
            InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{processed_query}"),
            InlineKeyboardButton("English", callback_data=f"lang_English_{processed_query}")
        ]
        
        suggestion_text = "কোনও ফলাফল পাওয়া যায়নি। আপনি কি এই মুভিটি অন্য ভাষায় খুঁজতে চান?"
        suggestion_markup = InlineKeyboardMarkup([lang_buttons, [InlineKeyboardButton("Google-এ খুঁজুন", url=Google Search_url)]])
        
        alert = await msg.reply(
            suggestion_text,
            reply_markup=suggestion_markup
        )
        asyncio.create_task(delete_message_later(alert.chat.id, alert.id))

        # Admin notification remains the same
        btn = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ মুভি আছে", callback_data=f"has_{msg.chat.id}_{msg.id}_{raw_query}"),
                InlineKeyboardButton("❌ নেই", callback_data=f"no_{msg.chat.id}_{msg.id}_{raw_query}")
            ],
            [
                InlineKeyboardButton("⏳ আসবে", callback_data=f"soon_{msg.chat.id}_{msg.id}_{raw_query}"),
                InlineKeyboardButton("✏️ ভুল নাম", callback_data=f"wrong_{msg.chat.id}_{msg.id}_{raw_query}")
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
                print(f"Error sending admin notification to {admin_id}: {e}")


@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data

    if data.startswith("movie_"):
        mid = int(data.split("_")[1])
        try:
            fwd = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
            await cq.message.reply("⚠️ এই মুভিটি 10 মিনিট পর অটো ডিলিট হয়ে যাবে।")
            asyncio.create_task(delete_message_later(cq.message.chat.id, fwd.id))
            await cq.answer("মুভি পাঠানো হয়েছে।")
        except Exception as e:
            await cq.answer("মুভিটি ফরওয়ার্ড করতে সমস্যা হয়েছে।", show_alert=True)
            print(f"Error forwarding movie from callback: {e}")

    elif data.startswith("lang_"):
        _, lang, query = data.split("_", 2)
        # Search for movies in the specified language, using fuzzy matching if the query is not empty
        
        # Get all movie titles for fuzzy matching within the selected language
        lang_movie_titles = [m.get("title", "") for m in movies_col.find({"language": lang}, {"title": 1})]
        
        if query: # If there's a specific query from the initial search
            fuzzy_lang_results = process.extract(query, lang_movie_titles, limit=RESULTS_COUNT)
            matched_movies = []
            seen_titles = set()
            for title, score in fuzzy_lang_results:
                if score >= FUZZY_MATCH_THRESHOLD and title not in seen_titles:
                    movie_doc = movies_col.find_one({"title": title, "language": lang}, {"message_id": 1, "title": 1})
                    if movie_doc:
                        matched_movies.append(movie_doc)
                        seen_titles.add(title)
        else: # If no specific query, just list movies in that language (or top ones)
            matched_movies = list(movies_col.find({"language": lang}, {"message_id": 1, "title": 1}).limit(RESULTS_COUNT))

        if matched_movies:
            buttons = [
                [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")]
                for m in matched_movies
            ]
            await cq.message.edit_text(
                f"ফলাফল ({lang}) - নিচের থেকে সিলেক্ট করুন:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await cq.answer(f"এই ভাষায় '{query}' এর জন্য কিছু পাওয়া যায়নি।", show_alert=True)
        await cq.answer()

    elif "_" in data:
        parts = data.split("_", 3)
        if len(parts) == 4:
            action, uid, mid, raw_query = parts
            uid = int(uid)
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
                except Exception as e:
                    await cq.answer("ইউজারকে মেসেজ পাঠাতে সমস্যা হয়েছে।", show_alert=True)
                    print(f"Error sending admin response to user {uid}: {e}")
            else:
                await cq.answer()

if __name__ == "__main__":
    print("Bot is starting...")
    app.run()
