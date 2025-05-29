# ✅ Movie Bot by @CTG_Tech with fast MongoDB regex search + admin feedback system

from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient, ASCENDING, TEXT
from flask import Flask
import os, re, asyncio
from datetime import datetime

# ✅ Configs
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DB_URL = os.getenv("DATABASE_URL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")
START_PIC = os.getenv("START_PIC", "")

# ✅ Init
app = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = MongoClient(DB_URL)
db = mongo.movie_bot
db.movies.create_index([("title", TEXT), ("year", ASCENDING)])
db.users.create_index("user_id")
db.feedback.create_index("user_id")

# ✅ Flask Server
flask_app = Flask(__name__)
@flask_app.route('/')
def index(): return 'Bot is running!'

async def auto_delete(msg: Message): await asyncio.sleep(300); await msg.delete()

def movie_markup(m):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 DOWNLOAD", url=m.get("link", UPDATE_CHANNEL))],
        [InlineKeyboardButton("🧨 Report", callback_data=f"report:{m['message_id']}")]
    ])

@app.on_message(filters.command("start") & filters.private)
async def start(_, m: Message):
    db.users.update_one({"user_id": m.from_user.id}, {"$set": {"username": m.from_user.username}}, upsert=True)
    await m.reply_photo(
        photo=START_PIC,
        caption=f"👋 Hi {m.from_user.first_name}!\n🎬 Send me a movie name to search.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Updates", url=UPDATE_CHANNEL)]
        ])
    )

@app.on_message(filters.text & filters.private & ~filters.command)
async def search_movie(_, m: Message):
    query = m.text.strip()
    user_id = m.from_user.id
    lang = None
    if "/" in query:
        parts = query.split("/")
        query = parts[0].strip()
        lang = parts[1].strip().lower()
    
    regex = re.compile(f".*{re.escape(query)}.*", re.IGNORECASE)
    filters_ = {"title": regex}
    if lang: filters_["language"] = re.compile(lang, re.IGNORECASE)

    results = list(db.movies.find(filters_).limit(RESULTS_COUNT))

    if not results:
        rid = str(datetime.now().timestamp()).replace('.', '')
        db.feedback.insert_one({"rid": rid, "user_id": user_id, "query": query})
        btns = [
            [InlineKeyboardButton("❌ Wrong Name", callback_data=f"resp:{rid}:wrong")],
            [InlineKeyboardButton("⏳ Not Released", callback_data=f"resp:{rid}:notyet")],
            [InlineKeyboardButton("📥 Uploaded", callback_data=f"resp:{rid}:uploaded")],
            [InlineKeyboardButton("🎯 Coming Soon", callback_data=f"resp:{rid}:coming")],
        ]
        for aid in ADMIN_IDS:
            await app.send_message(
                aid,
                f"❗ No result for: `{query}`\nFrom: [{m.from_user.first_name}](tg://user?id={user_id})",
                reply_markup=InlineKeyboardMarkup(btns)
            )
        await m.reply("🚫 No results found.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Google it", url=f"https://www.google.com/search?q={query} movie")]
        ]))
        return

    for res in results:
        cap = f"🎬 {res['title']} ({res.get('year', '')}) [{res.get('language', 'Unknown')}]"
        msg = await m.reply(cap, reply_markup=movie_markup(res))
        asyncio.create_task(auto_delete(msg))

@app.on_message(filters.chat(CHANNEL_ID) & filters.text)
async def save_movie(_, m: Message):
    match = re.match(r"(.+?) (\d{4}) ([A-Za-z ]+)", m.text)
    if not match: return
    title, year, language = match.groups()
    db.movies.update_one(
        {"message_id": m.id},
        {"$set": {"title": title.strip(), "year": int(year), "language": language.strip(), "message_id": m.id, "link": m.link}},
        upsert=True
    )

@app.on_callback_query(filters.regex("^report"))
async def report_cb(_, cb: CallbackQuery):
    await cb.answer("📩 Report sent to admins.", show_alert=True)

@app.on_callback_query(filters.regex("^resp:(.+):(.+)$"))
async def admin_response(_, cb: CallbackQuery):
    rid, action = cb.matches[0].groups()
    fb = db.feedback.find_one({"rid": rid})
    if not fb: return await cb.answer("⚠️ Expired", show_alert=True)
    uid = fb['user_id']
    msgs = {
        "wrong": "🚫 It seems the movie name is incorrect.",
        "notyet": "⌛ This movie hasn't been released yet.",
        "uploaded": "✅ This movie is already uploaded. Try correct name.",
        "coming": "🎯 This movie will be uploaded soon. Stay tuned!"
    }
    await app.send_message(uid, msgs.get(action, "ℹ️ Info"))
    await cb.answer("✅ Sent to user")
    db.feedback.delete_one({"rid": rid})

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, m: Message):
    total_users = db.users.count_documents({})
    total_movies = db.movies.count_documents({})
    await m.reply(f"👥 Users: {total_users}\n🎬 Movies: {total_movies}")

@app.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_IDS))
async def del_all(_, m: Message):
    db.movies.delete_many({})
    await m.reply("🗑️ All movies deleted.")

@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def del_one(_, m: Message):
    q = " ".join(m.command[1:])
    if not q: return await m.reply("❗Usage: /delete_movie <title>")
    r = db.movies.delete_one({"title": re.compile(f"^{re.escape(q)}$", re.IGNORECASE)})
    await m.reply("✅ Deleted" if r.deleted_count else "❌ Not found")

if __name__ == '__main__':
    import threading
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))).start()
    app.run()
