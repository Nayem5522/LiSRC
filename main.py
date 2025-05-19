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
from difflib import SequenceMatcher

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

mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
feedback_col = db["feedback"]
stats_col = db["stats"]
users_col = db["users"]
settings_col = db["settings"]

movies_col.create_index([("title", ASCENDING)])
movies_col.create_index("message_id")
movies_col.create_index("language")

flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Bot is running!"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

def refine_query(raw_text):
    stop_words = ["full", "hd", "movie", "hindi", "english", "bengali", "720p", "1080p"]
    words = raw_text.lower().split()
    refined = [w for w in words if w not in stop_words]
    return " ".join(refined)

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
    except:
        pass

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
    await msg.reply(
        f"Users: {users_col.count_documents({})}\n"
        f"Movies: {movies_col.count_documents({})}\n"
        f"Feedbacks: {feedback_col.count_documents({})}"
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

@app.on_message(filters.text)
async def search(_, msg):
    raw_query = msg.text.strip()
    refined = refine_query(raw_query)
    query = clean_text(refined)

    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"last_search": datetime.utcnow()}},
        upsert=True
    )

    loading = await msg.reply("\ud83d\udd0e \u09b2\u09cb\u09a1 \u09b9\u099a\u09cd\u099b\u09c7, \u0985\u09a8\u09c1\u0997\u09cd\u09b0\u09b9 \u0995\u09b0\u09c7 \u0985\u09aa\u09c7\u0995\u09cd\u09b7\u09be \u0995\u09b0\u09c1\u09a8...")
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1, "language": 1}))

    def is_similar(title):
        refined_title = clean_text(refine_query(title))
        ratio = SequenceMatcher(None, query, refined_title).ratio()
        return ratio >= 0.5

    matches = [m for m in all_movies if is_similar(m.get("title", ""))]

    if matches:
        await loading.delete()
        lang_buttons = [
            InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{query}"),
            InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{query}"),
            InlineKeyboardButton("English", callback_data=f"lang_English_{query}")
        ]
        buttons = [
            [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")]
            for m in matches[:RESULTS_COUNT]
        ]
        buttons.append(lang_buttons)
        m = await msg.reply("\u0986\u09aa\u09a8\u09be\u09b0 \u09ae\u09c1\u09ad\u09bf\u09b0 \u09a8\u09be\u09ae \u09ae\u09bf\u09b2\u09a4\u09c7 \u09aa\u09be\u09b0\u09c7, \u09a8\u09bf\u099a\u09c7\u09b0 \u09a5\u09c7\u0995\u09c7 \u09b8\u09bf\u09b2\u09c7\u0995\u09cd\u099f \u0995\u09b0\u09c1\u09a8:", reply_markup=InlineKeyboardMarkup(buttons))
        asyncio.create_task(delete_message_later(m.chat.id, m.id))
        return

    await loading.delete()
    google_search_url = "https://www.google.com/search?q=" + urllib.parse.quote(raw_query)
    google_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("Search on Google", url=google_search_url)]
    ])
    alert = await msg.reply(
        "\u0995\u09cb\u09a8\u09cb \u09ab\u09b2\u09be\u09ab\u09b2 \u09aa\u09be\u0993\u09df\u09be \u0997\u09df\u09c7\u09a8\u09bf \u09a8\u09be। \u0985\u09cd\u09af\u09be\u09a1\u09ae\u09bf\u09a8\u0995\u09c7 \u099c\u09be\u09a8\u09be\u09a8\u09cb \u09b9\u09df\u09c7\u099b\u09c7। \u09a8\u09bf\u099a\u09c7\u09b0 \u09ac\u09be\u099f\u09a8\u09c7 \u0995\u09cd\u09b2\u09bf\u0995 \u0995\u09b0\u09c7 \u0997\u09c1\u0997\u09b2\u09c7 \u09b8\u09be\u09b0\u09cd\u099a \u0995\u09b0\u09c1\u09a8।",
        reply_markup=google_button
    )
    asyncio.create_task(delete_message_later(alert.chat.id, alert.id))

    btn = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2705 \u09ae\u09c1\u09ad\u09bf \u0986\u099b\u09c7", callback_data=f"has_{msg.chat.id}_{msg.id}_{raw_query}"),
            InlineKeyboardButton("\u274c \u09a8\u09c7\u0987", callback_data=f"no_{msg.chat.id}_{msg.id}_{raw_query}")
        ],
        [
            InlineKeyboardButton("\u23f3 \u0986\u09b8\u09ac\u09c7", callback_data=f"soon_{msg.chat.id}_{msg.id}_{raw_query}"),
            InlineKeyboardButton("\u270f\ufe0f \u09ad\u09c1\u09b2 \u09a8\u09be\u09ae", callback_data=f"wrong_{msg.chat.id}_{msg.id}_{raw_query}")
        ]
    ])
    for admin_id in ADMIN_IDS:
        await app.send_message(
            admin_id,
            f"\u2757 \u0987\u0989\u099c\u09be\u09b0 `{msg.from_user.id}` `{msg.from_user.first_name}` \u0996\u09c1\u099c\u09c7\u099b\u09c7: **{raw_query}**\n\u09ab\u09b2\u09be\u09ab\u09b2 \u09aa\u09be\u0993\u09df\u09be \u0997\u09df\u09c7\u09a8\u09bf \u09a8\u09be। \u09a8\u09bf\u099a\u09c7 \u09ac\u09be\u099f\u09a8 \u09a5\u09c7\u0995\u09c7 \u0989\u09a4\u09cd\u09a4\u09b0 \u09a6\u09bf\u09a8।",
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
            if re.search(re.escape(query), clean_text(refine_query(m.get("title", ""))), re.IGNORECASE)
        ]
        if matches:
            buttons = [
                [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")]
                for m in matches[:RESULTS_COUNT]
            ]
            await cq.message.edit_text(
                f"ফলাফল ({lang}) - নিচের থেকে সিলেক্ট করুন:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await cq.answer("এই ভাষায় কিছু পাওয়া যায়নি।", show_alert=True)
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
                m = await app.send_message(uid, responses[action])
                asyncio.create_task(delete_message_later(m.chat.id, m.id))
                await cq.answer("অ্যাডমিনের পক্ষ থেকে উত্তর পাঠানো হয়েছে।")
            else:
                await cq.answer()

if __name__ == "__main__":
    print("Bot is starting...")
    app.run()
