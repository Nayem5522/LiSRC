import os

class Config:
    API_ID = int(os.getenv("API_ID", 12345))               # তোমার API ID
    API_HASH = os.getenv("API_HASH", "")                   # তোমার API HASH
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")                 # বট টোকেন
    CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001234567890"))  # সোর্স চ্যানেল আইডি
    DATABASE_URL = os.getenv("DATABASE_URL", "")           # মঙ্গোডিবি ইউআরএল
    RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 5))     # সার্চ ফলাফলের সংখ্যা
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))               # এডমিনের টেলিগ্রাম ইউজার আইডি (যাকে নোটিফাই করবে)
