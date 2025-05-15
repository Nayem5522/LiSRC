from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

client = AsyncIOMotorClient(Config.DATABASE_URL)
db = client["autobot_db"]
collection = db["movies"]

async def add_to_db(message):
    title = message.text or message.caption
    if not title:
        return
    data = {
        "message_id": message.message_id,
        "title": title.lower()
    }
    if not await collection.find_one({"message_id": message.message_id}):
        await collection.insert_one(data)

async def search_from_db(query: str, limit: int = 5):
    regex = {"$regex": query, "$options": "i"}
    cursor = collection.find({"title": regex}).limit(limit)
    return await cursor.to_list(length=limit)
