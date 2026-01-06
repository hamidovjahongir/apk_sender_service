#!/bin/bash
# Docker bilan ishga tushirish skripti

echo "🚀 APK Sender Service Docker bilan ishga tushirilmoqda..."

# .env faylini tekshirish
if [ ! -f .env ]; then
    echo "⚠️  .env fayl topilmadi. .env.example dan yaratilmoqda..."
    cp .env.example .env
    echo "✅ .env fayl yaratildi. Iltimos, uni tahrirlang va Telegram ma'lumotlarini kiriting!"
    exit 1
fi

# Docker Compose bilan build va run
echo "📦 Docker image yaratilmoqda..."
docker-compose build

echo "🚀 Konteyner ishga tushirilmoqda..."
docker-compose up -d

echo "⏳ Konteyner ishga tushishini kutmoqda..."
sleep 5

# Health check
echo "🏥 Health check..."
docker-compose ps

echo ""
echo "✅ Xizmat ishga tushdi!"
echo "📖 API dokumentatsiyasi: http://localhost:8000/docs"
echo "📊 Loglarni ko'rish: docker-compose logs -f"

