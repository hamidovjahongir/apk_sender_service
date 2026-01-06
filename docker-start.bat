@echo off
REM Docker bilan ishga tushirish skripti (Windows)

echo 🚀 APK Sender Service Docker bilan ishga tushirilmoqda...

REM .env faylini tekshirish
if not exist .env (
    echo ⚠️  .env fayl topilmadi. .env.example dan yaratilmoqda...
    copy .env.example .env
    echo ✅ .env fayl yaratildi. Iltimos, uni tahrirlang va Telegram ma'lumotlarini kiriting!
    pause
    exit /b 1
)

REM Docker Compose bilan build va run
echo 📦 Docker image yaratilmoqda...
docker-compose build

echo 🚀 Konteyner ishga tushirilmoqda...
docker-compose up -d

echo ⏳ Konteyner ishga tushishini kutmoqda...
timeout /t 5 /nobreak >nul

REM Health check
echo 🏥 Health check...
docker-compose ps

echo.
echo ✅ Xizmat ishga tushdi!
echo 📖 API dokumentatsiyasi: http://localhost:8000/docs
echo 📊 Loglarni ko'rish: docker-compose logs -f
pause

