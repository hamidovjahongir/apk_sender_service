# APK Sender Service

Telegram orqali APK fayllarni yuborish uchun FastAPI asosida yozilgan xizmat.

## 🚀 Docker bilan ishga tushirish

### Talablar
- Docker va Docker Compose o'rnatilgan bo'lishi kerak
- Telegram API_ID, API_HASH va BOT_TOKEN

### Tez boshlash

#### Windows:
```bash
# 1. Environment faylini yaratish
copy .env.example .env

# 2. .env faylini tahrirlash (Notepad yoki boshqa editor bilan)
notepad .env

# 3. Docker Compose bilan ishga tushirish
docker-compose up -d

# Yoki avtomatik skript bilan:
docker-start.bat
```

#### Linux/Mac:
```bash
# 1. Environment faylini yaratish
cp .env.example .env

# 2. .env faylini tahrirlash
nano .env

# 3. Docker Compose bilan ishga tushirish
docker-compose up -d

# Yoki avtomatik skript bilan:
chmod +x docker-start.sh
./docker-start.sh
```

**`.env` faylida sozlash kerak:**
   - `API_ID` - Telegram API ID
   - `API_HASH` - Telegram API Hash
   - `BOT_TOKEN` - Bot token
   - `GROUP_ID` - Target Telegram group ID

**API'ni tekshirish:**
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc
   - Health check: http://localhost:8000/health

### Qo'shimcha buyruqlar

```bash
# Loglarni ko'rish
docker-compose logs -f

# Konteynerni to'xtatish
docker-compose stop

# Konteynerni to'xtatish va o'chirish
docker-compose down

# Qayta build qilish
docker-compose build --no-cache
docker-compose up -d

# Konteyner ichiga kirish
docker exec -it apk_sender_service bash
```

## 📝 API Endpoints

### POST /deploy

APK faylni yuklash va Telegram'ga yuborish.

**Parameters:**
- `file` (required): APK fayl
- `caption` (optional): Fayl uchun caption
- `keep` (optional, default: false): Faylni saqlab qolish
- `group_id` (optional): Target group ID
- `bot_token` (optional): Bot token
- `button_text` (optional): Tugma matni
- `button_url` (optional): Tugma URL
- `button_active` (optional, default: false): Tugma faolligi

**Example:**
```bash
curl -X POST "http://localhost:8000/deploy" \
  -F "file=@app.apk" \
  -F "caption=Yangi versiya" \
  -F "button_text=Yuklab olish" \
  -F "button_url=https://example.com/download" \
  -F "button_active=true"
```

## 🔧 Sozlash

Barcha sozlamalar `.env` faylida:

- `API_ID` - Telegram API ID
- `API_HASH` - Telegram API Hash  
- `BOT_TOKEN` - Bot token
- `GROUP_ID` - Default group ID
- `MAX_FILE_SIZE_BYTES` - Maksimal fayl hajmi (default: 2GB)
- `TELEGRAM_CHUNK_SIZE_BYTES` - Telegram chunk size (default: 50MB)
- `PORT` - Server porti (default: 8000)

## 📁 Fayl tuzilishi

```
.
├── api.py                 # FastAPI endpoints
├── config.py              # Konfiguratsiya
├── telegram_uploader.py   # Telegram yuborish logikasi
├── Dockerfile             # Docker image
├── docker-compose.yml     # Docker Compose sozlamalari
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables misoli
├── sessions/             # Telegram session fayllari
└── uploads/              # Yuklangan fayllar
```

## 🐳 Docker Image

### Image yaratish:
```bash
docker build -t apk-sender-service .
```

### Image'ni ishga tushirish:
```bash
docker run -d \
  --name apk_sender \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/sessions:/app/sessions \
  -v $(pwd)/uploads:/app/uploads \
  apk-sender-service
```

## 🔒 Xavfsizlik

- `.env` faylini `.gitignore` ga qo'shing
- Production'da environment variables'larni to'g'ri sozlang
- Bot token va API kalitlarni hech qachon kodga yozmang

## 📊 Monitoring

Health check endpoint: http://localhost:8000/docs

Docker health check avtomatik ishlaydi va konteyner holatini tekshiradi.

## 🛠️ Development

Lokal ishlatish uchun:

```bash
# Virtual environment yaratish
python -m venv venv

# Aktivlashtirish
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Dependencies o'rnatish
pip install -r requirements.txt

# Server ishga tushirish
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

## 📝 Eslatmalar

- Fayllar `uploads/` papkasida saqlanadi (agar `keep=true` bo'lsa)
- Session fayllar `sessions/` papkasida saqlanadi
- Docker volume'lar fayllarni persistent qiladi
- Maksimal fayl hajmi: 2GB (sozlash mumkin)

## 🐛 Muammolarni hal qilish

### Konteyner ishga tushmayapti:
```bash
docker-compose logs apk-sender
```

### Port band:
`.env` faylida `PORT` ni o'zgartiring va `docker-compose.yml` da ham yangilang.

### Session muammolari:
`sessions/` papkasini tozalang va qayta ishga tushiring.

## 📄 License

MIT

