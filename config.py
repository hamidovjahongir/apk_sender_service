from pathlib import Path

BASE_DIR = Path(__file__).parent

# Telegram credentials (user session + bot token)
API_ID = 21073748
API_HASH = "85558e0e6cbed2cd263e8fd22cdcf915"
BOT_TOKEN = "8583449166:AAEHptGm-B_qrXnMG1DmlbeuxU_UDot254c"
GROUP_ID = -4996810201

SESSIONS_DIR = BASE_DIR / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

SESSION_PATH = SESSIONS_DIR / "default.session"

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
TELEGRAM_CHUNK_SIZE_BYTES = 50 * 1024 * 1024  # send files in 50 MB parts

