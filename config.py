import os

class Config:
    API_ID = int(os.getenv("API_ID", "123456"))  # তোমার Telegram API ID
    API_HASH = os.getenv("API_HASH", "your_api_hash_here")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token_here")
    CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001234567890"))  # চ্যানেল আইডি যেখান থেকে মেসেজ ফেচ করবে
    ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))  # তোমার ইউজার আইডি (এডমিন)
    
    DATABASE_URL = os.getenv("DATABASE_URL", "mongodb+srv://username:password@cluster.mongodb.net/dbname")
    
    RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", "5"))
    BROADCAST_LIMIT = int(os.getenv("BROADCAST_LIMIT", "1000"))  # ব্রডকাস্ট করার সময় একসাথে পাঠানোর ইউজার সংখ্যা
    
    # ফিডব্যাক, ইউজার স্ট্যাটস ইত্যাদির জন্য প্রয়োজন হলে বাড়াতে পারো
