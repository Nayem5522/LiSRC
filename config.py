import os

class Config:
    API_ID = int(os.getenv("API_ID", "1234567"))
    API_HASH = os.getenv("API_HASH", "")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001234567890"))
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", "5"))
    LOG_CHANNEL = int(os.getenv("LOG_CHANNEL", "0"))
