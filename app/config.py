import os
from pathlib import Path


def env(key, default=""):
    return os.environ.get(key, default).strip()


DATA_DIR = Path(env("DATA_DIR", "/app/data"))
(DATA_DIR / "videos").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "music").mkdir(parents=True, exist_ok=True)
FONT_DIR = Path(env("FONT_DIR", "/app/fonts"))

UPLOADPOST_API_KEY = env("UPLOADPOST_API_KEY")
UPLOADPOST_USER = env("UPLOADPOST_USER")
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")
TELEGRAM_API_BASE = env("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
MCP_SECRET = env("MCP_SECRET")
LISTEN_PORT = int(env("LISTEN_PORT", "8787"))
APPROVAL_TTL_HOURS = float(env("APPROVAL_TTL_HOURS", "24"))
MAX_SECONDS = float(env("MAX_SECONDS", "90"))
DEFAULT_HANDLE = env("DEFAULT_HANDLE")


def missing():
    req = ["UPLOADPOST_API_KEY", "UPLOADPOST_USER", "TELEGRAM_BOT_TOKEN",
           "TELEGRAM_CHAT_ID", "MCP_SECRET"]
    return [k for k in req if not globals()[k]]
