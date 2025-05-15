from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

client = AsyncIOMotorClient(Config.DATABASE_URL)
db = client.autobot
collection = db.files

async def add_to_db(message):
    title = message.text or message.caption
    if not title:
        return
    clean_title = " ".join(title.lower().strip().split())
    data = {
        "message_id": message.id,
        "title": clean_title
    }
    if not await collection.find_one({"message_id": message.id}):
        await collection.insert_one(data)

async def search_from_db(query: str, limit: int = 5):
    query = " ".join(query.lower().strip().split())
    regex = {"$regex": f".*{query}.*", "$options": "i"}
    cursor = collection.find({"title": regex}).limit(limit)
    results = await cursor.to_list(length=limit)
    return results
