from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient, ASCENDING
from pymongo.errors import OperationFailure, CollectionInvalid, DuplicateKeyError
from flask import Flask
from threading import Thread
import os
import re
from datetime import datetime
import asyncio
import urllib.parse
from fuzzywuzzy import process
from concurrent.futures import ThreadPoolExecutor

# Configs - নিশ্চিত করুন এই ভেরিয়েবলগুলো আপনার এনভায়রনমেন্টে সেট করা আছে।
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

# Indexing - Optimized for faster search
# এই অংশটি MongoDB তে প্রয়োজনীয় ইন্ডেক্স তৈরি বা আপডেট করবে।
try:
    # Attempt to drop the conflicting 'message_id_1' index if it exists.
    movies_col.drop_index("message_id_1")
    print("Existing 'message_id_1' index dropped successfully (if it existed).")
except Exception as e:
    if "index not found" not in str(e):
        print(f"Error dropping existing index 'message_id_1': {e}")
    else:
        print("'message_id_1' index not found, proceeding with creation.")

try:
    # Ensure the unique index on 'message_id' is created.
    movies_col.create_index("message_id", unique=True, background=True)
    print("Index 'message_id' (unique) ensured successfully.")
except DuplicateKeyError as e:
    print(f"Error: Cannot create unique index on 'message_id' due to duplicate entries. "
          f"Please clean your database manually if this persists. Error: {e}")
except OperationFailure as e:
    print(f"Error creating index 'message_id': {e}")

# Ensure other critical indexes are always created.
movies_col.create_index("language", background=True)
movies_col.create_index([("title_clean", ASCENDING)], background=True)
movies_col.create_index([("language", ASCENDING), ("title_clean", ASCENDING)], background=True)
print("All other necessary indexes ensured successfully.")

# Flask App for health check
# এটি বটের সার্ভার সচল আছে কিনা তা পরীক্ষা করার জন্য ব্যবহৃত হয়।
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Bot is running!"
Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

# Initialize a global ThreadPoolExecutor for running blocking functions (like fuzzywuzzy)
# ফাজিউজি (fuzzywuzzy) একটি CPU-ইনটেনসিভ অপারেশন, তাই এটি থ্রেড পুলে চালানো হয় যাতে বট ব্লক না হয়।
thread_pool_executor = ThreadPoolExecutor(max_workers=5)

# Helpers - সহায়ক ফাংশন
def clean_text(text):
    """টেক্সট থেকে নন-আলফানিউমেরিক ক্যারেক্টার সরিয়ে ছোট হাতের করে দেয়।"""
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

def extract_language(text):
    """টেক্সট থেকে ভাষা (বেঙ্গলি, হিন্দি, ইংলিশ) বের করে।"""
    langs = ["Bengali", "Hindi", "English"]
    return next((lang for lang in langs if lang.lower() in text.lower()), None)

def extract_year(text):
    """টেক্সট থেকে বছর (যেমন 19XX, 20XX) বের করে।"""
    match = re.search(r'\b(19|20)\d{2}\b', text)
    return int(match.group(0)) if match else None

async def delete_message_later(chat_id, message_id, delay=600):
    """নির্দিষ্ট সময় পর মেসেজ ডিলিট করে।"""
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except Exception as e:
        if "MESSAGE_ID_INVALID" not in str(e) and "MESSAGE_DELETE_FORBIDDEN" not in str(e):
            print(f"Error deleting message {message_id} in chat {chat_id}: {e}")

def find_corrected_matches(query_clean, all_movie_titles_data, score_cutoff=70, limit=5):
    """ফাজি ম্যাচিং ব্যবহার করে সঠিক মুভির নাম খুঁজে বের করে।"""
    if not all_movie_titles_data:
        return []

    choices = [item["title_clean"] for item in all_movie_titles_data]
    
    matches_raw = process.extract(query_clean, choices, limit=limit)

    corrected_suggestions = []
    for matched_clean_title, score in matches_raw:
        if score >= score_cutoff:
            for movie_data in all_movie_titles_data:
                if movie_data["title_clean"] == matched_clean_title:
                    corrected_suggestions.append({
                        "title": movie_data["original_title"],
                        "message_id": movie_data["message_id"],
                        "language": movie_data["language"]
                    })
                    break
    return corrected_suggestions

---

## মেসেজ হ্যান্ডলার

### চ্যানেল থেকে নতুন পোস্ট সেভ করা

@app.on_message(filters.chat(CHANNEL_ID))
async def save_post(_, msg: Message):
    """চ্যানেলে নতুন মুভি পোস্ট হলে তার তথ্য ডেটাবেসে সেভ করে।"""
    text = msg.text or msg.caption
    if not text:
        return

    movie_to_save = {
        "message_id": msg.id,
        "title": text,
        "date": msg.date,
        "year": extract_year(text),
        "language": extract_language(text),
        "title_clean": clean_text(text)
    }
    
    result = movies_col.update_one({"message_id": msg.id}, {"$set": movie_to_save}, upsert=True)

    # নতুন মুভি যোগ হলে ইউজারদের নোটিফিকেশন পাঠায় (যদি গ্লোবাল নোটিফিকেশন চালু থাকে)।
    if result.upserted_id is not None:
        setting = settings_col.find_one({"key": "global_notify"})
        if setting and setting.get("value"):
            for user in users_col.find({"notify": {"$ne": False}}):
                try:
                    await app.send_message(
                        user["_id"],
                        f"নতুন মুভি আপলোড হয়েছে:\n**{text.splitlines()[0][:100]}**\nএখনই সার্চ করে দেখুন!"
                    )
                    await asyncio.sleep(0.05) # Rate limit for sending messages
                except Exception as e:
                    if "PEER_ID_INVALID" in str(e) or "USER_IS_BOT" in str(e) or "USER_DEACTIVATED_REQUIRED" in str(e):
                        print(f"Skipping notification to invalid/blocked user {user['_id']}: {e}")
                    else:
                        print(f"Failed to send notification to user {user['_id']}: {e}")

### স্টার্ট কমান্ড হ্যান্ডলার

@app.on_message(filters.command("start"))
async def start(_, msg: Message):
    """বট চালু হলে বা '/start' কমান্ড দিলে কাজ করে।"""
    # '/start watch_MESSAGE_ID' কমান্ড হ্যান্ডেল করে মুভি ফরওয়ার্ড করার জন্য।
    if len(msg.command) > 1 and msg.command[1].startswith("watch_"):
        message_id = int(msg.command[1].replace("watch_", ""))
        try:
            fwd = await app.forward_messages(msg.chat.id, CHANNEL_ID, message_id)
            await msg.reply_text("আপনার অনুরোধকৃত মুভিটি এখানে পাঠানো হয়েছে।")
            asyncio.create_task(delete_message_later(msg.chat.id, fwd.id))
        except Exception as e:
            await msg.reply_text("মুভিটি খুঁজে পাওয়া যায়নি বা ফরওয়ার্ড করা যায়নি।")
            print(f"Error forwarding message from start payload: {e}")
        return

    # সাধারণ '/start' কমান্ডের জন্য ব্যবহারকারীর তথ্য আপডেট করে এবং স্বাগত মেসেজ পাঠায়।
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"joined": datetime.utcnow(), "notify": True}},
        upsert=True
    )
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("আপডেট চ্যানেল", url=UPDATE_CHANNEL)],
        [InlineKeyboardButton("অ্যাডমিনের সাথে যোগাযোগ", url="https://t.me/ctgmovies23")]
    ])
    await msg.reply_photo(photo=START_PIC, caption="আমাকে মুভির নাম লিখে পাঠান, আমি খুঁজে দেবো।", reply_markup=btns)

### ফিডব্যাক কমান্ড হ্যান্ডলার

@app.on_message(filters.command("feedback") & filters.private)
async def feedback(_, msg: Message):
    """ব্যবহারকারীদের ফিডব্যাক গ্রহণ করে।"""
    if len(msg.command) < 2:
        return await msg.reply("অনুগ্রহ করে /feedback এর পর আপনার মতামত লিখুন।")
    feedback_col.insert_one({
        "user": msg.from_user.id,
        "text": msg.text.split(None, 1)[1],
        "time": datetime.utcnow()
    })
    m = await msg.reply("আপনার মতামতের জন্য ধন্যবাদ!")
    asyncio.create_task(delete_message_later(m.chat.id, m.id, delay=30))

### ব্রডকাস্ট কমান্ড হ্যান্ডলার (অ্যাডমিনদের জন্য)

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(_, msg: Message):
    """অ্যাডমিনরা সকল ব্যবহারকারীকে মেসেজ পাঠাতে পারে।"""
    if len(msg.command) < 2:
        return await msg.reply("ব্যবহার: /broadcast আপনার মেসেজ এখানে")
    count = 0
    message_to_send = msg.text.split(None, 1)[1]
    for user in users_col.find():
        try:
            await app.send_message(user["_id"], message_to_send)
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            if "PEER_ID_INVALID" in str(e) or "USER_IS_BLOCKED" in str(e) or "USER_BOT" in str(e) or "USER_DEACTIVATED_REQUIRED" in str(e):
                print(f"Skipping broadcast to invalid/blocked user {user['_id']}: {e}")
            else:
                print(f"Failed to broadcast to user {user['_id']}: {e}")
    await msg.reply(f"{count} জন ব্যবহারকারীর কাছে ব্রডকাস্ট পাঠানো হয়েছে।")

### স্ট্যাটাস কমান্ড হ্যান্ডলার (অ্যাডমিনদের জন্য)

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg: Message):
    """বটের বর্তমান অবস্থা ও ডেটাবেসের তথ্য দেখায়।"""
    await msg.reply(
        f"মোট ব্যবহারকারী: {users_col.count_documents({})}\n"
        f"মোট মুভি: {movies_col.count_documents({})}\n"
        f"মোট ফিডব্যাক: {feedback_col.count_documents({})}"
    )

### নোটিফিকেশন টগল কমান্ড হ্যান্ডলার (অ্যাডমিনদের জন্য)

@app.on_message(filters.command("notify") & filters.user(ADMIN_IDS))
async def notify_command(_, msg: Message):
    """গ্লোবাল নোটিফিকেশন চালু/বন্ধ করে।"""
    if len(msg.command) != 2 or msg.command[1] not in ["on", "off"]:
        return await msg.reply("ব্যবহার: /notify on অথবা /notify off")
    new_value = True if msg.command[1] == "on" else False
    settings_col.update_one(
        {"key": "global_notify"},
        {"$set": {"value": new_value}},
        upsert=True
    )
    status = "চালু" if new_value else "বন্ধ"
    await msg.reply(f"✅ গ্লোবাল নোটিফিকেশন {status} করা হয়েছে!")

### মুভি ডিলিট কমান্ড হ্যান্ডলার (অ্যাডমিনদের জন্য)

@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_specific_movie(_, msg: Message):
    """নির্দিষ্ট মুভি ডেটাবেস থেকে ডিলিট করে।"""
    if len(msg.command) < 2:
        return await msg.reply("অনুগ্রহ করে মুভির টাইটেল দিন। ব্যবহার: `/delete_movie <মুভির টাইটেল>`")
    
    movie_title_to_delete = msg.text.split(None, 1)[1].strip()
    
    movie_to_delete = movies_col.find_one({"title": {"$regex": re.escape(movie_title_to_delete), "$options": "i"}})

    if not movie_to_delete:
        cleaned_title_to_delete = clean_text(movie_title_to_delete)
        movie_to_delete = movies_col.find_one({"title_clean": {"$regex": f"^{re.escape(cleaned_title_to_delete)}$", "$options": "i"}})

    if movie_to_delete:
        movies_col.delete_one({"_id": movie_to_delete["_id"]})
        await msg.reply(f"মুভি **{movie_to_delete['title']}** সফলভাবে ডিলিট করা হয়েছে।")
    else:
        await msg.reply(f"**{movie_title_to_delete}** নামের কোনো মুভি খুঁজে পাওয়া যায়নি।")

### সব মুভি ডিলিট করার কমান্ড হ্যান্ডলার (অ্যাডমিনদের জন্য)

@app.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_IDS))
async def delete_all_movies_command(_, msg: Message):
    """ডেটাবেস থেকে সকল মুভি ডিলিট করার জন্য কনফার্মেশন চায়।"""
    confirmation_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("হ্যাঁ, সব ডিলিট করুন", callback_data="confirm_delete_all_movies")],
        [InlineKeyboardButton("না, বাতিল করুন", callback_data="cancel_delete_all_movies")]
    ])
    await msg.reply("আপনি কি নিশ্চিত যে আপনি ডাটাবেস থেকে **সব মুভি** ডিলিট করতে চান? এই প্রক্রিয়াটি অপরিবর্তনীয়!", reply_markup=confirmation_button)

---

## কলব্যাক কোয়েরি হ্যান্ডলার

### অ্যাডমিন রিপ্লাই হ্যান্ডলার

@app.on_callback_query(filters.regex(r"^noresult_(wrong|notyet|uploaded|coming)_(\d+)_([^ ]+)$") & filters.user(ADMIN_IDS))
async def handle_admin_reply(_, cq: CallbackQuery):
    """অ্যাডমিনদের 'মুভি পাওয়া যায়নি' সংক্রান্ত বাটনে ক্লিক করার প্রতিক্রিয়া হ্যান্ডেল করে।"""
    parts = cq.data.split("_", 3)
    reason = parts[1]
    user_id = int(parts[2])
    encoded_query = parts[3]
    original_query = urllib.parse.unquote_plus(encoded_query) # মূল সার্চ ক্যোয়ারী ডিকোড করা।

    messages = {
        "wrong": f"❌ আপনি **'{original_query}'** নামে ভুল সার্চ করেছেন। অনুগ্রহ করে সঠিক নাম লিখে আবার চেষ্টা করুন।",
        "notyet": f"⏳ **'{original_query}'** মুভিটি এখনো আমাদের কাছে আসেনি। অনুগ্রহ করে কিছু সময় পর আবার চেষ্টা করুন।",
        "uploaded": f"📤 **'{original_query}'** মুভিটি ইতিমধ্যে আপলোড করা হয়েছে। সঠিক নামে আবার সার্চ করুন।",
        "coming": f"🚀 **'{original_query}'** মুভিটি খুব শিগগিরই আমাদের চ্যানেলে আসবে। অনুগ্রহ করে অপেক্ষা করুন।"
    }

    try:
        await app.send_message(user_id, messages[reason])
        await cq.answer("ব্যবহারকারীকে জানানো হয়েছে ✅", show_alert=True)
        await cq.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ উত্তর দেওয়া হয়েছে: {messages[reason].split(' ')[0]}", callback_data="noop")
        ]]))
    except Exception as e:
        await cq.answer("ব্যবহারকারীকে মেসেজ পাঠানো যায়নি ❌", show_alert=True)
        print(f"Error sending admin reply to user {user_id}: {e}")

---

## মুভি সার্চ ফাংশন

@app.on_message(filters.text & (filters.group | filters.private))
async def search(_, msg: Message):
    """ব্যবহারকারীদের মুভি সার্চ ক্যোয়ারী হ্যান্ডেল করে।"""
    query = msg.text.strip()
    if not query:
        return

    # গ্রুপ চ্যাটের জন্য অতিরিক্ত ফিল্টারিং।
    if msg.chat.type == "group":
        if len(query) < 3: # খুব ছোট ক্যোয়ারী উপেক্ষা করা।
            return
        if msg.reply_to_message or msg.from_user.is_bot: # রিপ্লাই বা বট-এর মেসেজ উপেক্ষা করা।
            return
        if not re.search(r'[a-zA-Z0-9]', query): # শুধুমাত্র আলফানিউমেরিক ক্যারেক্টার আছে কিনা তা পরীক্ষা করা।
            return

    user_id = msg.from_user.id
    users_col.update_one(
        {"_id": user_id},
        {"$set": {"last_query": query}, "$setOnInsert": {"joined": datetime.utcnow()}},
        upsert=True
    )

    loading_message = await msg.reply("🔎 লোড হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...", quote=True)

    query_clean = clean_text(query)
    
    # প্রথমে সরাসরি (starts-with) ম্যাচ খোঁজা হয়।
    matched_movies_direct = list(movies_col.find(
        {"title_clean": {"$regex": f"^{re.escape(query_clean)}", "$options": "i"}}
    ).limit(RESULTS_COUNT))

    if matched_movies_direct:
        await loading_message.delete()
        buttons = []
        for movie in matched_movies_direct:
            buttons.append([
                InlineKeyboardButton(
                    text=movie["title"][:40], # আসল টাইটেল ৪০ ক্যারেক্টার পর্যন্ত প্রদর্শন করা।
                    url=f"https://t.me/{app.me.username}?start=watch_{movie['message_id']}"
                )
            ])
        m = await msg.reply("🎬 নিচের রেজাল্টগুলো পাওয়া গেছে:", reply_markup=InlineKeyboardMarkup(buttons), quote=True)
        # গ্রুপে সার্চ রেজাল্ট নির্দিষ্ট সময় পর ডিলিট করে।
        if msg.chat.type == "group":
            asyncio.create_task(delete_message_later(m.chat.id, m.id, delay=120)) # ২ মিনিট পর ডিলিট।
        return

    # সরাসরি ম্যাচ না পেলে, ফাজি সার্চের মাধ্যমে কাছাকাছি রেজাল্ট খোঁজা হয়।
    all_movie_data_cursor = movies_col.find(
        {"title_clean": {"$regex": query_clean, "$options": "i"}},
        {"title_clean": 1, "original_title": "$title", "message_id": 1, "language": 1}
    ).limit(100) # পারফরম্যান্সের জন্য রেজাল্ট লিমিট করা হয়েছে।

    all_movie_data = list(all_movie_data_cursor)

    corrected_suggestions = await asyncio.get_event_loop().run_in_executor(
        thread_pool_executor,
        find_corrected_matches,
        query_clean,
        all_movie_data,
        70, # স্কোর কাটঅফ, প্রয়োজনে পরিবর্তন করা যেতে পারে।
        RESULTS_COUNT
    )

    await loading_message.delete()

    if corrected_suggestions:
        buttons = []
        for movie in corrected_suggestions:
            buttons.append([
                InlineKeyboardButton(
                    text=movie["title"][:40],
                    url=f"https://t.me/{app.me.username}?start=watch_{movie['message_id']}"
                )
            ])
        
        # ভাষার উপর ভিত্তি করে ফিল্টার করার জন্য বাটন যোগ করা হয়।
        lang_buttons = [
            InlineKeyboardButton("বেঙ্গলি", callback_data=f"lang_Bengali_{query_clean}"),
            InlineKeyboardButton("হিন্দি", callback_data=f"lang_Hindi_{query_clean}"),
            InlineKeyboardButton("ইংলিশ", callback_data=f"lang_English_{query_clean}")
        ]
        buttons.append(lang_buttons)

        m = await msg.reply("🔍 সরাসরি মিলে যায়নি, তবে কাছাকাছি কিছু পাওয়া গেছে:", reply_markup=InlineKeyboardMarkup(buttons), quote=True)
        # গ্রুপে সাজেশন মেসেজ নির্দিষ্ট সময় পর ডিলিট করে।
        if msg.chat.type == "group":
            asyncio.create_task(delete_message_later(m.chat.id, m.id, delay=120))
    else:
        # কোনো মুভি খুঁজে না পেলে ব্যবহারকারীকে জানানো হয়।
        Google_Search_url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
        google_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("গুগলে সার্চ করুন", url=Google_Search_url)]
        ])
        
        alert = await msg.reply(
            "দুঃখিত! আপনার খোঁজা মুভিটি খুঁজে পাওয়া যায়নি। নিচের বাটনে ক্লিক করে গুগলে সার্চ করতে পারেন।",
            reply_markup=google_button,
            quote=True
        )
        # গ্রুপে এই মেসেজ নির্দিষ্ট সময় পর ডিলিট করে।
        if msg.chat.type == "group":
            asyncio.create_task(delete_message_later(alert.chat.id, alert.id, delay=60))

        # অ্যাডমিনদের কাছে নোটিফিকেশন পাঠানো হয়।
        encoded_query = urllib.parse.quote_plus(query) # মুভির নাম এনকোড করে কলব্যাক ডেটার সাথে পাঠানো হয়।
        admin_btns = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ ভুল নাম", callback_data=f"noresult_wrong_{user_id}_{encoded_query}"),
            InlineKeyboardButton("⏳ এখনো আসেনি", callback_data=f"noresult_notyet_{user_id}_{encoded_query}")
        ], [
            InlineKeyboardButton("📤 আপলোড আছে", callback_data=f"noresult_uploaded_{user_id}_{encoded_query}"),
            InlineKeyboardButton("🚀 শিগগির আসবে", callback_data=f"noresult_coming_{user_id}_{encoded_query}")
        ]])

        for admin_id in ADMIN_IDS:
            try:
                await app.send_message(
                    admin_id,
                    f"❗ *নতুন মুভি খোঁজা হয়েছে কিন্তু পাওয়া যায়নি!*\n\n"
                    f"🔍 অনুসন্ধান: `{query}`\n"
                    f"👤 ইউজার: [{msg.from_user.first_name}](tg://user?id={user_id}) (`{user_id}`)",
                    reply_markup=admin_btns,
                    disable_web_page_preview=True
                )
            except Exception as e:
                print(f"Could not notify admin {admin_id}: {e}")

---

## সাধারণ কলব্যাক কোয়েরি হ্যান্ডলার

@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    """সকল ধরনের কলব্যাক কোয়েরি (যেমন - বাটন ক্লিক) হ্যান্ডেল করে।"""
    data = cq.data

    # সব মুভি ডিলিট করার কনফার্মেশন।
    if data == "confirm_delete_all_movies":
        movies_col.delete_many({})
        await cq.message.edit_text("✅ ডাটাবেস থেকে সব মুভি সফলভাবে ডিলিট করা হয়েছে।")
        await cq.answer("সব মুভি ডিলিট করা হয়েছে।")
    elif data == "cancel_delete_all_movies":
        await cq.message.edit_text("❌ সব মুভি ডিলিট করার প্রক্রিয়া বাতিল করা হয়েছে।")
        await cq.answer("বাতিল করা হয়েছে।")

    # এই 'movie_' কলব্যাক ডেটা এখন ব্যবহার করা হয় না, কারণ মুভি ফরওয়ার্ডিং '/start' পেলোডের মাধ্যমে হয়।
    elif data.startswith("movie_"):
        await cq.answer("মুভিটি ফরওয়ার্ড করার জন্য আমাকে ব্যক্তিগতভাবে মেসেজ করুন।", show_alert=True)
        # You could also add: asyncio.create_task(app.send_message(cq.from_user.id, "ক্লিক করুন: " + f"https://t.me/{app.me.username}?start=watch_{data.split('_')[1]}"))

    # ভাষার উপর ভিত্তি করে মুভি ফিল্টার করার জন্য।
    elif data.startswith("lang_"):
        _, lang, query_clean = data.split("_", 2)
        
        potential_lang_matches_cursor = movies_col.find(
            {"language": lang, "title_clean": {"$regex": query_clean, "$options": "i"}},
            {"title": 1, "message_id": 1, "title_clean": 1}
        ).limit(50)

        potential_lang_matches = list(potential_lang_matches_cursor)
        
        fuzzy_data_for_matching_lang = [
            {"title_clean": m["title_clean"], "original_title": m["title"], "message_id": m["message_id"], "language": lang}
            for m in potential_lang_matches
        ]
        
        loop = asyncio.get_running_loop()
        matches_filtered_by_lang = await loop.run_in_executor(
            thread_pool_executor,
            find_corrected_matches,
            query_clean,
            fuzzy_data_for_matching_lang,
            70,
            RESULTS_COUNT
        )

        if matches_filtered_by_lang:
            buttons = [
                [InlineKeyboardButton(m["title"][:40], url=f"https://t.me/{app.me.username}?start=watch_{m['message_id']}")]
                for m in matches_filtered_by_lang[:RESULTS_COUNT]
            ]
            await cq.message.edit_text(
                f"ফলাফল ({lang}) - নিচের থেকে সিলেক্ট করুন:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await cq.answer("এই ভাষায় কিছু পাওয়া যায়নি।", show_alert=True)
        await cq.answer()

    # অন্যান্য অ্যাডমিন কলব্যাক হ্যান্ডেল করার জন্য (যেমন: 'has', 'no', 'soon', 'wrong' - যা এখন নতুন 'noresult_' হ্যান্ডলারে স্থানান্তরিত)।
    # এই অংশটি মূলত পুরোনো অ্যাডমিন ফিডব্যাক বাটন হ্যান্ডেল করার জন্য, নতুন 'noresult_' এর জন্য উপরের ফাংশনটি ব্যবহার করা হয়।
    elif "_" in data:
        parts = data.split("_", 3)
        if len(parts) == 4 and parts[0] in ["has", "no", "soon", "wrong"]: 
            action, uid, mid, raw_query = parts
            uid = int(uid)
            responses = {
                "has": f"✅ @{cq.from_user.username or cq.from_user.first_name} জানিয়েছেন যে **{raw_query}** মুভিটি ডাটাবেজে আছে। সঠিক নাম লিখে আবার চেষ্টা করুন।",
                "no": f"❌ @{cq.from_user.username or cq.from_user.first_name} জানিয়েছেন যে **{raw_query}** মুভিটি ডাটাবেজে নেই।",
                "soon": f"⏳ @{cq.from_user.username or cq.from_user.first_name} জানিয়েছেন যে **{raw_query}** মুভিটি শীঘ্রই আসবে।",
                "wrong": f"✏️ @{cq.from_user.username or cq.from_user.first_name} বলছেন যে আপনি ভুল নাম লিখেছেন: **{raw_query}**।"
            }
            if action in responses:
                try:
                    m = await app.send_message(uid, responses[action])
                    asyncio.create_task(delete_message_later(m.chat.id, m.id, delay=30))
                    await cq.answer("অ্যাডমিনের পক্ষ থেকে উত্তর পাঠানো হয়েছে।")
                except Exception as e:
                    await cq.answer("ইউজারকে বার্তা পাঠাতে সমস্যা হয়েছে।", show_alert=True)
                    print(f"Error sending admin feedback message: {e}")
            else:
                await cq.answer("অকার্যকর কলব্যাক ডেটা।", show_alert=True)
        else:
            await cq.answer("অকার্যকর কলব্যাক ডেটা।", show_alert=True)

---

## বট রান করা

if __name__ == "__main__":
    print("বট শুরু হচ্ছে...")
    app.run()

