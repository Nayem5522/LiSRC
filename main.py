from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from pymongo import MongoClient
from datetime import datetime
import asyncio
import re
import os

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
MONGO_URL = os.getenv("MONGO_URL")
RESULTS_COUNT = 5
ADMIN_IDS = [int(i) for i in os.getenv("ADMIN_IDS", "").split()]

app = Client("search-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = MongoClient(MONGO_URL)
db = mongo["autolink"]
movies_col = db["movies"]
users_col = db["users"]

def clean_text(text):
    return re.sub(r"[^a-zA-Z0-9]", "", text).lower()

@app.on_message(filters.channel)
async def save_channel_messages(client, message):
    if not message.text and not message.caption:
        return
    title = message.text or message.caption
    title = title.split("\n")[0][:100]
    lang = "Bengali" if "BN" in title.upper() else "Hindi" if "HIN" in title.upper() else "English" if "ENG" in title.upper() else "Unknown"
    year_match = re.search(r'(19|20)\d{2}', title)
    year = year_match.group() if year_match else "Unknown"
    type_ = "Movie" if "MOVIE" in title.upper() else "Web Series" if "SERIES" in title.upper() else "Unknown"

    if not movies_col.find_one({"message_id": message.id}):
        movies_col.insert_one({
            "message_id": message.id,
            "title": title,
            "language": lang,
            "year": year,
            "type": type_
        })

@app.on_message(filters.text & (filters.private | filters.group))
async def search(_, msg):
    raw_query = msg.text.strip()
    query = clean_text(raw_query)
    users_col.update_one({"_id": msg.from_user.id}, {"$set": {"last_search": datetime.utcnow()}}, upsert=True)

    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1, "language": 1, "year": 1, "type": 1}))
    exact_match = [m for m in all_movies if clean_text(m.get("title", "")) == query]

    if exact_match:
        try:
            for m in exact_match[:RESULTS_COUNT]:
                await app.forward_messages(msg.chat.id, CHANNEL_ID, m["message_id"])
                await asyncio.sleep(1)
            return
        except:
            await msg.reply("মুভি পাঠাতে সমস্যা হয়েছে।")
            return

    suggestions = [m for m in all_movies if re.search(re.escape(raw_query), m.get("title", ""), re.IGNORECASE)]
    if suggestions:
        buttons = [
            [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")]
            for m in suggestions[:RESULTS_COUNT]
        ]

        filter_buttons = [
            [
                InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{query}"),
                InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{query}"),
                InlineKeyboardButton("English", callback_data=f"lang_English_{query}")
            ],
            [
                InlineKeyboardButton("2023", callback_data=f"year_2023_{query}"),
                InlineKeyboardButton("2024", callback_data=f"year_2024_{query}"),
                InlineKeyboardButton("2025", callback_data=f"year_2025_{query}")
            ],
            [
                InlineKeyboardButton("Movie", callback_data=f"type_movie_{query}"),
                InlineKeyboardButton("Web Series", callback_data=f"type_series_{query}")
            ]
        ]

        buttons.extend(filter_buttons)
        await msg.reply("আপনার মুভির নাম মিলতে পারে, নিচের থেকে সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    await msg.reply("কোনও ফলাফল পাওয়া যায়নি। অ্যাডমিনকে জানানো হয়েছে।")
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("\u2705 মুভি আছে", callback_data=f"has_{msg.chat.id}")],
        [InlineKeyboardButton("\u274C নেই", callback_data=f"no_{msg.chat.id}")],
        [InlineKeyboardButton("\u23F3 আসবে", callback_data=f"soon_{msg.chat.id}")],
        [InlineKeyboardButton("\u270F\uFE0F ভুল নাম", callback_data=f"wrong_{msg.chat.id}")]
    ])
    for admin_id in ADMIN_IDS:
        await app.send_message(admin_id, f"\u2757 ইউজার `{msg.from_user.id}` `{msg.from_user.first_name}` খুঁজেছে: **{raw_query}**\n\nফলাফল পাওয়া যায়নি। নিচে বাটন থেকে উত্তর দিন।", reply_markup=btn)

@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data
    if data.startswith("movie_"):
        msg_id = int(data.split("_")[1])
        await app.forward_messages(cq.message.chat.id, CHANNEL_ID, msg_id)
        await cq.answer()

    elif data.startswith("lang_"):
        _, lang, query = data.split("_", 2)
        lang_movies = movies_col.find({"language": lang})
        matches = [m for m in lang_movies if re.search(re.escape(query), m.get("title", ""), re.IGNORECASE)]
        if matches:
            for m in matches[:RESULTS_COUNT]:
                await app.forward_messages(cq.message.chat.id, CHANNEL_ID, m["message_id"])
                await asyncio.sleep(1)
        else:
            await cq.message.reply("এই ভাষায় কিছু পাওয়া যায়নি।")
        await cq.answer()

    elif data.startswith("year_"):
        _, year, query = data.split("_", 2)
        year_movies = movies_col.find({"year": year})
        matches = [m for m in year_movies if re.search(re.escape(query), m.get("title", ""), re.IGNORECASE)]
        if matches:
            for m in matches[:RESULTS_COUNT]:
                await app.forward_messages(cq.message.chat.id, CHANNEL_ID, m["message_id"])
                await asyncio.sleep(1)
        else:
            await cq.message.reply("এই বছরে কিছু পাওয়া যায়নি।")
        await cq.answer()

    elif data.startswith("type_"):
        _, mtype, query = data.split("_", 2)
        type_movies = movies_col.find({"type": re.compile(mtype, re.IGNORECASE)})
        matches = [m for m in type_movies if re.search(re.escape(query), m.get("title", ""), re.IGNORECASE)]
        if matches:
            for m in matches[:RESULTS_COUNT]:
                await app.forward_messages(cq.message.chat.id, CHANNEL_ID, m["message_id"])
                await asyncio.sleep(1)
        else:
            await cq.message.reply("এই টাইপে কিছু পাওয়া যায়নি।")
        await cq.answer()

    elif data.startswith("has_") or data.startswith("no_") or data.startswith("soon_") or data.startswith("wrong_"):
        status, uid = data.split("_")
        tag = {"has": "✅ আছে", "no": "❌ নেই", "soon": "⏳ আসবে", "wrong": "✏️ ভুল নাম"}[status]
        await app.send_message(int(uid), f"আপনার অনুরোধের জন্য: {tag}")
        await cq.answer("ইউজারকে জানানো হয়েছে")

app.run()
