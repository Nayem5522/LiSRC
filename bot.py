from pyrogram import Client, filters
from pyrogram.types import Message
from config import Config
from database import add_movie, search_movies, add_feedback, add_user, add_broadcasted_user
import asyncio

app = Client("AutoBot",
             api_id=Config.API_ID,
             api_hash=Config.API_HASH,
             bot_token=Config.BOT_TOKEN)

SOURCE_CHANNEL = Config.CHANNEL_ID
ADMIN_ID = Config.ADMIN_ID

# মুভি সেভ
@app.on_message(filters.chat(SOURCE_CHANNEL))
async def save_channel_post(client, message: Message):
    await add_movie(message)

# প্রাইভেট চ্যাটে মুভি সার্চ ও ফিল্টার
@app.on_message(filters.private & filters.text)
async def search_post(client, message: Message):
    await add_user(message.from_user.id)
    
    # ফিল্টার প্যারামিটার নেয়ার জন্য একটা পদ্ধতি, উদাহরণস্বরূপ:
    # ব্যবহারকারী লিখতে পারে: "Inception year:2010 type:movie language:english"
    text = message.text.lower()
    parts = text.split()
    query = []
    filters_dict = {"year": "", "type": "", "language": ""}
    for part in parts:
        if part.startswith("year:"):
            filters_dict["year"] = part.replace("year:", "")
        elif part.startswith("type:"):
            filters_dict["type"] = part.replace("type:", "")
        elif part.startswith("language:"):
            filters_dict["language"] = part.replace("language:", "")
        else:
            query.append(part)
    query_text = " ".join(query).strip()
    
    results = await search_movies(query_text, filters_dict, Config.RESULTS_COUNT)
    if not results:
        await message.reply("কোনো ফলাফল পাওয়া যায়নি! এডমিনকে জানানো হচ্ছে...")
        # এডমিনকে মেসেজ পাঠাও
        await client.send_message(ADMIN_ID, f"User [{message.from_user.id}](tg://user?id={message.from_user.id}) searched for '{query_text}' কিন্তু কিছু পাওয়া যায়নি।")
        return

    for res in results:
        try:
            await client.forward_messages(chat_id=message.chat.id,
                                          from_chat_id=SOURCE_CHANNEL,
                                          message_ids=res["message_id"])
        except Exception as e:
            await message.reply(f"ফরোয়ার্ড করতে সমস্যা হয়েছে:\n`{e}`")

# ফিডব্যাক নেওয়া
@app.on_message(filters.private & filters.command("feedback"))
async def feedback_handler(client, message: Message):
    feedback_text = message.text[len("/feedback"):].strip()
    if not feedback_text:
        await message.reply("ফিডব্যাক পাঠাতে /feedback এর পরে কিছু লিখুন।")
        return
    await add_feedback(message.from_user.id, feedback_text)
    await message.reply("তোমার ফিডব্যাক পেয়ে খুশি হলাম! ধন্যবাদ।")

# ব্রডকাস্ট (শুধু এডমিন এর জন্য)
@app.on_message(filters.user(ADMIN_ID) & filters.command("broadcast"))
async def broadcast_handler(client, message: Message):
    text = message.text[len("/broadcast"):].strip()
    if not text:
        await message.reply("ব্রডকাস্ট করার জন্য /broadcast এর পরে মেসেজ দিন।")
        return
    users = await get_broadcast_users()
    count = 0
    failed = 0
    for user in users:
        try:
            await client.send_message(user["user_id"], text)
            count += 1
            if count % 30 == 0:
                await asyncio.sleep(1)  # Rate limit এড়ানোর জন্য
        except:
            failed += 1
    await message.reply(f"ব্রডকাস্ট শেষ হয়েছে। সফল: {count}, ব্যর্থ: {failed}")

# ব্রডকাস্টের জন্য ইউজার সংগ্রহ
@app.on_message(filters.private & filters.text)
async def track_broadcast_users(client, message: Message):
    await add_broadcasted_user(message.from_user.id)

if __name__ == "__main__":
    print("Bot started!")
    app.run()
