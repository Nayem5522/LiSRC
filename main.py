# main.py

import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from pymongo import MongoClient
from datetime import datetime
from config import BOT_TOKEN, API_ID, API_HASH, CHANNEL_ID, MONGO_URL

app = Client("Auto_Link_Search_Bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

client = MongoClient(MONGO_URL)
db = client["AutoLinkDB"]
movies_col = db["movies"]
users_col = db["users"]

# Clean text function
def clean_text(text):
    return "".join(e.lower() for e in text if e.isalnum() or e.isspace()).strip()

# Send multiple movie results
async def send_movie_results(chat_id, movie_list):
    for movie in movie_list[:5]:  # Limit to 5 results
        try:
            await app.forward_messages(chat_id, CHANNEL_ID, movie["message_id"])
            await asyncio.sleep(1.5)
        except:
            continue

# Get language filter buttons
def get_language_buttons(query):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{query}")],
        [InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{query}")],
        [InlineKeyboardButton("English", callback_data=f"lang_English_{query}")],
        [InlineKeyboardButton("All", callback_data=f"lang_All_{query}")]
    ])

@app.on_message(filters.command("start") & filters.private)
async def start(_, msg):
    await msg.reply("Hi! আমি প্রস্তুত। আপনি মুভির নাম লিখে খুঁজুন।")

@app.on_message(filters.text & (filters.private | filters.group))
async def search(_, msg):
    raw_query = msg.text.strip()
    query = clean_text(raw_query)
    users_col.update_one({"_id": msg.from_user.id}, {"$set": {"last_search": datetime.utcnow()}}, upsert=True)

    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1, "language": 1}))
    matches = []
    for m in all_movies:
        title_clean = clean_text(m.get("title", ""))
        if query in title_clean:
            matches.append(m)

    if matches:
        await send_movie_results(msg.chat.id, matches)
        reply = await msg.reply(
            f"{len(matches)} মুভি পাওয়া গেছে। আপনি চাইলে ভাষা অনুযায়ী ফিল্টার করতে পারেন:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Filter by Language", callback_data=f"filtermenu_{query}")]
            ])
        )
    else:
        reply = await msg.reply(
            "Sorry, কোনো মুভি পাওয়া যায়নি।",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ আছে", callback_data=f"has_{msg.from_user.id}"),
                    InlineKeyboardButton("❌ নেই", callback_data=f"no_{msg.from_user.id}")
                ],
                [
                    InlineKeyboardButton("⏳ আসছে", callback_data=f"soon_{msg.from_user.id}"),
                    InlineKeyboardButton("✏️ ভুল নাম", callback_data=f"wrong_{msg.from_user.id}")
                ]
            ])
        )
    await asyncio.sleep(60)
    await msg.delete()
    await reply.delete()

@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data

    if data.startswith("movie_"):
        mid = int(data.split("_")[1])
        try:
            fmsg = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
            await asyncio.sleep(30)
            await fmsg.delete()
            await cq.message.delete()
            await cq.answer()
        except:
            err = await cq.message.reply("মুভি পাঠাতে সমস্যা হয়েছে।")
            await asyncio.sleep(30)
            await err.delete()
            await cq.message.delete()
            await cq.answer()

    elif data.startswith("lang_"):
        parts = data.split("_", 2)
        if len(parts) < 3:
            await cq.answer("Invalid request", show_alert=True)
            return

        lang = parts[1]
        orig_query = parts[2]
        query = clean_text(orig_query)

        all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1, "language": 1}))
        matched = []

        for movie in all_movies:
            title = movie.get("title", "")
            title_clean = clean_text(title)
            movie_lang = movie.get("language", "Unknown")

            if lang != "All" and movie_lang.lower() != lang.lower():
                continue

            if query in title_clean:
                matched.append(movie)

        if matched:
            await send_movie_results(cq.message.chat.id, matched)
            await cq.message.edit_text(
                f"Filter: {lang} | Found {len(matched)} results for '{orig_query}'",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Change Language Filter", callback_data=f"filtermenu_{orig_query}")]
                ])
            )
            await cq.answer(f"{len(matched)} মুভি পাওয়া গেছে।")
        else:
            await cq.message.edit_text("এই ভাষায় কোনো মুভি পাওয়া যায়নি।")
            await cq.answer("No match found", show_alert=True)

    elif data.startswith("filtermenu_"):
        orig_query = data.split("_", 1)[1]
        await cq.message.edit_text(
            "ভাষা সিলেক্ট করুন:",
            reply_markup=get_language_buttons(orig_query)
        )
        await cq.answer()

    elif "_" in data:
        action, user_id = data.split("_")
        uid = int(user_id)
        responses = {
            "has": "\u2705 মুভিটি ডাটাবেজে আছে। নামটি সঠিকভাবে লিখে আবার চেষ্টা করুন।",
            "no": "\u274C এই মুভিটি ডাটাবেজে নেই।",
            "soon": "\u23F3 এই মুভিটি শিগগির আসবে।",
            "wrong": "\u270F\uFE0F নামটি ভুল হয়েছে। আবার চেষ্টা করুন।"
        }
        if action in responses:
            try:
                reply = await app.send_message(uid, responses[action])
                await cq.answer("রিপ্লাই পাঠানো হয়েছে", show_alert=True)
                await asyncio.sleep(30)
                await reply.delete()
            except:
                await cq.answer("ইউজারকে মেসেজ পাঠানো যায়নি", show_alert=True)

app.run()
