import asyncio
import logging
import urllib.parse
from datetime import datetime
from difflib import SequenceMatcher

from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from pymongo import MongoClient

# Setup logging
logging.basicConfig(level=logging.INFO)

# Config
API_ID = 12345678
API_HASH = "your_api_hash"
BOT_TOKEN = "your_bot_token"
MONGO_URI = "your_mongo_uri"
ADMIN_IDS = [123456789, 987654321]  # Add admin Telegram user IDs here
RESULTS_COUNT = 10

# MongoDB setup
client = MongoClient(MONGO_URI)
db = client["movie_bot"]
movies_col = db["movies"]
users_col = db["users"]

# Pyrogram client
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Helpers
def clean_text(text):
    return ''.join(e for e in text.lower() if e.isalnum() or e.isspace()).strip()

def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()

async def delete_message_later(chat_id, message_id, delay=120):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except:
        pass

# Search Handler
@app.on_message(filters.text)
async def search(_, msg):
    raw_query = msg.text.strip()
    query = clean_text(raw_query)
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"last_search": datetime.utcnow()}},
        upsert=True
    )

    loading = await msg.reply("🔎 লোড হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1, "language": 1}))

    scored_movies = []
    for m in all_movies:
        title_clean = clean_text(m.get("title", ""))
        score = similarity(query, title_clean)
        if score > 0.3:
            scored_movies.append((score, m))

    scored_movies.sort(key=lambda x: x[0], reverse=True)

    if scored_movies:
        await loading.delete()
        buttons = [
            [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")]
            for _, m in scored_movies[:RESULTS_COUNT]
        ]

        lang_buttons = [
            InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{query}"),
            InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{query}"),
            InlineKeyboardButton("English", callback_data=f"lang_English_{query}")
        ]
        buttons.append(lang_buttons)

        m = await msg.reply("আপনার মুভির নাম মিলতে পারে, নিচের থেকে সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(buttons))
        asyncio.create_task(delete_message_later(m.chat.id, m.id))
        return

    # fallback: গুগল সার্চ + অ্যাডমিনকে ইনফর্ম
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

# Start the bot
if __name__ == "__main__":
    print("Bot is running...")
    app.run()
