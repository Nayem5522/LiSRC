from pyrogram import Client, filters
from pyrogram.types import Message
from config import Config
from database import add_to_db, search_from_db

app = Client(
    "AutoBot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
)

SOURCE_CHANNEL = Config.CHANNEL_ID
ADMIN_ID = Config.ADMIN_ID

@app.on_message(filters.chat(SOURCE_CHANNEL))
async def save_channel_post(client: Client, message: Message):
    await add_to_db(message)

@app.on_message(filters.private & filters.text)
async def search_post(client: Client, message: Message):
    query = message.text.strip().lower()
    results = await search_from_db(query, Config.RESULTS_COUNT)

    if not results:
        await message.reply("কোনো ফলাফল পাওয়া যায়নি!")
        # Notify admin about failed search
        if ADMIN_ID != 0:
            await client.send_message(
                chat_id=ADMIN_ID,
                text=f"User [{message.from_user.first_name}](tg://user?id={message.from_user.id}) searched for:\n`{query}`\nBut no results were found."
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

if __name__ == "__main__":
    app.run()
