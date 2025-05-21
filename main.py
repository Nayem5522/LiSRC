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

# ===== CONFIGURATION =====
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")
START_PIC = os.getenv("START_PIC", "https://i.ibb.co/prnGXMr3/photo-2025-05-16-05-15-45-7504908428624527364.jpg")

# ===== INIT =====
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
feedback_col = db["feedback"]
users_col = db["users"]
settings_col = db["settings"]

# Create indexes
movies_col.create_index([("title", ASCENDING)])
movies_col.create_index("message_id")
movies_col.create_index("language")

# ===== FLASK =====
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)

Thread(target=run_flask).start()

# ===== HELPERS =====
def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

def extract_year(text):
    match = re.search(r"(19|20)\d{2}", text)
    return match.group() if match else None

def extract_language(text):
    langs = ["Bengali", "Hindi", "English"]
    text_lower = text.lower()
    for lang in langs:
        if lang.lower() in text_lower:
            return lang
    return "Unknown"

async def delete_message_later(chat_id, message_id, delay=600):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except:
        pass

# ===== HANDLERS =====
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

    # Notify users if global notify on
    setting = settings_col.find_one({"key": "global_notify"})
    if setting and setting.get("value"):
        for user in users_col.find({"notify": {"$ne": False}}):
            try:
                await app.send_message(
                    user["_id"],
                    f"নতুন মুভি আপলোড হয়েছে:\n{text.splitlines()[0][:100]}\nএখনই সার্চ করে দেখুন!"
                )
            except:
                pass

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
        except:
            pass
    await msg.reply(f"Broadcast sent to {count} users.")

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg):
    total_users = users_col.count_documents({})
    total_movies = movies_col.count_documents({})
    total_feedbacks = feedback_col.count_documents({})

    pipeline = [{"$group": {"_id": None, "total_searches": {"$sum": "$search_count"}}}]
    result = list(users_col.aggregate(pipeline))
    total_searches = result[0]["total_searches"] if result else 0

    await msg.reply(
        f"Users: {total_users}\n"
        f"Movies: {total_movies}\n"
        f"Feedbacks: {total_feedbacks}\n"
        f"Total Searches: {total_searches}"
    )

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

@app.on_message(filters.command("delete") & filters.user(ADMIN_IDS))
async def delete_movie(_, msg: Message):
    if len(msg.command) < 2:
        return await msg.reply("Usage: /delete movie_name")
    movie_name = " ".join(msg.command[1:])
    result = movies_col.delete_many({"title": {"$regex": re.escape(movie_name), "$options": "i"}})
    if result.deleted_count > 0:
        await msg.reply(f"Deleted {result.deleted_count} movies matching '{movie_name}'.")
    else:
        await msg.reply("No matching movies found to delete.")

@app.on_message(filters.text)
async def search(_, msg):
    raw_query = msg.text.strip()
    query = clean_text(raw_query)

    # Track user's search count and last search time
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$inc": {"search_count": 1}, "$set": {"last_search": datetime.utcnow()}},
        upsert=True
    )

    loading = await msg.reply("🔎 লোড হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1, "language": 1}))

    exact_match = [m for m in all_movies if clean_text(m.get("title", "")) == query]
    if exact_match:
        await loading.delete()
        for m in exact_match[:RESULTS_COUNT]:
            fwd = await app.forward_messages(msg.chat.id, CHANNEL_ID, m["message_id"])
            asyncio.create_task(delete_message_later(msg.chat.id, fwd.id))
            await asyncio.sleep(0.7)
        return

    suggestions = [
        m for m in all_movies
        if re.search(re.escape(raw_query), m.get("title", ""), re.IGNORECASE)
    ]
    if suggestions:
        await loading.delete()
        lang_buttons = [
            InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{query}"),
            InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{query}"),
            InlineKeyboardButton("English", callback_data=f"lang_English_{query}")
        ]
        buttons = [
            [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")]
            for m in suggestions[:RESULTS_COUNT]
        ]
        buttons.append(lang_buttons)
        m = await msg.reply("আপনার মুভির নাম মিলতে পারে, নিচের থেকে সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(buttons))
        asyncio.create_task(delete_message_later(m.chat.id, m.id))
        return

    await loading.delete()
    google_search_url = "https://www.google.com/search?q=" + urllib.parse.quote(raw_query)
    google_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("Search on Google", url=google_search_url)]
    ])
    alert = await msg.reply(
        "কোনও ফলাফল পাওয়া যায়নি। অ্যাডমিনকে জানানো হয়েছে। নিচের বাটনে ক্লিক করে গুগলে সার্চ করুন।",
        reply_markup=google_button
    )
    asyncio.create_task(delete_message_later(alert.chat.id, alert.id))

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
        await app.send_message(
            admin_id,
            f"❗ ইউজার `{msg.from_user.id}` `{msg.from_user.first_name}` খুঁজেছে: **{raw_query}**\nফলাফল পাওয়া যায়নি। নিচে বাটন থেকে উত্তর দিন।",
            reply_markup=btn
        )

@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data

    if data.startswith("movie_"):
        mid = int(data.split("_")[1])
        fwd = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
        asyncio.create_task(delete_message_later(cq.message.chat.id, fwd.id))
        await cq.answer("মুভি পাঠানো হয়েছে।")

    elif data.startswith("lang_"):
        _, lang, query = data.split("_", 2)
        lang_movies = list(movies_col.find({"language": lang}))
        matches = [
            m for m in lang_movies
            if re.search(re.escape(query), m.get("title", ""), re.IGNORECASE)
        ][:RESULTS_COUNT]
        if matches:
            text = "\n\n".join([m["title"] for m in matches])
            await cq.message.edit_text(f"Language: {lang}\nMatches:\n{text}")
        else:
            await cq.message.edit_text("No matches found for this language.")
        await cq.answer()

    elif data.startswith(("has_", "no_", "soon_", "wrong_")):
        # Admin response buttons after user no-result search
        await cq.answer("Thanks for your response!")

app.run()
