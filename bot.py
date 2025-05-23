from pyrogram import Client, filters, enums from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InlineQueryResultArticle, InputTextMessageContent from flask import Flask from threading import Thread from fuzzywuzzy import fuzz import asyncio import os import re import json

API_ID = int(os.getenv("API_ID")) API_HASH = os.getenv("API_HASH") BOT_TOKEN = os.getenv("BOT_TOKEN")) SESSION_STRING = os.getenv("SESSION_STRING") CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME") DELETE_DELAY = int(os.getenv("DELETE_DELAY", 300))

user_client = Client(name="user", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING) bot = Client(name="bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

app = Flask(name) @app.route('/') def home(): return "Bot is running!"

def run(): app.run(host='0.0.0.0', port=8080)

def keep_alive(): t = Thread(target=run) t.start()

def normalize(text): return re.sub(r"[^a-zA-Z0-9]", "", text.lower())

user_stats = {} admin_ids = [123456789]  # Replace with your Telegram user ID(s) blocked_users = set()

LANG_TAGS = ["[Hindi]", "[Bengali]", "[Dual]", "[English]", "[Tamil]", "[Telugu]"]

def detect_language(text): for tag in LANG_TAGS: if tag.lower() in text.lower(): return tag return "[Unknown]"

@bot.on_message((filters.private | filters.group) & filters.text) async def movie_search_handler(client, message): if message.from_user.id in blocked_users: return

query = normalize(message.text.strip())
if not query:
    return await message.reply("দয়া করে একটি মুভির নাম লিখুন")

user_stats[message.from_user.id] = user_stats.get(message.from_user.id, 0) + 1

results = []
async for msg in user_client.search_messages(CHANNEL_USERNAME, query="", limit=3000):
    content = msg.caption or msg.text or "Untitled"
    if fuzz.partial_ratio(query, normalize(content)) >= 65:
        results.append((content[:60], msg.id))

if not results:
    return await message.reply("দুঃখিত, কোনো মিল পাওয়া যায়নি। আরও নির্দিষ্ট নাম দিন।")

results = sorted(results, key=lambda x: fuzz.ratio(query, normalize(x[0])), reverse=True)
buttons = [
    [InlineKeyboardButton(text=title, callback_data=f"movie_{mid}")]
    for title, mid in results[:7]
]

await message.reply(
    "আপনি কোনটি খুঁজছেন? নিচে থেকে সিলেক্ট করুন:",
    reply_markup=InlineKeyboardMarkup(buttons)
)

@bot.on_callback_query(filters.regex("^movie_")) async def movie_sender(client, callback_query): msg_id = int(callback_query.data.split("_", 1)[1]) try: msg = await user_client.get_messages(CHANNEL_USERNAME, msg_id) sent = await bot.copy_message( chat_id=callback_query.message.chat.id, from_chat_id=CHANNEL_USERNAME, message_id=msg_id ) await callback_query.message.delete() await callback_query.answer("মুভি পাঠানো হয়েছে") await asyncio.sleep(DELETE_DELAY) await sent.delete() except Exception as e: await callback_query.answer("মুভি পাঠাতে সমস্যা হয়েছে।", show_alert=True)

@bot.on_inline_query() async def inline_query_handler(client, inline_query): query = normalize(inline_query.query.strip()) if not query: return

results = []
async for msg in user_client.search_messages(CHANNEL_USERNAME, query="", limit=100):
    content = msg.caption or msg.text or "Untitled"
    if fuzz.partial_ratio(query, normalize(content)) >= 65:
        results.append((content, msg.id))

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

@bot.on_message(filters.command("stats") & filters.user(admin_ids)) async def show_stats(client, message): total_users = len(user_stats) await message.reply(f"মোট ইউজার: {total_users}\n\nDetails:\n" + "\n".join([f"{uid}: {count}" for uid, count in user_stats.items()]))

@bot.on_message(filters.command("block") & filters.user(admin_ids)) async def block_user(client, message): if len(message.command) < 2: return await message.reply("ব্যবহার: /block user_id") uid = int(message.command[1]) blocked_users.add(uid) await message.reply(f"User {uid} ব্লক করা হয়েছে।")

@bot.on_message(filters.command("unblock") & filters.user(admin_ids)) async def unblock_user(client, message): if len(message.command) < 2: return await message.reply("ব্যবহার: /unblock user_id") uid = int(message.command[1]) blocked_users.discard(uid) await message.reply(f"User {uid} আনব্লক করা হয়েছে।")

@bot.on_message(filters.command("broadcast") & filters.user(admin_ids)) async def broadcast_msg(client, message): text = message.text.split(" ", 1)[-1] if len(message.text.split(" ", 1)) > 1 else None if not text: return await message.reply("/broadcast <মেসেজ>") for uid in user_stats: try: await bot.send_message(uid, text) except: continue await message.reply("ব্রডকাস্ট সম্পন্ন হয়েছে।")

keep_alive() user_client.start() bot.run()

