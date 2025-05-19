import asyncio
import re
import urllib.parse
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from rapidfuzz import process, fuzz
from pymongo import MongoClient

# ====== CONFIGURATION ======
API_ID = 1234567  # তোমার API_ID
API_HASH = "your_api_hash"  # তোমার API_HASH
BOT_TOKEN = "your_bot_token"  # তোমার বট টোকেন

CHANNEL_ID = -1001234567890  # তোমার চ্যানেলের আইডি (যেখান থেকে মুভি মেসেজ আসবে)

MONGO_URI = "mongodb://localhost:27017"  # MongoDB URI
DB_NAME = "moviebotdb"
MOVIES_COLLECTION = "movies"
USERS_COLLECTION = "users"

ADMIN_IDS = [123456789, 987654321]  # তোমার অ্যাডমিন ইউজার আইডি লিস্ট

RESULTS_COUNT = 10  # সর্বোচ্চ কতগুলো সাজেশন দেখাবে

# ===========================

app = Client("moviebot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
movies_col = db[MOVIES_COLLECTION]
users_col = db[USERS_COLLECTION]

# Helper: Clean text for search
def clean_text(text):
    return re.sub(r"[^a-zA-Z0-9\s]", "", text).strip().lower()

# Helper: Delete message later (10 seconds)
async def delete_message_later(chat_id, message_id, delay=10):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except Exception:
        pass

# --- DEBUG: log all incoming messages ---
@app.on_message()
async def debug_all_messages(client, message):
    print(f"[DEBUG] Incoming message: {message.text if message.text else 'No text'} from user {message.from_user.id if message.from_user else 'unknown'}")

# --- Main search handler ---
@app.on_message(filters.text & ~filters.private)
async def search(_, msg):
    print(f"[DEBUG] Received message from user_id={msg.from_user.id if msg.from_user else 'unknown'}: {msg.text}")
    try:
        raw_query = msg.text.strip()
        if len(raw_query) < 3:
            return await msg.reply("অনুগ্রহ করে আরও নির্দিষ্ট একটি নাম লিখুন (কমপক্ষে ৩ অক্ষর)।")

        query = clean_text(raw_query)
        users_col.update_one(
            {"_id": msg.from_user.id},
            {"$set": {"last_search": datetime.utcnow()}},
            upsert=True
        )

        loading = await msg.reply("🔎 লোড হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")

        all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1, "language": 1}))

        movie_titles = [m["title"] for m in all_movies]
        matched = process.extract(raw_query, movie_titles, scorer=fuzz.partial_ratio, limit=RESULTS_COUNT)
        matched_titles = [match[0] for match in matched if match[1] >= 50]
        suggestions = [m for m in all_movies if m["title"] in matched_titles]

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
    except Exception as e:
        print(f"[ERROR] Exception in search handler: {e}")
        await msg.reply("দুঃখিত, সার্চের সময় ত্রুটি ঘটেছে।")

# --- Callback query handler ---
@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    print(f"[DEBUG] Callback query data: {cq.data} from user {cq.from_user.id if cq.from_user else 'unknown'}")
    data = cq.data

    if data.startswith("movie_"):
        try:
            mid = int(data.split("_")[1])
            fwd = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
            asyncio.create_task(delete_message_later(cq.message.chat.id, fwd.id))
            await cq.answer("মুভি পাঠানো হয়েছে।")
        except Exception as e:
            print(f"[ERROR] Forwarding movie failed: {e}")
            await cq.answer("মুভি পাঠানো সম্ভব হয়নি।")

    elif data.startswith("lang_"):
        try:
            _, lang, query = data.split("_", 2)
            lang_movies = list(movies_col.find({"language": lang}))
            matches = [
                m for m in lang_movies
                if re.search(re.escape(query), m.get("title", ""), re.IGNORECASE)
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
        except Exception as e:
            print(f"[ERROR] Language filter error: {e}")
            await cq.answer("ত্রুটি ঘটেছে।")

    elif "_" in data:
        parts = data.split("_", 3)
        if len(parts) == 4:
            action, uid, mid, raw_query = parts
            try:
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
            except Exception as e:
                print(f"[ERROR] Admin reply error: {e}")
                await cq.answer()

# --- Start the bot ---
print("Bot is starting...")
app.run()
