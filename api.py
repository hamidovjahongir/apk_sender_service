import os
import logging
import gc
from typing import BinaryIO

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncio

from config import MAX_FILE_SIZE_BYTES
from telegram_uploader import send_file_to_group

# Logging konfiguratsiyasi
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Optimallashtirish konstantalari
CHUNK_SIZE = 2 * 1024 * 1024  # 2 MB chunks (xotira optimallashtirish uchun)

app = FastAPI(title="Flutter Relay Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



class NamedStream(BinaryIO):
    def __init__(self, base: BinaryIO, name: str):
        self._base = base
        self._name = name

    def __getattr__(self, item):
        return getattr(self._base, item)

    @property
    def name(self) -> str:
        return self._name

    def read(self, *args, **kwargs):
        return self._base.read(*args, **kwargs)

    def seek(self, *args, **kwargs):
        return self._base.seek(*args, **kwargs)

    def tell(self):
        return self._base.tell()

    def close(self):
        return self._base.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


async def _get_upload_size(file: UploadFile) -> int:
    """
    Fayl hajmini aniqlash (optimallashtirilgan)
    Avval Content-Length header'dan, keyin file.file dan, oxirida chunk-by-chunk
    """
    try:
        await file.seek(0)
        
        # 1. file.file dan o'qish (eng tez)
        try:
            file.file.seek(0, os.SEEK_END)
            size = file.file.tell()
            file.file.seek(0)
            await file.seek(0)
            if size > 0:
                return size
        except:
            pass
        
        # 2. Chunk-by-chunk o'qib hisoblash (memory-efficient)
        await file.seek(0)
        size = 0
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
        
        await file.seek(0)
        return size
    except Exception as e:
        logger.error(f"Error getting file size: {e}")
        await file.seek(0)
        return 0


@app.post("/deploy")
async def deploy(
    file: UploadFile = File(...),
    caption: str | None = Form(None),
    group_id: int = Form(...),
    bot_token: str = Form(...),
    button_text: str | None = Form(None),
    button_url: str | None = Form(None),
    button_active: bool = Form(False),
) -> dict[str, int | str | float]:
    """
    Fayl yuklash endpoint (2 GB gacha optimallashtirilgan)
    Streaming upload, synchronous Telegram yuborish (backgroundsiz)
    """
    filename_to_send = file.filename or "unknown_file"
    size = 0

    try:
        logger.info(f"Received upload request: {filename_to_send}")
        
        # 1. Fayl hajmini aniqlash (optimallashtirilgan)
        try:
            # Avval Content-Length header'dan o'qib ko'ramiz (eng tez)
            content_length = file.headers.get("content-length")
            if content_length:
                size = int(content_length)
                logger.info(f"File size from header: {size / 1024 / 1024:.2f} MB")
            else:
                # Agar header yo'q bo'lsa, faylni o'qib hisoblaymiz
                size = await _get_upload_size(file)
                logger.info(f"File size determined: {size / 1024 / 1024:.2f} MB")
        except Exception as e:
            logger.warning(f"Could not determine file size: {e}, continuing...")
            size = 0

        # 2. Fayl hajmi cheklovini tekshirish
        if size > 0 and size > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File size ({size / 1024 / 1024 / 1024:.2f} GB) exceeds maximum limit (2 GB)"
            )

        # 3. Faylni bevosita stream orqali Telegram'ga yuborish (diskka saqlamasdan)
        await file.seek(0)
        stream = NamedStream(file.file, filename_to_send)

        logger.info(
            f"Starting synchronous Telegram upload: {filename_to_send} ({size / 1024 / 1024:.2f} MB)"
        )

        try:
            await send_file_to_group(
                stream,
                filename=filename_to_send,
                caption=caption,
                group_id=group_id,
                bot_token=bot_token,
                file_size=size,
                button_text=button_text,
                button_url=button_url,
                button_active=button_active,
            )
        except ValueError as e:
            logger.error(f"ValueError while sending to Telegram: {e}", exc_info=True)
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error sending file to Telegram: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to send file to Telegram")

        logger.info(f"File sent successfully to Telegram: {filename_to_send}")

    except HTTPException as e:
        logger.error(f"HTTPException: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error processing file upload: {e}", exc_info=True)
        raise
    finally:
        # Resurslarni tozalash
        try:
            await file.close()
        except:
            pass
        
        # Memory cleanup
        gc.collect()

    return {
        "status": "ok",
        "filename": filename_to_send,
        "size": size,
        "size_mb": round(size / 1024 / 1024, 2),
        "message": "File uploaded successfully and sent to Telegram."
    }


# Qo'shimcha informational endpointlar (/ va /health) olib tashlandi,
# endi faqat /deploy API orqali fayl yuklash mumkin.
