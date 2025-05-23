from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
from threading import Thread
from fuzzywuzzy import fuzz
import asyncio
import os
import re

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SESSION_STRING = os.getenv("SESSION_STRING")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")  # Without @
DELETE_DELAY = int(os.getenv("DELETE_DELAY", 300))  # seconds

user_client = Client(name="user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
bot = Client(name="bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

def normalize(text):
    return re.sub(r"[^a-zA-Z0-9]", "", text.lower())

@bot.on_message((filters.private | filters.group) & filters.text)
async def movie_search_handler(client, message):
    query = normalize(message.text.strip())
    if not query:
        return await message.reply("দয়া করে একটি মুভির নাম লিখুন")

    results = []
    async for msg in user_client.search_messages(CHANNEL_USERNAME, query="", limit=1000):
        title = msg.caption or msg.text or "Untitled"
        if fuzz.partial_ratio(query, normalize(title)) >= 70:
            results.append((title[:60], msg.id))

    if not results:
        return await message.reply("কোনো মুভি পাওয়া যায়নি।")

    results = sorted(results, key=lambda x: fuzz.ratio(query, normalize(x[0])), reverse=True)
    buttons = [
        [InlineKeyboardButton(text=title, callback_data=f"movie_{mid}")]
        for title, mid in results[:5]
    ]

    await message.reply(
        "আপনি কোনটি খুঁজছেন?",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@bot.on_callback_query(filters.regex("^movie_"))
async def movie_sender(client, callback_query):
    msg_id = int(callback_query.data.split("_", 1)[1])
    try:
        msg = await user_client.get_messages(CHANNEL_USERNAME, msg_id)
        sent = await bot.copy_message(
            chat_id=callback_query.message.chat.id,
            from_chat_id=CHANNEL_USERNAME,
            message_id=msg_id
        )
        await callback_query.message.delete()
        await callback_query.answer("মুভি পাঠানো হয়েছে")
        await asyncio.sleep(DELETE_DELAY)
        await sent.delete()
    except Exception:
        await callback_query.answer("মুভি পাঠানো যায়নি", show_alert=True)

keep_alive()
user_client.start()
bot.run()
