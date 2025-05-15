import os

class Config:
    API_ID = int(os.getenv("API_ID", 12345))
    API_HASH = os.getenv("API_HASH", "")
    USER_SESSION_STRING = os.getenv("USER_SESSION_STRING", "")
    CHANNEL_ID = int(os.getenv("CHANNEL_ID", -100))  # Source Channel
    BOT_OWNER = int(os.getenv("BOT_OWNER", 12345678))
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 5))
