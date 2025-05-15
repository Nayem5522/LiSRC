from pymongo import MongoClient
from config import Config

client = MongoClient(Config.DATABASE_URL)
db = client.autobot
collection = db.files

async def add_to_db(message):
    if not message.text and not message.caption:
        return
    title = message.text or message.caption
    data = {
        "message_id": message.id,
        "title": title.lower()
    }
    if not await collection.find_one({"message_id": message.id}):
        await collection.insert_one(data)

async def search_from_db(query: str, limit: int = 5):
    regex = {"$regex": query, "$options": "i"}
    results = collection.find({"title": regex}).limit(limit)
    return await results.to_list(length=limit)
