# main.py

import os
import re
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from config import *

bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
client = MongoClient(MONGO_URL)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]
admin_id = int(ADMIN_ID)


def build_keyboard(results):
    keyboard = []
    for result in results:
        buttons = []
        if result.get("language"):
            buttons.append(InlineKeyboardButton(f"Language: {result['language']}", callback_data="ignore"))
        if result.get("year"):
            buttons.append(InlineKeyboardButton(f"Year: {result['year']}", callback_data="ignore"))
        if result.get("type"):
            buttons.append(InlineKeyboardButton(f"Type: {result['type']}", callback_data="ignore"))
        keyboard.append(buttons)
    return keyboard


@bot.on_message(filters.command("start"))
async def start(_, message):
    await message.reply_text("Welcome! Send me a movie name to search.")


@bot.on_message(filters.text & ~filters.private)
async def ignore_group(_, message):
    return


@bot.on_message(filters.text & filters.private)
async def search_movie(_, message):
    query = message.text.strip()
    if not query:
        return await message.reply_text("Please provide a search term.")

    regex = re.compile(".*".join(re.escape(word) for word in query.split()), re.IGNORECASE)
    results = list(collection.find({"title": regex}).limit(5))

    if results:
        for result in results:
            buttons = build_keyboard([result])
            await message.reply_photo(
                photo=result.get("poster"),
                caption=f"**{result['title']}**\nYear: {result.get('year', 'N/A')} | Type: {result.get('type', 'N/A')}",
                reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
            )
    else:
        # Notify admin
        await bot.send_message(
            chat_id=admin_id,
            text=f"❗️No result for: {query}\nFrom: {message.from_user.mention}"
        )

        google_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Search on Google", url=google_url)]
        ])

        no_result_msg = await message.reply_text(
            f"No results found for **{query}**.\nTry searching on Google:",
            reply_markup=keyboard
        )

        await asyncio.sleep(600)
        await no_result_msg.delete()
        await message.delete()


@bot.on_callback_query()
async def callback_query_handler(_, query):
    await query.answer()


if __name__ == "__main__":
    bot.run()
