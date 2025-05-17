import asyncio
import os
import re
from datetime import datetime
from threading import Thread

from flask import Flask
from googlesearch import search
from pymongo import MongoClient, ASCENDING
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

# Configurations - environment variables থেকে নেবে
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")
START_PIC = os.getenv(
    "START_PIC",
    "https://i.ibb.co/prnGXMr3/photo-2025-05-16-05-15-45-7504908428624527364.jpg",
)

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# MongoDB setup
mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
feedback_col = db["feedback"]
stats_col = db["stats"]
users_col = db["users"]
settings_col = db["settings"]

# Indexes for faster search
movies_col.create_index([("title", ASCENDING)])
movies_col.create_index("message_id")
movies_col.create_index("language")

# Flask app for Render/Koyeb ping
flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot is running!"


Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()


# Helper functions
def clean_text(text):
    return re.sub(r"[^a-zA-Z0-9]", "", text.lower())


def extract_year(text):
    match = re.search(r"(19|20)\d{2}", text)
    return match.group() if match else None


def extract_language(text):
    langs = ["Bengali", "Hindi", "English"]
    return next((lang for lang in langs if lang.lower() in text.lower()), "Unknown")


def get_google_suggestion(query):
    try:
        results = list(search(query + " movie", num_results=3))
        return results[0] if results else None
    except Exception:
        return None


async def delete_message_later(chat_id, message_id, delay=600):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except Exception:
        pass


# When a new movie post arrives in the channel, save it in DB
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
        "language": extract_language(text),
    }
    movies_col.update_one({"message_id": msg.id}, {"$set": movie}, upsert=True)

    setting = settings_col.find_one({"key": "global_notify"})
    if setting and setting.get("value"):
        for user in users_col.find({"notify": {"$ne": False}}):
            try:
                await app.send_message(
                    user["_id"],
                    f"নতুন মুভি আপলোড হয়েছে:\n{text.splitlines()[0][:100]}\nএখনই সার্চ করে দেখুন!",
                )
            except Exception:
                pass


# /start command
@app.on_message(filters.command("start"))
async def start(_, msg: Message):
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"joined": datetime.utcnow()}},
        upsert=True,
    )
    btns = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Update Channel", url=UPDATE_CHANNEL)],
            [InlineKeyboardButton("Contact Admin", url="https://t.me/ctgmovies23")],
        ]
    )
    await msg.reply_photo(
        photo=START_PIC, caption="Send me a movie name to search.", reply_markup=btns
    )


# /feedback command
@app.on_message(filters.command("feedback") & filters.private)
async def feedback(_, msg):
    if len(msg.command) < 2:
        return await msg.reply("Please write something after /feedback.")
    feedback_col.insert_one(
        {
            "user": msg.from_user.id,
            "text": msg.text.split(None, 1)[1],
            "time": datetime.utcnow(),
        }
    )
    m = await msg.reply("Thanks for your feedback!")
    asyncio.create_task(delete_message_later(m.chat.id, m.id))


# /broadcast (admin only)
@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(_, msg):
    if len(msg.command) < 2:
        return await msg.reply("Usage: /broadcast Your message here")
    count = 0
    for user in users_col.find():
        try:
            await app.send_message(user["_id"], msg.text.split(None, 1)[1])
            count += 1
        except Exception:
            pass
    await msg.reply(f"Broadcast sent to {count} users.")


# /stats (admin only)
@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg):
    await msg.reply(
        f"Users: {users_col.count_documents({})}\n"
        f"Movies: {movies_col.count_documents({})}\n"
        f"Feedbacks: {feedback_col.count_documents({})}"
    )


# /notify on|off (admin only)
@app.on_message(filters.command("notify") & filters.user(ADMIN_IDS))
async def notify_command(_, msg: Message):
    if len(msg.command) != 2 or msg.command[1] not in ["on", "off"]:
        return await msg.reply("ব্যবহার: /notify on  অথবা  /notify off")
    new_value = True if msg.command[1] == "on" else False
    settings_col.update_one(
        {"key": "global_notify"}, {"$set": {"value": new_value}}, upsert=True
    )
    status = "enabled" if new_value else "disabled"
    await msg.reply(f"✅ Global notifications {status}!")


# Search handler for normal text messages
@app.on_message(filters.text)
async def search(_, msg):
    raw_query = msg.text.strip()
    query = clean_text(raw_query)
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"last_search": datetime.utcnow()}},
        upsert=True,
    )
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1, "language": 1}))

    # Try exact matches first
    exact_match = [m for m in all_movies if clean_text(m.get("title", "")) == query]
    if exact_match:
        for m in exact_match[:RESULTS_COUNT]:
            forwarded_message = await app.forward_messages(
                msg.chat.id, CHANNEL_ID, m["message_id"]
            )
            asyncio.create_task(delete_message_later(msg.chat.id, forwarded_message.id))
            await asyncio.sleep(0.7)
        return

    # Partial suggestions
    suggestions = [
        m
        for m in all_movies
        if re.search(re.escape(raw_query), m.get("title", ""), re.IGNORECASE)
    ]
    if suggestions:
        lang_buttons = [
            InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{query}"),
            InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{query}"),
            InlineKeyboardButton("English", callback_data=f"lang_English_{query}"),
        ]
        buttons = [
            [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")]
            for m in suggestions[:RESULTS_COUNT]
        ]
        buttons.append(lang_buttons)
        m = await msg.reply(
            "আপনার মুভির নাম মিলতে পারে, নিচের থেকে সিলেক্ট করুন:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        asyncio.create_task(delete_message_later(m.chat.id, m.id))
        return

    # No results found - notify admins with buttons for feedback
    alert = await msg.reply("কোনও ফলাফল পাওয়া যায়নি। অ্যাডমিনকে জানানো হয়েছে।")
    asyncio.create_task(delete_message_later(alert.chat.id, alert.id))

    btn = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ মুভি আছে", callback_data=f"has_{msg.chat.id}_{msg.id}_{raw_query}"
                ),
                InlineKeyboardButton(
                    "❌ নেই", callback_data=f"no_{msg.chat.id}_{msg.id}_{raw_query}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "⏳ আসবে", callback_data=f"soon_{msg.chat.id}_{msg.id}_{raw_query}"
                ),
                InlineKeyboardButton(
                    "✏️ ভুল নাম", callback_data=f"wrong_{msg.chat.id}_{msg.id}_{raw_query}"
                ),
            ],
        ]
    )

    for admin_id in ADMIN_IDS:
        await app.send_message(
            admin_id,
            f"❗ ইউজার `{msg.from_user.id}` `{msg.from_user.first_name}` খুঁজেছে: **{raw_query}**\n"
            "ফলাফল পাওয়া যায়নি। নিচে বাটন থেকে উত্তর দিন।",
            reply_markup=btn,
        )


# Callback query handler
@app.on_callback_query(filters.regex("^(has|no|soon|wrong|movie|lang)_"))
async def handle_callback(client, cq: CallbackQuery):
    data = cq.data

    if data.startswith(("has_", "no_", "soon_", "wrong_")):
        parts = data.split("_", 3)
        if len(parts) == 4:
            action, chat_id, message_id, raw_query = parts
            chat_id, message_id = int(chat_id), int(message_id)

            if action == "wrong":
                suggestion = get_google_suggestion(raw_query)
                suggestion_text = (
                    f"\n\nআপনি হয়তো খুঁজছিলেন:\n👉 {suggestion}" if suggestion else ""
                )
                response = (
                    f"✏️ @{cq.from_user.username or cq.from_user.first_name} বলছেন যে আপনি ভুল নাম লিখেছেন: **{raw_query}**।{suggestion_text}"
                )
            else:
                responses = {
                    "has": f"✅ @{cq.from_user.username or cq.from_user.first_name} জানিয়েছেন যে **{raw_query}** মুভিটি ডাটাবেজে আছে। সঠিক নাম লিখে আবার চেষ্টা করুন।",
                    "no": f"❌ @{cq.from_user.username or cq.from_user.first_name} জানিয়েছেন যে **{raw_query}** মুভিটি ডাটাবেজে নেই।",
                    "soon": f"⏳ @{cq.from_user.username or cq.from_user.first_name} জানিয়েছেন যে **{raw_query}** মুভিটি শীঘ্রই আসবে।",
                }
                response = responses.get(action)

            if response:
                m = await app.send_message(chat_id, response)
                asyncio.create_task(delete_message_later(m.chat.id, m.id))
                await cq.answer("অ্যাডমিনের পক্ষ থেকে উত্তর পাঠানো হয়েছে।")
            else:
                await cq.answer()
        else:
            await cq.answer()

    elif data.startswith("movie_"):
        mid = int(data.split("_")[1])
        forwarded_message = await app.forward_messages(
            cq.message.chat.id, CHANNEL_ID, mid
        )
        asyncio.create_task(delete_message_later(cq.message.chat.id, forwarded_message.id))
        await cq.answer("মুভি পাঠানো হয়েছে।")

    elif data.startswith("lang_"):
        _, lang, query = data.split("_", 2)
        lang_movies = list(movies_col.find({"language": lang}))
        matches = [
            m for m in lang_movies if re.search(re.escape(query), m.get("title", ""), re.IGNORECASE)
        ]
        if matches:
            buttons = [
                [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")]
                for m in matches[:RESULTS_COUNT]
            ]
            await cq.message.edit(
                f"ভাষা অনুযায়ী ফলাফল ({lang}):",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            await cq.answer()
        else:
            await cq.answer("কোনও ফলাফল পাওয়া যায়নি।")

    else:
        await cq.answer()


if __name__ == "__main__":
    print("Bot is starting...")
    app.run()
