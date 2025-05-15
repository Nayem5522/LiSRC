import os

class Config:
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    CHANNEL_ID = int(os.getenv("CHANNEL_ID"))  # -100xxxxxxxx
    DATABASE_URL = os.getenv("DATABASE_URL")
    ADMIN_ID = int(os.getenv("ADMIN_ID"))  # তোমার ইউজার আইডি
    RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 5))
