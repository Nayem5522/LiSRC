import os
import asyncio
import logging
import urllib.parse
from datetime import datetime, timedelta

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from rapidfuzz import process, fuzz

logging.basicConfig(level=logging.INFO)

API_ID = int(os.getenv("API_ID", "12345"))
API_HASH = os.getenv("API_HASH", "your_api_hash")
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token")
MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://...")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001234567890"))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "123456789").split()))

RESULTS_COUNT = 10

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = MongoClient(MONGO_URL)
db = mongo["movie_bot_db"]
movies_col = db["movies"]
users_col = db["users"]
notify_col = db["notify"]
feedback_col = db["feedback"]

def clean_text(text):
    return text.lower().strip()

async def delete_message_later(chat_id, message_id, delay=600):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except Exception:
        pass

@app.on_message(filters.command("start"))
async def start_handler(_, msg):
    await msg.reply_text(
        f"হ্যালো {msg.from_user.first_name}!\n"
        "আমি তোমার মুভি সার্চ এবং ডাউনলোড সহায়ক বট।\n"
        "মুভির নাম লিখে সার্চ করো।\n\n"
        "/feedback দিয়ে তোমার মতামত পাঠাও।"
    )

@app.on_message(filters.text & ~filters.command)
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
    # First exact match
    exact_match = [m for m in all_movies if clean_text(m.get("title", "")) == query]

    if exact_match:
        await loading.delete()
        for m in exact_match[:RESULTS_COUNT]:
            fwd = await app.forward_messages(msg.chat.id, CHANNEL_ID, m["message_id"])
            warning_msg = await msg.reply("⚠️ এই মুভিটি ১০ মিনিট পর অটো ডিলিট হবে।")
            asyncio.create_task(delete_message_later(msg.chat.id, fwd.id))
            asyncio.create_task(delete_message_later(warning_msg.chat.id, warning_msg.id))
            await asyncio.sleep(0.7)
        return

    # fuzzy match with rapidfuzz
    titles_dict = {m["title"]: m for m in all_movies if "title" in m}
    matches = process.extract(raw_query, titles_dict.keys(), scorer=fuzz.token_sort_ratio, limit=RESULTS_COUNT)
    filtered_matches = [titles_dict[match[0]] for match in matches if match[1] >= 70]

    if filtered_matches:
        await loading.delete()
        lang_buttons = [
            InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{query}"),
            InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{query}"),
            InlineKeyboardButton("English", callback_data=f"lang_English_{query}")
        ]
        buttons = [[
            InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")
        ] for m in filtered_matches]
        buttons.append(lang_buttons)
        sent = await msg.reply("আপনার মুভির নাম মিলতে পারে, নিচের থেকে সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(buttons))
        asyncio.create_task(delete_message_later(sent.chat.id, sent.id))
        return

    await loading.delete()

    # Notify admin with buttons about missing movie
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
async def callback_handler(_, cb):
    data = cb.data
    if data.startswith("movie_"):
        msg_id = int(data.split("_")[1])
        fwd = await app.forward_messages(cb.message.chat.id, CHANNEL_ID, msg_id)
        warning_msg = await cb.message.reply("⚠️ এই মুভিটি ১০ মিনিট পর অটো ডিলিট হবে।")
        asyncio.create_task(delete_message_later(cb.message.chat.id, fwd.id))
        asyncio.create_task(delete_message_later(warning_msg.chat.id, warning_msg.id))
        await cb.answer()
    elif data.startswith(("lang_")):
        # Implement language filter here if needed
        await cb.answer("Language filtering is under development.")
    elif data.startswith(("has_", "no_", "soon_", "wrong_")):
        # Admin feedback buttons callback
        await cb.answer("Thanks for your feedback.")
    else:
        await cb.answer()

@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_movie_cmd(_, msg):
    if len(msg.command) < 2:
        await msg.reply("ব্যবহার: /delete_movie <message_id>")
        return
    message_id = int(msg.command[1])
    res = movies_col.delete_one({"message_id": message_id})
    if res.deleted_count:
        await msg.reply(f"✅ মুভি মেসেজ ID `{message_id}` ডিলেট করা হয়েছে।")
    else:
        await msg.reply(f"⚠️ মুভি মেসেজ ID `{message_id}` পাওয়া যায়নি।")

@app.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_IDS))
async def delete_all_movies_cmd(_, msg):
    movies_col.delete_many({})
    await msg.reply("✅ সব মুভি ডাটাবেজ থেকে মুছে ফেলা হয়েছে।")

@app.on_message(filters.command("notify") & filters.user(ADMIN_IDS))
async def notify_cmd(_, msg):
    if len(msg.command) < 2 or msg.command[1].lower() not in ["on", "off"]:
        await msg.reply("ব্যবহার: /notify on বা /notify off")
        return
    state = msg.command[1].lower()
    notify_col.update_one({"_id": "global_notify"}, {"$set": {"enabled": state=="on"}}, upsert=True)
    await msg.reply(f"নোটিফিকেশন {'চালু' if state=='on' else 'বন্ধ'} করা হয়েছে।")

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast_cmd(_, msg):
    text = msg.text.partition(" ")[2]
    if not text:
        await msg.reply("ব্যবহার: /broadcast <মেসেজ>")
        return
    all_users = users_col.find({})
    count = 0
    for user in all_users:
        try:
            await app.send_message(user["_id"], text)
            count += 1
            await asyncio.sleep(0.05)  # rate limit avoid
        except Exception:
            pass
    await msg.reply(f"ব্রডকাস্ট সম্পন্ন হয়েছে। মোট পাঠানো হয়েছে: {count}")

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats_cmd(_, msg):
    total_users = users_col.count_documents({})
    total_movies = movies_col.count_documents({})
    notify_data = notify_col.find_one({"_id": "global_notify"})
    notify_status = "চালু" if notify_data and notify_data.get("enabled") else "বন্ধ"
    await msg.reply(
        f"স্ট্যাটস:\n"
        f"👥 মোট ইউজার: {total_users}\n"
        f"🎬 মোট মুভি: {total_movies}\n"
        f"🔔 নোটিফিকেশন: {notify_status}"
    )

@app.on_message(filters.command("feedback"))
async def feedback_handler(_, msg):
    text = msg.text.partition(" ")[2]
    if not text:
        await msg.reply("দয়া করে /feedback <তোমার মতামত> লিখুন।")
        return
    feedback_col.insert_one({
        "user_id": msg.from_user.id,
        "username": msg.from_user.username,
        "feedback": text,
        "date": datetime.utcnow()
    })
    await msg.reply("তোমার মতামতের জন্য ধন্যবাদ!")

@app.on_message(filters.command("view_feedback") & filters.user(ADMIN_IDS))
async def view_feedback_cmd(_, msg):
    all_feedback = list(feedback_col.find({}).sort("date", -1).limit(20))
    if not all_feedback:
        await msg.reply("কোনো ফিডব্যাক পাওয়া যায়নি।")
        return
    text = "\n\n".join(
        f"User: {f.get('username') or f.get('user_id')}\nDate: {f.get('date').strftime('%Y-%m-%d %H:%M')}\nFeedback: {f.get('feedback')}"
        for f in all_feedback
    )
    await msg.reply(text)

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
