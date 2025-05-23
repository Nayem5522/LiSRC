from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InlineQueryResultArticle, InputTextMessageContent
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
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")  # চ্যানেল ইউজারনেম, যেমন: @YourChannelName
DELETE_DELAY = int(os.getenv("DELETE_DELAY", 300))  # মুভি মেসেজ কত সেকেন্ড পরে ডিলিট হবে

# ইউজার সেশন ক্লায়েন্ট (চ্যানেল থেকে মেসেজ খোঁজার জন্য)
user_client = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# বট ক্লায়েন্ট (বট টোকেন দিয়ে)
bot = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

app = Flask(__name__)

# হোমপেজ
@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

def normalize(text):
    return re.sub(r"[^a-zA-Z0-9]", "", text.lower())

user_stats = {}
admin_ids = [123456789]  # তোমার টেলিগ্রাম আইডি এখানে রাখো (অ্যাডমিন ইউজার আইডি)
blocked_users = set()

LANG_TAGS = ["[Hindi]", "[Bengali]", "[Dual]", "[English]", "[Tamil]", "[Telugu]"]

def detect_language(text):
    for tag in LANG_TAGS:
        if tag.lower() in text.lower():
            return tag
    return "[Unknown]"

@bot.on_message((filters.private | filters.group) & filters.text)
async def movie_search_handler(client, message):
    if message.from_user.id in blocked_users:
        return

    query = normalize(message.text.strip())
    if not query:
        return await message.reply("দয়া করে একটি মুভির নাম লিখুন")

    user_stats[message.from_user.id] = user_stats.get(message.from_user.id, 0) + 1

    results = []
    async for msg in user_client.search_messages(CHANNEL_USERNAME, query=query, limit=300):
        try:
            # চ্যানেলে মেসেজ এখনো আছে কি না চেক করবো get_messages দিয়ে
            check_msg = await user_client.get_messages(CHANNEL_USERNAME, msg.id)
            content = check_msg.caption or check_msg.text or "Untitled"
            content_norm = normalize(content)
            if fuzz.partial_ratio(query, content_norm) >= 30:
                results.append((content[:60], msg.id))
        except Exception:
            # মেসেজ ডিলিট বা আনঅ্যাক্সেসেবল হলে স্কিপ করবে
            continue

    if not results:
        return await message.reply("দুঃখিত, কোনো মিল পাওয়া যায়নি। আরও নির্দিষ্ট নাম দিন।")

    # ফলাফল র‍্যাঙ্কিং
    results = sorted(results, key=lambda x: fuzz.ratio(query, normalize(x[0])), reverse=True)
    buttons = [
        [InlineKeyboardButton(text=title, callback_data=f"movie_{mid}")]
        for title, mid in results[:7]
    ]

    await message.reply(
        "আপনি কোনটি খুঁজছেন? নিচে থেকে সিলেক্ট করুন:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@bot.on_callback_query(filters.regex("^movie_"))
async def movie_sender(client, callback_query):
    msg_id = int(callback_query.data.split("_", 1)[1])
    try:
        # মেসেজ আছে কি না চেক
        msg = await user_client.get_messages(CHANNEL_USERNAME, msg_id)
        # মুভি কপি করে ইউজারের কাছে পাঠানো
        sent = await bot.copy_message(
            chat_id=callback_query.message.chat.id,
            from_chat_id=CHANNEL_USERNAME,
            message_id=msg_id
        )
        await callback_query.message.delete()
        await callback_query.answer("মুভি পাঠানো হয়েছে")

        # ডিলিট ডিলে পরে মেসেজ ডিলিট করো
        await asyncio.sleep(DELETE_DELAY)
        await sent.delete()
    except Exception:
        await callback_query.answer("মুভি পাঠাতে সমস্যা হয়েছে বা মুভি পাওয়া যায়নি।", show_alert=True)

@bot.on_inline_query()
async def inline_query_handler(client, inline_query):
    query = normalize(inline_query.query.strip())
    if not query:
        return

    results = []
    async for msg in user_client.search_messages(CHANNEL_USERNAME, query=query, limit=100):
        try:
            check_msg = await user_client.get_messages(CHANNEL_USERNAME, msg.id)
            content = check_msg.caption or check_msg.text or "Untitled"
            content_norm = normalize(content)
            if fuzz.partial_ratio(query, content_norm) >= 30:
                results.append((content, msg.id))
        except:
            continue

    articles = [
        InlineQueryResultArticle(
            title=text[:60],
            input_message_content=InputTextMessageContent(f"মুভির জন্য অপেক্ষা করুন..."),
            description=detect_language(text),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("এই মুভি দেখান", callback_data=f"movie_{mid}")]]
            )
        ) for text, mid in results[:10]
    ]
    await inline_query.answer(articles, cache_time=1)

# অ্যাডমিন কমান্ডস

@bot.on_message(filters.command("stats") & filters.user(admin_ids))
async def show_stats(client, message):
    total_users = len(user_stats)
    await message.reply(f"মোট ইউজার: {total_users}\n\nDetails:\n" + "\n".join([f"{uid}: {count}" for uid, count in user_stats.items()]))

@bot.on_message(filters.command("block") & filters.user(admin_ids))
async def block_user(client, message):
    if len(message.command) < 2:
        return await message.reply("ব্যবহার: /block user_id")
    uid = int(message.command[1])
    blocked_users.add(uid)
    await message.reply(f"User {uid} ব্লক করা হয়েছে।")

@bot.on_message(filters.command("unblock") & filters.user(admin_ids))
async def unblock_user(client, message):
    if len(message.command) < 2:
        return await message.reply("ব্যবহার: /unblock user_id")
    uid = int(message.command[1])
    blocked_users.discard(uid)
    await message.reply(f"User {uid} আনব্লক করা হয়েছে।")

@bot.on_message(filters.command("broadcast") & filters.user(admin_ids))
async def broadcast_msg(client, message):
    text = message.text.split(" ", 1)[-1] if len(message.text.split(" ", 1)) > 1 else None
    if not text:
        return await message.reply("/broadcast <মেসেজ>")
    fail_count = 0
    for uid in list(user_stats):
        try:
            await bot.send_message(uid, text)
        except:
            fail_count += 1
            continue
    await message.reply(f"ব্রডকাস্ট সম্পন্ন হয়েছে। ব্যর্থ হয়েছে: {fail_count}")

@bot.on_message(filters.command("delete") & filters.user(admin_ids))
async def delete_movie(client, message):
    if len(message.command) < 2:
        return await message.reply("ব্যবহার: /delete <message_id>")
    try:
        msg_id = int(message.command[1])
        await user_client.delete_messages(CHANNEL_USERNAME, msg_id)
        await message.reply(f"মেসেজ {msg_id} ডিলিট করা হয়েছে।")
    except Exception:
        await message.reply("ডিলিট করতে ব্যর্থ।")

# Flask + bot চালানোর জন্য
keep_alive()
user_client.start()
bot.run()
