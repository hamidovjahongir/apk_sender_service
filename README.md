# APK Sender Service

Telegram orqali APK fayllarni yuborish uchun FastAPI + Docker xizmati. Quyidagi qisqa qo'llanma devops uchun: minimal server talablari, env sozlamalar, ishga tushirish komandalar va health check.

## Server talablari
- OS: Ubuntu 22.04 yoki mos Linux (Docker + Docker Compose o'rnatilgan)
- Resurs: 1 vCPU, 1–2 GB RAM, ≥5 GB disk
- Portlar: ichki servis `8000`, agar reverse proxy bo'lsa 80/443

## Muhit sozlamalari (`.env`)
- `API_ID`, `API_HASH`, `BOT_TOKEN`, `GROUP_ID` (majburiy)
- `PORT` (default 8000, Railway/PAAS beradigan portni ham qabul qiladi)
- `MAX_FILE_SIZE_BYTES` (default 2GB), `TELEGRAM_CHUNK_SIZE_BYTES` (default 50MB)

`.env` ni `.gitignore` da qoldiring; `.env.example` ni to'ldirib qo'yish kifoya.

## Tez deploy (Docker Compose)
```bash
git clone <repo-url> && cd apk_sender_service
cp .env.example .env    # kerakli env qiymatlarni yozing
docker-compose up -d --build
```

Fayl persistensiyasi: `sessions/` va `uploads/` kataloglari compose orqali volume sifatida ulanadi.

## Health va tekshiruv
- Health: `http://<host>:8000/health`
- Swagger: `http://<host>:8000/docs`
- Loglar: `docker-compose logs -f`
- Konteyner ichiga kirish: `docker exec -it apk_sender_service bash`

## Production tavsiyalar
- Reverse proxy (Nginx/Caddy/Traefik) orqali TLS bilan 80/443 ni oching, upstream `http://localhost:8000`
- `restart: unless-stopped` compose’da bor; boshqa sozlama kerak emas
- Storage: `sessions/`, `uploads/` ni zaxiralash yoki tashqi storage/volume ga ulang
- CI/CD: `main` branch deployga tayyor; registry image ishlatmoqchi bo'lsangiz compose’ga `image:` qo'shishingiz mumkin

## API foydalanish (POST /deploy)
```bash
curl -X POST "http://<host>:8000/deploy" \
  -F "file=@app.apk" \
  -F "caption=Yangi versiya" \
  -F "button_text=Yuklab olish" \
  -F "button_url=https://example.com" \
  -F "button_active=true"
```

## Muammolarni hal qilish
- Ishga tushmadi: `docker-compose logs apk-sender`
- Port band: `.env` dagi `PORT` va compose mappingini moslang
- Session xatolari: `sessions/` ni tozalab, qayta ishga tushiring

## Litsenziya
MIT

