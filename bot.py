# bot.py
import os
import re
import logging
from flask import Flask
from threading import Thread
from pymongo import MongoClient, TEXT
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
import requests

# ====== CONFIG ======
API_ID = 12345678  # 🔁 আপনার API_ID দিন
API_HASH = "your_api_hash"  # 🔁 আপনার API_HASH দিন
BOT_TOKEN = "your_bot_token"  # 🔁 আপনার BOT_TOKEN দিন
MONGO_URI = "mongodb+srv://..."  # 🔁 Mongo URI দিন
IMDB_API_KEY = "your_imdb_api_key"  # 🔁 IMDb API key দিন
MOVIE_CHANNEL = -1001234567890  # 🔁 আপনার চ্যানেলের ID (negative sign সহ)

ADMINS = [123456789]  # 🔁 এডমিনদের ইউজার আইডি

# ====== SETUP ======
bot = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = MongoClient(MONGO_URI)
db = mongo.movie_bot
movies = db.movies
users = db.users

try:
    movies.create_index([("title", TEXT)], default_language="none")
except Exception as e:
    print("Index Error:", e)

# ====== IMDb ======
def get_imdb_data(query):
    url = f"https://www.omdbapi.com/?t={query}&apikey={IMDB_API_KEY}"
    try:
        res = requests.get(url).json()
        if res.get("Response") == "True":
            return f"🎬 {res.get('Title')} ({res.get('Year')})\n⭐ {res.get('imdbRating')} IMDb\n🗂️ {res.get('Genre')}\n📝 {res.get('Plot')}"
    except:
        pass
    return None

# ====== MOVIE SAVE FROM CHANNEL ======
@bot.on_message(filters.channel & filters.chat(MOVIE_CHANNEL) & filters.text)
def save_movie(client, message):
    title_match = re.search(r'^(.+?)\s+(\d{4})', message.text)
    if title_match:
        title = title_match.group(1).strip()
        year = title_match.group(2)
        movie_doc = {
            "title": title.lower(),
            "year": year,
            "caption": message.text,
            "link": message.link
        }
        if not movies.find_one({"title": title.lower()}):
            movies.insert_one(movie_doc)

# ====== SEARCH COMMAND ======
@bot.on_message(filters.private & filters.text & ~filters.command(["start", "delete_all_movies", "delete_movie"]))
def search_movie(client, message):
    query = message.text.lower()
    regex = {"$regex": f".*{re.escape(query)}.*", "$options": "i"}
    results = movies.find({"title": regex}).limit(5)

    if results.count() == 0:
        return message.reply("❌ মুভি পাওয়া যায়নি।")

    buttons = []
    for movie in results:
        imdb = get_imdb_data(movie['title'])
        text = f"{movie['caption']}\n\n{imdb if imdb else ''}"
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Download", url=movie['link'])]])
        message.reply(text, reply_markup=btn)

    users.update_one({"_id": message.from_user.id}, {"$set": {"last_query": query}}, upsert=True)

# ====== START ======
@bot.on_message(filters.command("start"))
def start(client, message):
    message.reply("👋 স্বাগতম! মুভির নাম লিখে খুঁজুন।")

# ====== DELETE ALL MOVIES ======
@bot.on_message(filters.command("delete_all_movies") & filters.user(ADMINS))
def delete_all_movies(client, message):
    result = movies.delete_many({})
    message.reply(f"✅ {result.deleted_count}টি মুভি ডিলিট হয়েছে।")

# ====== DELETE BY TITLE ======
@bot.on_message(filters.command("delete_movie") & filters.user(ADMINS))
def delete_movie(client, message: Message):
    if len(message.command) < 2:
        return message.reply("⚠️ উদাহরণ: `/delete_movie avengers`", quote=True)
    title = " ".join(message.command[1:]).lower()
    result = movies.delete_one({"title": {"$regex": f"^{re.escape(title)}$", "$options": "i"}})
    if result.deleted_count:
        message.reply("✅ মুভি ডিলিট হয়েছে।")
    else:
        message.reply("❌ এমন কোন মুভি পাইনি।")

# ====== FLASK DASHBOARD (Optional Placeholder) ======
app = Flask(__name__)

@app.route('/')
def home():
    total_users = users.count_documents({})
    total_movies = movies.count_documents({})
    return f"<h2>📊 Movie Bot Stats</h2><p>👥 Users: {total_users}<br>🎬 Movies: {total_movies}</p>"

def run_flask():
    app.run(host="0.0.0.0", port=8000)

# ====== START EVERYTHING ======
if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.run()
