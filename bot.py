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

# Configs
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

# MongoDB setup
mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
feedback_col = db["feedback"]
stats_col = db["stats"]
users_col = db["users"]
settings_col = db["settings"]

# --- ADVANCED SEARCH: Create Text Index ---
# This index allows for efficient text searching across the 'title' field.
# You can add other fields here if you want to search across them too (e.g., "language", "year").
movies_col.create_index([("title", "text")])
movies_col.create_index("message_id")
movies_col.create_index("language")
# --- END ADVANCED SEARCH ---

# Flask
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Bot is running!"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

# Helpers
def clean_text(text):
    # This function is less critical for MongoDB text search but can be used for exact matching if needed.
    return re.sub(r'[^a-zA-Z0-9\s]', '', text).lower() # Allowed spaces for multi-word titles

def extract_year(text):
    match = re.search(r"(19|20)\d{2}", text)
    return match.group() if match else None

def extract_language(text):
    langs = ["Bengali", "Hindi", "English"]
    # Check for full word matches for better accuracy
    return next((lang for lang in langs if re.search(r'\b' + lang.lower() + r'\b', text.lower())), "Unknown")

async def delete_message_later(chat_id, message_id, delay=600):
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except Exception as e:
        print(f"Error deleting message: {e}") # Log the error for debugging

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
        # Fetch only users who want notifications
        for user in users_col.find({"notify": {"$ne": False}}):
            try:
                await app.send_message(
                    user["_id"],
                    f"নতুন মুভি আপলোড হয়েছে:\n{text.splitlines()[0][:100]}\nএখনই সার্চ করে দেখুন!"
                )
            except Exception as e:
                print(f"Error sending notification to user {user['_id']}: {e}") # Log the error

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
    # Add a filter to users_col.find() if you want to broadcast only to active users
    for user in users_col.find():
        try:
            await app.send_message(user["_id"], msg.text.split(None, 1)[1])
            count += 1
        except Exception as e:
            print(f"Error broadcasting to user {user.get('_id', 'N/A')}: {e}")
    await msg.reply(f"Broadcast sent to {count} users.")

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg):
    await msg.reply(
        f"Users: {users_col.count_documents({})}\n"
        f"Movies: {movies_col.count_documents({})}\n"
        f"Feedbacks: {feedback_col.count_documents({})}"
    )

@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_movie(_, msg):
    if len(msg.command) != 2:
        return await msg.reply("ব্যবহার: /delete_movie <movie_id>")
    try:
        movie_id = int(msg.command[1])
        result = movies_col.delete_one({"message_id": movie_id})
        if result.deleted_count:
            await msg.reply(f"✅ মুভি (ID: {movie_id}) ডিলিট করা হয়েছে।")
        else:
            await msg.reply("❌ এই ID-এর কোনো মুভি পাওয়া যায়নি।")
    except ValueError:
        await msg.reply("⚠️ Movie ID একটি সংখ্যা হওয়া প্রয়োজন।")
    except Exception as e:
        await msg.reply(f"⚠️ Error deleting movie: {e}")

@app.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_IDS))
async def delete_all_movies(_, msg):
    # Added confirmation step for this destructive command
    confirm_btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("হ্যাঁ, ডিলিট করুন", callback_data="confirm_delete_all_movies")],
        [InlineKeyboardButton("না, বাতিল করুন", callback_data="cancel_delete_all_movies")]
    ])
    await msg.reply("আপনি কি নিশ্চিত যে আপনি সমস্ত মুভি ডিলিট করতে চান? এই কাজটি পূর্বাবস্থায় ফেরানো যাবে না।", reply_markup=confirm_btn)

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

# --- ADVANCED SEARCH: Main Search Handler ---
@app.on_message(filters.text & filters.private & ~filters.command(["start", "feedback", "broadcast", "stats", "delete_movie", "delete_all_movies", "notify"]))
async def search(_, msg):
    raw_query = msg.text.strip()
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"last_search": datetime.utcnow()}},
        upsert=True
    )

    loading = await msg.reply("🔎 লোড হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")

    # MongoDB Text Search: Finds documents where the 'title' field contains the search term.
    # It also returns a 'textScore' for relevance, which we use for sorting.
    search_results = list(movies_col.find(
        {"$text": {"$search": raw_query}},
        {"score": {"$meta": "textScore"}, "title": 1, "message_id": 1, "language": 1} # Include necessary fields
    ).sort([("score", {"$meta": "textScore"})]).limit(RESULTS_COUNT))

    if search_results:
        await loading.delete()
        buttons = []
        for m in search_results:
            title = m.get("title", "")
            # Truncate title if too long for inline button
            if len(title) > 40:
                title = title[:37] + "..."
            buttons.append([InlineKeyboardButton(title, callback_data=f"movie_{m['message_id']}")])

        # Language filter buttons - useful after an initial search
        lang_buttons = [
            InlineKeyboardButton("Bengali", callback_data=f"lang_Bengali_{urllib.parse.quote(raw_query)}"),
            InlineKeyboardButton("Hindi", callback_data=f"lang_Hindi_{urllib.parse.quote(raw_query)}"),
            InlineKeyboardButton("English", callback_data=f"lang_English_{urllib.parse.quote(raw_query)}")
        ]
        buttons.append(lang_buttons)

        # Year filter buttons - dynamically generate for recent years
        current_year = datetime.now().year
        year_buttons_row = []
        for year_offset in range(5): # Last 5 years
            year = current_year - year_offset
            year_buttons_row.append(InlineKeyboardButton(str(year), callback_data=f"year_{year}_{urllib.parse.quote(raw_query)}"))
        buttons.append(year_buttons_row)


        m = await msg.reply("আপনার মুভির নাম মিলতে পারে, নিচের থেকে সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(buttons))
        asyncio.create_task(delete_message_later(m.chat.id, m.id))
        return
    else:
        # If no results found with text search, proceed to the admin notification and Google search
        await loading.delete()
        google_search_url = "https://www.google.com/search?q=" + urllib.parse.quote(raw_query)
keyboard = [
    [InlineKeyboardButton("Search on Google", url=google_search_url)]
])
        alert = await msg.reply(
            "কোনও ফলাফল পাওয়া যায়নি। অ্যাডমিনকে জানানো হয়েছে। নিচের বাটনে ক্লিক করে গুগলে সার্চ করুন।",
            reply_markup=google_button
        )
        asyncio.create_task(delete_message_later(alert.chat.id, alert.id))

        btn = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ মুভি আছে", callback_data=f"has_{msg.chat.id}_{msg.id}_{urllib.parse.quote(raw_query)}"),
                InlineKeyboardButton("❌ নেই", callback_data=f"no_{msg.chat.id}_{msg.id}_{urllib.parse.quote(raw_query)}")
            ],
            [
                InlineKeyboardButton("⏳ আসবে", callback_data=f"soon_{msg.chat.id}_{msg.id}_{urllib.parse.quote(raw_query)}"),
                InlineKeyboardButton("✏️ ভুল নাম", callback_data=f"wrong_{msg.chat.id}_{msg.id}_{urllib.parse.quote(raw_query)}")
            ]
        ])
        for admin_id in ADMIN_IDS:
            await app.send_message(
                admin_id,
                f"❗ ইউজার `{msg.from_user.id}` `{msg.from_user.first_name}` খুঁজেছে: **{raw_query}**\nফলাফল পাওয়া যায়নি। নিচে বাটন থেকে উত্তর দিন।",
                reply_markup=btn
            )

# --- ADVANCED SEARCH: Callback Query Handlers ---
@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data

    if data.startswith("movie_"):
        mid = int(data.split("_")[1])
        fwd = await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
        await cq.message.reply("⚠️ এই মুভিটি 10 মিনিট পর অটো ডিলিট হয়ে যাবে।")
        asyncio.create_task(delete_message_later(cq.message.chat.id, fwd.id))
        await cq.answer("মুভি পাঠানো হয়েছে।", show_alert=False) # show_alert=False for non-intrusive feedback

    elif data.startswith("lang_"):
        _, lang, raw_query = data.split("_", 2)
        # Decode the query from URL encoding
        decoded_query = urllib.parse.unquote(raw_query)

        # Filter by language and use text search for the query
        lang_movies = list(movies_col.find(
            {"language": lang, "$text": {"$search": decoded_query}},
            {"score": {"$meta": "textScore"}, "title": 1, "message_id": 1}
        ).sort([("score", {"$meta": "textScore"})]).limit(RESULTS_COUNT))

        if lang_movies:
            buttons = [
                [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")]
                for m in lang_movies
            ]
            await cq.message.edit_text(
                f"ফলাফল ({lang}) - নিচের থেকে সিলেক্ট করুন:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await cq.answer(f"এই ({lang}) ভাষায় '{decoded_query}' এর জন্য কিছু পাওয়া যায়নি।", show_alert=True)
        await cq.answer() # Acknowledge the callback

    elif data.startswith("year_"):
        _, year, raw_query = data.split("_", 2)
        decoded_query = urllib.parse.unquote(raw_query)

        # Filter by year and use text search for the query
        year_movies = list(movies_col.find(
            {"year": year, "$text": {"$search": decoded_query}},
            {"score": {"$meta": "textScore"}, "title": 1, "message_id": 1}
        ).sort([("score", {"$meta": "textScore"})]).limit(RESULTS_COUNT))

        if year_movies:
            buttons = [
                [InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")]
                for m in year_movies
            ]
            await cq.message.edit_text(
                f"ফলাফল ({year} সাল) - নিচের থেকে সিলেক্ট করুন:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await cq.answer(f"এই ({year}) সালে '{decoded_query}' এর জন্য কিছু পাওয়া যায়নি।", show_alert=True)
        await cq.answer()

    elif data == "confirm_delete_all_movies":
        if cq.from_user.id in ADMIN_IDS: # Ensure only admins can confirm
            result = movies_col.delete_many({})
            await cq.message.edit_text(f"🗑️ মোট {result.deleted_count} টি মুভি ডিলিট করা হয়েছে।")
        else:
            await cq.answer("আপনার এই অনুমতি নেই।", show_alert=True)
        await cq.answer()

    elif data == "cancel_delete_all_movies":
        await cq.message.edit_text("❌ সমস্ত মুভি ডিলিট করার অনুরোধ বাতিল করা হয়েছে।")
        await cq.answer()

    elif "_" in data:
        parts = data.split("_", 3)
        if len(parts) == 4:
            action, uid, mid, raw_query = parts
            uid = int(uid)
            # Decode the raw_query from URL encoding for display
            decoded_query = urllib.parse.unquote(raw_query)
            responses = {
                "has": f"✅ @{cq.from_user.username or cq.from_user.first_name} জানিয়েছেন যে **{decoded_query}** মুভিটি ডাটাবেজে আছে। সঠিক নাম লিখে আবার চেষ্টা করুন।",
                "no": f"❌ @{cq.from_user.username or cq.from_user.first_name} জানিয়েছেন যে **{decoded_query}** মুভিটি ডাটাবেজে নেই।",
                "soon": f"⏳ @{cq.from_user.username or cq.from_user.first_name} জানিয়েছেন যে **{decoded_query}** মুভিটি শীঘ্রই আসবে।",
                "wrong": f"✏️ @{cq.from_user.username or cq.from_user.first_name} বলছেন যে আপনি ভুল নাম লিখেছেন: **{decoded_query}**।"
            }
            if action in responses:
                m = await app.send_message(uid, responses[action])
                asyncio.create_task(delete_message_later(m.chat.id, m.id))
                await cq.answer("অ্যাডমিনের পক্ষ থেকে উত্তর পাঠানো হয়েছে।")
            else:
                await cq.answer()
# --- END ADVANCED SEARCH ---

if __name__ == "__main__":
    print("Bot is starting...")
    app.run()
