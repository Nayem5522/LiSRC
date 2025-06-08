import re
from os
from os import environ
id_pattern = re.compile(r'^.\d+$')


API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/PrimeCineZone")
AUTH_CHANNEL = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('AUTH_CHANNEL', '-1002323796637').split()] # give channel id with separate space. Ex: ('-10073828 -102782829 -1007282828')
START_PIC = os.getenv("START_PIC", "https://i.postimg.cc/SRQn4Dwg/IMG-20250606-112525-389.jpg")
