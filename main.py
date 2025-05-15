import asyncio
import threading
import nest_asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from flask import Flask
from config import Config
from database import add_to_db, search_from_db

app = Client(
    "bot_session",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
)

flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is running!"

# চ্যানেল থেকে মেসেজ আসলে সেভ করবে
@app.on_message(filters.chat(Config.CHANNEL_ID))
async def save_channel_message(client: Client, message: Message):
    await add_to_db(message)

def is_admin(user_id: int):
    return user_id == Config.BOT_OWNER

# প্রাইভেট মেসেজে সার্চ করবে, ফলাফল ফরওয়ার্ড করবে
@app.on_message(filters.private & filters.text & ~filters.edited)
async def handle_search(client: Client, message: Message):
    user_id = message.from_user.id
    query = message.text.strip()
    
    if query.startswith("/start") or query.startswith("/help"):
        await message.reply(
            "হ্যালো! আমি পাবলিক মুভি সার্চ বট। তোমার মুভির নাম লিখে সার্চ করো, আমি চ্যানেল থেকে মেসেজ ফরওয়ার্ড করে দিব।"
        )
        return
    
    results = await search_from_db(query, Config.RESULTS_COUNT)
    
    if not results:
        # এডমিনকে নোটিফিকেশন
        await client.send_message(
            Config.BOT_OWNER,
            f"User [{user_id}](tg://user?id={user_id}) searched for '{query}' but found nothing."
        )
        await message.reply("দুঃখিত, তোমার অনুসন্ধানের জন্য কিছু পাওয়া যায়নি।")
        return
    
    for res in results:
        try:
            await client.forward_messages(
                chat_id=message.chat.id,
                from_chat_id=Config.CHANNEL_ID,
                message_ids=res["message_id"],
            )
        except Exception as e:
            print(f"Forwarding error: {e}")

# এডমিন ব্রডকাস্ট কমান্ড
@app.on_message(filters.private & filters.command("broadcast") & filters.user(Config.BOT_OWNER))
async def broadcast(client: Client, message: Message):
    text = message.text.split(None, 1)
    if len(text) < 2:
        await message.reply("ব্রডকাস্ট মেসেজ লিখুন। উদাহরণ: /broadcast তোমার মেসেজ")
        return
    
    broadcast_text = text[1]
    # ইউজার তালিকা যেহেতু নেই, শুধু এডমিনকে সেন্ড করা হচ্ছে ডেমোতে
    await message.reply("ব্রডকাস্ট মেসেজ পাঠানো হচ্ছে...")

    # TODO: এখানে ইউজার আইডি সংগ্রহ করে foreach করে পাঠাতে হবে
    await client.send_message(Config.BOT_OWNER, f"Broadcast sent:\n\n{broadcast_text}")

def run():
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()

    # Flask সার্ভার আলাদাভাবে রান করবে
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=8080)).start()

    loop.run_until_complete(app.start())
    print("Bot started!")
    loop.run_forever()

if __name__ == "__main__":
    run()
