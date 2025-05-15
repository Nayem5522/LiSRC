import asyncio
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer

from pyrogram import Client, filters
from pyrogram.types import Message
from config import Config
from database import add_to_db, search_from_db

app = Client(
    "autobot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
)

SOURCE_CHANNEL = Config.CHANNEL_ID
ADMIN_ID = Config.ADMIN_ID

@app.on_message(filters.chat(SOURCE_CHANNEL))
async def save_channel_post(client: Client, message: Message):
    await add_to_db(message)
    print(f"Saved: {message.id}")

@app.on_message(filters.private & filters.text)
async def handle_search(client: Client, message: Message):
    query = message.text.strip().lower()
    results = await search_from_db(query, Config.RESULTS_COUNT)

    if not results:
        await message.reply("দুঃখিত, কোনো ফলাফল পাওয়া যায়নি!")
        # Notify admin
        await client.send_message(
            chat_id=ADMIN_ID,
            text=f"❗ ইউজার `{message.from_user.id}` \"{query}\" সার্চ করেছে কিন্তু কিছু পায়নি।"
        )
        return

    for result in results:
        try:
            await client.forward_messages(
                chat_id=message.chat.id,
                from_chat_id=SOURCE_CHANNEL,
                message_ids=result["message_id"]
            )
        except Exception as e:
            await message.reply(f"ফরোয়ার্ড করতে সমস্যা হয়েছে:\n`{e}`")

def start_web():
    server = HTTPServer(("0.0.0.0", 8000), SimpleHTTPRequestHandler)
    print("Web server running on port 8000")
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=start_web, daemon=True).start()
    print("Starting bot...")
    app.run()
