import os
import re
import asyncio
from threading import Thread
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InlineQueryResultArticle, InputTextMessageContent
from fuzzywuzzy import fuzz

# --- Environment Variables ---
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SESSION_STRING = os.getenv("SESSION_STRING")  # User Session String (must be from same account as CHANNEL_USERNAME)
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")  # @channelusername or channel ID (e.g. -100123456789)
DELETE_DELAY = int(os.getenv("DELETE_DELAY", 300))  # seconds to auto-delete sent messages

# --- Initialize clients ---
user_client = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Flask app for keep-alive ---
app = Flask(__name__)

@app.route("/")
def home():
    return "Telegram Movie Info Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- Helpers ---
def normalize(text):
    return re.sub(r"[^a-zA-Z0-9]", "", text.lower())

LANG_TAGS = ["[Hindi]", "[Bengali]", "[English]", "[Tamil]", "[Telugu]", "[Dual]"]

def detect_language(text):
    for tag in LANG_TAGS:
        if tag.lower() in text.lower():
            return tag
    return "[Unknown]"

user_stats = {}
blocked_users = set()
admin_ids = [123456789]  # <-- আপনার Telegram ইউজার আইডি এখানে দিন

# --- Bot Handlers ---

# Handle text messages (private & groups)
@bot.on_message(filters.text & (filters.private | filters.group))
async def search_movies(client, message):
    user_id = message.from_user.id
    if user_id in blocked_users:
        return

    query = normalize(message.text.strip())
    if not query:
        await message.reply("দয়া করে মুভির নাম লিখুন।")
        return

    user_stats[user_id] = user_stats.get(user_id, 0) + 1

    results = []
    async for msg in user_client.search_messages(CHANNEL_USERNAME, query=query, limit=200):
        try:
            content = msg.caption or msg.text or ""
            content_norm = normalize(content)
            score = fuzz.partial_ratio(query, content_norm)
            if score >= 50:
                results.append((content, msg.message_id, score))
        except:
            continue

    if not results:
        await message.reply("দুঃখিত, কোনো মিল পাওয়া যায়নি। দয়া করে আরেকটু নির্দিষ্ট নাম দিন।")
        return

    # Sort by fuzzy match score (descending)
    results.sort(key=lambda x: x[2], reverse=True)

    buttons = []
    for content, msg_id, _ in results[:7]:
        lang_tag = detect_language(content)
        title = content.split("\n")[0][:50]  # প্রথম লাইন থেকে টাইটেল (৫০ ক্যারেক্টার)
        buttons.append([InlineKeyboardButton(f"{title} {lang_tag}", callback_data=f"movie_{msg_id}")])

    await message.reply(
        "আপনি কোনটি খুঁজছেন? নিচের বোতাম থেকে সিলেক্ট করুন:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# Handle callback queries when user clicks movie button
@bot.on_callback_query(filters.regex("^movie_"))
async def send_movie(client, callback_query):
    try:
        msg_id = int(callback_query.data.split("_")[1])
        msg = await user_client.get_messages(CHANNEL_USERNAME, msg_id)
        sent_msg = await bot.copy_message(
            chat_id=callback_query.message.chat.id,
            from_chat_id=CHANNEL_USERNAME,
            message_id=msg_id
        )
        await callback_query.message.delete()
        await callback_query.answer("মুভি পাঠানো হয়েছে।")

        # Auto delete after delay
        await asyncio.sleep(DELETE_DELAY)
        await sent_msg.delete()
    except Exception as e:
        await callback_query.answer("মুভি পাঠাতে সমস্যা হয়েছে।", show_alert=True)

# Inline query handler
@bot.on_inline_query()
async def inline_query_handler(client, inline_query):
    query = normalize(inline_query.query.strip())
    if not query:
        return

    results = []
    async for msg in user_client.search_messages(CHANNEL_USERNAME, query=query, limit=100):
        try:
            content = msg.caption or msg.text or ""
            content_norm = normalize(content)
            score = fuzz.partial_ratio(query, content_norm)
            if score >= 50:
                results.append((content, msg.message_id, score))
        except:
            continue

    results.sort(key=lambda x: x[2], reverse=True)

    articles = []
    for content, msg_id, _ in results[:10]:
        lang_tag = detect_language(content)
        title = content.split("\n")[0][:60]
        articles.append(
            InlineQueryResultArticle(
                title=f"{title} {lang_tag}",
                input_message_content=InputTextMessageContent(f"মুভির ডিটেইল দেখার জন্য নিচের বোতাম চাপুন।"),
                description=lang_tag,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("মুভি দেখান", callback_data=f"movie_{msg_id}")]])
            )
        )

    await inline_query.answer(results=articles, cache_time=1)

# Admin commands: stats
@bot.on_message(filters.command("stats") & filters.user(admin_ids))
async def cmd_stats(client, message):
    total_users = len(user_stats)
    text = f"মোট ইউজার: {total_users}\n\nইউজার ডিটেইলস:\n"
    text += "\n".join([f"ID: {uid} - কুইরিজ: {count}" for uid, count in user_stats.items()])
    await message.reply(text)

# Admin commands: block user
@bot.on_message(filters.command("block") & filters.user(admin_ids))
async def cmd_block(client, message):
    if len(message.command) < 2:
        await message.reply("ব্যবহার: /block user_id")
        return
    uid = int(message.command[1])
    blocked_users.add(uid)
    await message.reply(f"User {uid} ব্লক করা হয়েছে।")

# Admin commands: unblock user
@bot.on_message(filters.command("unblock") & filters.user(admin_ids))
async def cmd_unblock(client, message):
    if len(message.command) < 2:
        await message.reply("ব্যবহার: /unblock user_id")
        return
    uid = int(message.command[1])
    blocked_users.discard(uid)
    await message.reply(f"User {uid} আনব্লক করা হয়েছে।")

# Admin commands: broadcast
@bot.on_message(filters.command("broadcast") & filters.user(admin_ids))
async def cmd_broadcast(client, message):
    text = message.text.split(" ", 1)
    if len(text) < 2:
        await message.reply("ব্যবহার: /broadcast <মেসেজ>")
        return
    msg_text = text[1]
    fail_count = 0
    for uid in list(user_stats.keys()):
        try:
            await bot.send_message(uid, msg_text)
        except:
            fail_count += 1
            continue
    await message.reply(f"ব্রডকাস্ট সম্পন্ন হয়েছে। ব্যর্থ হয়েছে: {fail_count}")

# --- Start the bot and Flask ---
if __name__ == "__main__":
    keep_alive()
    user_client.start()
    bot.run()
