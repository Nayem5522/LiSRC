from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

client = AsyncIOMotorClient(Config.DATABASE_URL)
db = client.autobot
collection = db.files  # নিশ্চিত হও 'files' কালেকশন ব্যবহার করছো

async def add_to_db(message):
    # message.text or message.caption দুইটাই হতে পারে, কোনোটা নেই তাহলে ফেরত দাও
    title = message.text or message.caption
    if not title:
        return

    data = {
        "message_id": message.message_id,   # Pyrogram message_id
        "title": title.lower()
    }
    # যদি আগে থেকে সেই মেসেজ আইডি না থাকে, তখন ইনসার্ট করো
    exists = await collection.find_one({"message_id": message.message_id})
    if not exists:
        await collection.insert_one(data)

async def search_from_db(query: str, limit: int = 5):
    regex = {"$regex": query, "$options": "i"}  # case insensitive search
    results = collection.find({"title": regex}).limit(limit)
    return await results.to_list(length=limit)
