import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

BORIS_EMAIL = os.getenv("BORIS_EMAIL", "")
BORIS_PASSWORD = os.getenv("BORIS_PASSWORD", "")

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
MAX_TICKETS = int(os.getenv("MAX_TICKETS", "10"))

BASE_URL = "https://www.borisbilet.ru"
HOCKEY_URL = f"{BASE_URL}/events/hokkey"
LOGIN_URL = f"{BASE_URL}/login"
CART_URL = f"{BASE_URL}/cart"
