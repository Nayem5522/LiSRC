import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from pymongo import MongoClient
from config import Config
from flask import Flask

# MongoDB Setup
mongo_client = MongoClient(Config.DATABASE_URL)
db = mongo_client["movie_db"]
collection = db["movies"]

# Pyrogram Client with Bot Token
app = Client(
    "bot_session",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
)

# Flask app for uptime
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is running!"

async def start_bot():
    await app.start()
    print("Bot started with Bot Token!")

    @app.on_message(filters.private & filters.text & ~filters.edited)
    async def search_movie(client: Client, message: Message):
        query = message.text.strip()
        if query.startswith("/start") or query.startswith("/help"):
            await message.reply_text(
                "হ্যালো! আমি পাবলিক মুভি সার্চ বট। যেকোনো মুভি বা লিংক নাম লিখে সার্চ করো, আমি তোমাকে চ্যানেল থেকে মেসেজ ফরওয়ার্ড করে দিব।"
            )
            return

        results = collection.find({"title": {"$regex": query, "$options": "i"}}).limit(Config.RESULTS_COUNT)

        results_list = list(results)
        if not results_list:
            await message.reply_text("দুঃখিত, তোমার অনুসন্ধানের জন্য কিছু পাওয়া যায়নি। আবার চেষ্টা করো।")
            # এডমিনে নোটিফিকেশন পাঠাতে চাইলে এখানে কোড দিতে পারো
            return

        for res in results_list:
            try:
                msg_id = res.get("message_id")
                chat_id = Config.CHANNEL_ID
                await client.forward_messages(
                    chat_id=message.chat.id,
                    from_chat_id=chat_id,
                    message_ids=msg_id,
                )
            except Exception as e:
                print(f"Forwarding error: {e}")

def run():
    import threading
    import nest_asyncio

    nest_asyncio.apply()

    loop = asyncio.get_event_loop()

    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

    loop.run_until_complete(start_bot())
    loop.run_forever()

if __name__ == "__main__":
    run()
