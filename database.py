from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

client = AsyncIOMotorClient(Config.DATABASE_URL)
db = client.autobot_db

movies_collection = db.movies
feedback_collection = db.feedbacks
users_collection = db.users
broadcast_collection = db.broadcasts

async def add_movie(message):
    title = message.text or message.caption or ""
    if not title:
        return
    data = {
        "message_id": message.id,
        "title": title.lower(),
        "year": "",       # পরবর্তীতে যোগ করবো
        "type": "",       # পরবর্তীতে যোগ করবো
        "language": "",   # পরবর্তীতে যোগ করবো
    }
    exists = await movies_collection.find_one({"message_id": message.id})
    if not exists:
        await movies_collection.insert_one(data)

async def search_movies(query: str, filters=None, limit=5):
    """
    filters = {"year": "2023", "type": "movie", "language": "english"} ইত্যাদি হতে পারে
    """
    query_filter = {"title": {"$regex": query, "$options": "i"}}
    if filters:
        for k,v in filters.items():
            if v:
                query_filter[k] = v.lower()
    cursor = movies_collection.find(query_filter).limit(limit)
    return await cursor.to_list(length=limit)

async def add_feedback(user_id, feedback_text):
    await feedback_collection.insert_one({"user_id": user_id, "feedback": feedback_text})

async def add_user(user_id):
    exists = await users_collection.find_one({"user_id": user_id})
    if not exists:
        await users_collection.insert_one({"user_id": user_id})

async def get_user_count():
    return await users_collection.count_documents({})

async def add_broadcasted_user(user_id):
    exists = await broadcast_collection.find_one({"user_id": user_id})
    if not exists:
        await broadcast_collection.insert_one({"user_id": user_id})

async def get_broadcast_users():
    cursor = broadcast_collection.find({})
    return await cursor.to_list(length=None)
