import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

# Telegram API credentials
# Eslatma: bot token va group_id endi request'dan olinadi,
# shu sababli bu yerda faqat API_ID va API_HASH saqlanadi.
API_ID = int(os.getenv("API_ID", "21073748"))
API_HASH = os.getenv("API_HASH", "85558e0e6cbed2cd263e8fd22cdcf915")

# Directories (Docker'da /app ichida)
SESSIONS_DIR = BASE_DIR / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

SESSION_PATH = SESSIONS_DIR / "default.session"

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# File size limits
MAX_FILE_SIZE_BYTES = int(os.getenv("MAX_FILE_SIZE_BYTES", str(2 * 1024 * 1024 * 1024)))  # 2 GB default
TELEGRAM_CHUNK_SIZE_BYTES = int(os.getenv("TELEGRAM_CHUNK_SIZE_BYTES", str(50 * 1024 * 1024)))  # 50 MB default

# Server settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

