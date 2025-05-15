from pyrogram import Client, filters
from pyrogram.types import Message
from pymongo import MongoClient
from flask import Flask
from threading import Thread
import os
import re
from datetime import datetime

# Configs from environment
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")  # সেশন স্ট্রিং এর জায়গায় বট টোকেন
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 5))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

# Pyrogram bot client (bot token দিয়ে)
app = Client(
    "bot",
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


def extract_year(text):
    match = re.search(r"(19|20)\\d{2}", text)
    return match.group() if match else None

def extract_language(text):
    langs = ["Bengali", "Bangla", "Hindi", "English"]
    for lang in langs:
        if lang.lower() in text.lower():
            return lang
    return "Unknown"

@app.on_message(filters.private & filters.command("start"))
async def start(client, message):
    users_collection.update_one({"_id": message.from_user.id}, {"$set": {"joined": datetime.utcnow()}}, upsert=True)
    await message.reply("Welcome! Send me a movie name to search.")

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
        except: pass
    await message.reply(f"Broadcast sent to {count} users.")

# **এখানে নতুন সুন্দর Stats কমান্ড ফাংশন**
@app.on_message(filters.private & filters.command("stats") & filters.user(ADMIN_ID))
async def stats_cmd(client, message):
    total_users = users_collection.count_documents({})
    total_feedbacks = feedback_collection.count_documents({})
    total_movies = collection.count_documents({})

    await message.reply(
        f"Users: {total_users}\n"
        f"Movies: {total_movies}\n"
        f"Feedbacks: {total_feedbacks}"
    )

@app.on_message(filters.private & filters.text)
async def search(client, message: Message):
    users_collection.update_one({"_id": message.from_user.id}, {"$set": {"last_search": datetime.utcnow()}}, upsert=True)
    query = message.text.strip()
    filters_q = {"title": {"$regex": query, "$options": "i"}}
    results = list(collection.find(filters_q).limit(RESULTS_COUNT))

    if not results:
        await client.send_message(ADMIN_ID, f"No result for: {query}")
        await message.reply("No results found.")
        return

    for item in results:
        try:
            await client.forward_messages(chat_id=message.chat.id, from_chat_id=CHANNEL_ID, message_ids=item["message_id"])
        except Exception as e:
            print(f"Error forwarding: {e}")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    app.run()
