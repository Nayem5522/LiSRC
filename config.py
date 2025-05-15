import os

class Config:
    API_ID = int(os.getenv("API_ID", "YOUR_API_ID"))
    API_HASH = os.getenv("API_HASH", "YOUR_API_HASH")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
    CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-100XXXXXXXXXX"))  # যেখান থেকে মুভি মেসেজগুলো আসবে
    DATABASE_URL = os.getenv("DATABASE_URL", "mongodb+srv://user:pass@cluster.mongodb.net/dbname")
    BOT_OWNER = int(os.getenv("BOT_OWNER", "123456789"))  # এডমিনের টেলিগ্রাম ইউজার আইডি
    RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 5))  # সার্চ রেজাল্টস কতগুলো দেখাবে
