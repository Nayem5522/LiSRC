from pymongo import MongoClient
from config import Config

mongo_client = MongoClient(Config.DATABASE_URL)
db = mongo_client["movie_db"]
collection = db["movies"]

async def add_to_db(message):
    """
    Channel থেকে আসা মুভি মেসেজ সেভ করার জন্য (পরে চাইলে ইউজার আইডি সেভ করতে পারো)
    """
    title = message.text or message.caption
    if not title:
        return
    title = title.lower()
    if collection.find_one({"message_id": message.id}):
        return
    data = {
        "message_id": message.id,
        "title": title,
    }
    collection.insert_one(data)

async def search_from_db(query: str, limit: int = 5):
    regex = {"$regex": query, "$options": "i"}
    results = collection.find({"title": regex}).limit(limit)
    return list(results)
