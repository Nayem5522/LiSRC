from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient
from flask import Flask
from threading import Thread
import os
import re
from datetime import datetime

# Configs from environment
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 5))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")
START_PIC = os.getenv("START_PIC", "https://envs.sh/o3s.jpg")

# Pyrogram bot client
app = Client(
    name="movie_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Mongo setup
mongo_client = MongoClient(DATABASE_URL)
db = mongo_client["movie_bot"]
collection = db["movies"]
feedback_collection = db["feedback"]
stats_collection = db["stats"]
users_collection = db["users"]
settings_collection = db["settings"]

# Flask for uptime
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is alive!"

def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)

@app.on_message(filters.chat(CHANNEL_ID))
async def save_channel_post(client, message: Message):
    if message.text or message.caption:
        text = message.text or message.caption
        doc = {
            "message_id": message.id,
            "title": text,
            "date": message.date,
            "type": "movie",
            "year": extract_year(text),
            "language": extract_language(text)
        }
        collection.update_one({"message_id": message.id}, {"$set": doc}, upsert=True)

        # Check if notification is enabled
        notify_setting = settings_collection.find_one({"_id": "notify_toggle"}) or {"enabled": True}
        if notify_setting["enabled"]:
            name_line = text.split("\n")[0][:100]
            notify_text = f"**নতুন মুভি আপলোড হয়েছে:**\n{name_line}\n\nএখনই এই নাম দিয়ে সার্চ করে দেখুন!"
            for user in users_collection.find():
                try:
                    await client.send_message(user["_id"], notify_text)
                except:
                    pass

def extract_year(text):
    match = re.search(r"(19|20)\d{2}", text)
    return match.group() if match else None

def extract_language(text):
    langs = ["Bengali", "Bangla", "Hindi", "English"]
    for lang in langs:
        if lang.lower() in text.lower():
            return lang
    return "Unknown"

@app.on_message(filters.private | filters.group & filters.command("start"))
async def start(client, message):
    users_collection.update_one({"_id": message.from_user.id}, {"$set": {"joined": datetime.utcnow()}}, upsert=True)
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Update Channel", url=UPDATE_CHANNEL)]
    ])
    await message.reply_photo(
        photo=START_PIC,
        caption="Welcome! Send me a movie name to search.",
        reply_markup=buttons
    )

@app.on_message(filters.private & filters.command("feedback"))
async def feedback_cmd(client, message):
    fb = message.text.split(" ", 1)
    if len(fb) < 2:
        return await message.reply("Please provide feedback after /feedback.")
    feedback_collection.insert_one({"user": message.from_user.id, "text": fb[1], "time": datetime.utcnow()})
    await message.reply("Thanks for your feedback!")

@app.on_message(filters.private & filters.command("broadcast") & filters.user(ADMIN_ID))
async def broadcast_cmd(client, message):
    text = message.text.split(" ", 1)
    if len(text) < 2:
        return await message.reply("Give message to broadcast.")
    msg = text[1]
    count = 0
    for user in users_collection.find():
        try:
            await client.send_message(user["_id"], msg)
            count += 1
        except:
            pass
    await message.reply(f"Broadcast sent to {count} users.")

@app.on_message(filters.private & filters.command("stats") & filters.user(ADMIN_ID))
async def stats_cmd(client, message):
    total = users_collection.count_documents({})
    feedbacks = feedback_collection.count_documents({})
    movies = collection.count_documents({})
    await message.reply(f"Users: {total}\nFeedbacks: {feedbacks}\nMovies in DB: {movies}")

@app.on_message(filters.private & filters.command("notif") & filters.user(ADMIN_ID))
async def toggle_notif(client, message):
    current = settings_collection.find_one({"_id": "notify_toggle"}) or {"enabled": True}
    new_state = not current["enabled"]
    settings_collection.update_one({"_id": "notify_toggle"}, {"$set": {"enabled": new_state}}, upsert=True)
    status = "ON ✅" if new_state else "OFF ❌"
    await message.reply(f"নোটিফিকেশন এখন `{status}` করা হয়েছে।")

@app.on_message(filters.private | filters.group & filters.text)
async def search(client, message: Message):
    users_collection.update_one({"_id": message.from_user.id}, {"$set": {"last_search": datetime.utcnow()}}, upsert=True)
    query = message.text.strip()
    filters_q = {"title": {"$regex": query, "$options": "i"}}
    results = list(collection.find(filters_q).limit(RESULTS_COUNT))

    if not results:
        await message.reply("কোনও ফলাফল পাওয়া যায়নি। অ্যাডমিনকে জানানো হয়েছে।")

        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ মুভি আছে", callback_data=f"has_{message.chat.id}")],
            [InlineKeyboardButton("❌ মুভি নেই", callback_data=f"no_{message.chat.id}")],
            [InlineKeyboardButton("⏳ শিগগির আসবে", callback_data=f"soon_{message.chat.id}")],
            [InlineKeyboardButton("✏️ নাম ভুল", callback_data=f"wrong_{message.chat.id}")]
        ])

        await client.send_message(
            ADMIN_ID,
            f"❗ ইউজার `{message.from_user.id}` `{message.from_user.first_name}` এই নাম সার্চ করেছে: **{query}**\n\nকোন ফলাফল পাওয়া যায়নি। নিচে বাটন থেকে ইউজারকে রিপ্লাই দিন।",
            reply_markup=buttons
        )
        return

    for item in results:
        try:
            await client.forward_messages(chat_id=message.chat.id, from_chat_id=CHANNEL_ID, message_ids=item["message_id"])
        except Exception as e:
            print(f"Error forwarding: {e}")

@app.on_callback_query()
async def admin_reply_callback(client, callback_query: CallbackQuery):
    data = callback_query.data
    if "_" in data:
        action, user_id = data.split("_")
        user_id = int(user_id)

        messages = {
            "has": "✅ আপনার খোঁজা মুভিটি ডাটাবেজে আছে। নামটি ঠিকভাবে লিখে আবার চেষ্টা করুন।",
            "no": "❌ এই মুভিটি আমাদের ডাটাবেজে নেই।",
            "soon": "⏳ এই মুভিটি খুব শিগগিরই আপলোড হবে। আবার কিছুক্ষণ পরে সার্চ দিন।",
            "wrong": "✏️ আপনি যে নামটি লিখেছেন সেটি সঠিক নয়। নামটি ঠিকভাবে লিখে আবার চেষ্টা করুন।"
        }

        try:
            await client.send_message(user_id, messages[action])
            await callback_query.answer("ইউজারকে মেসেজ পাঠানো হয়েছে।", show_alert=True)
        except Exception as e:
            await callback_query.answer("ইউজারকে মেসেজ পাঠানো যায়নি।", show_alert=True)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    app.run()
