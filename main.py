# main.py

import os
import re
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from bson.regex import Regex
from rapidfuzz import fuzz
from flask import Flask
from threading import Thread

# ========== CONFIG ==========
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")  # ✅ ঠিক করে দেওয়া হলো
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))
ADMINS = list(map(int, os.environ.get("ADMINS", "").split()))

# ========== CLIENT ==========
app = Client("AutoLinkSearchBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = MongoClient(DATABASE_URL)  # ✅ এখানে ঠিক করা
db = mongo["MovieBot"]
collection = db["movies"]
feedbacks = db["feedbacks"]
stats = db["search_stats"]

# ========== CLEAN TEXT ==========
def clean_text(text):
    return re.sub(r'[^\w\s]', '', text.lower()).strip()

# ========== FLASK SERVER ==========
flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "Bot is running!"
def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)
Thread(target=run_flask).start()

# ========== SIMPLE HTTP SERVER ==========
import http.server
import socketserver
def run_http():
    PORT = 8000
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()
Thread(target=run_http).start()

# ========== SEARCH HANDLER ==========
@app.on_message(filters.private & filters.text)
async def search_handler(client, message):
    user_id = message.from_user.id
    query = message.text.strip()
    if len(query) < 2:
        return await message.reply("অনুগ্রহ করে অন্তত ২ অক্ষরের নাম দিন।")

    raw_query = query
    query = clean_text(query)

    stats.insert_one({"user_id": user_id, "query": raw_query})

    results = list(collection.find({"clean_name": Regex(query, "i")}).limit(50))

    if not results:
        all_movies = list(collection.find({}, {"clean_name": 1, "message_id": 1}))
        scored = []
        for movie in all_movies:
            score = fuzz.partial_ratio(query, movie.get("clean_name", ""))
            if score >= 70:
                scored.append((score, movie["message_id"]))
        scored.sort(reverse=True)
        results = [collection.find_one({"message_id": mid}) for _, mid in scored[:10]]

    if results:
        for result in results:
            try:
                await client.forward_messages(chat_id=message.chat.id, from_chat_id=CHANNEL_ID, message_ids=result['message_id'])
            except:
                continue
    else:
        btn = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❗️অ্যাডমিনকে জানান", callback_data=f"noresult|{raw_query}")]]
        )
        await message.reply(f"কোনো মুভি পাইনি `{raw_query}` নামে।", reply_markup=btn, quote=True)

# ========== CALLBACK: Admin Response ==========
@app.on_callback_query(filters.regex("noresult"))
async def no_result_handler(client, callback):
    data = callback.data.split("|", maxsplit=1)[-1]
    for admin_id in ADMINS:
        try:
            await client.send_message(
                admin_id,
                f"❗️কোনো রেজাল্ট মেলেনি:\n\nসার্চ: `{data}`\nUser: {callback.from_user.mention()}",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("✍️ উত্তর দিন", callback_data=f"replyto|{callback.from_user.id}|{data}")]]
                )
            )
        except: continue
    await callback.answer("অ্যাডমিনকে জানানো হয়েছে।", show_alert=True)

@app.on_callback_query(filters.regex(r"replyto\|"))
async def reply_user_response(client, callback):
    _, uid, q = callback.data.split("|", maxsplit=2)
    await callback.message.reply(f"আপনার রিপ্লাই লিখুন:\n\nসার্চ: `{q}`", quote=True)
    client.set_parse_mode("Markdown")
    client._reply_context = {"uid": int(uid), "query": q, "admin": callback.from_user.id}

@app.on_message(filters.user(ADMINS) & filters.reply)
async def reply_to_user(client, message):
    context = getattr(client, "_reply_context", None)
    if context and message.from_user.id == context["admin"]:
        try:
            await client.send_message(
                chat_id=context["uid"],
                text=f"📩 অ্যাডমিনের রিপ্লাই:\n\nসার্চ: `{context['query']}`\n\n{message.text}"
            )
            await message.reply("✉️ ইউজারকে পাঠানো হয়েছে।")
        except:
            await message.reply("❌ ইউজারকে পাঠানো যায়নি।")
        client._reply_context = None

# ========== BOT START ==========
print("Bot is running...")
app.run()
