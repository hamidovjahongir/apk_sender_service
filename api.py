import os
import uuid
import logging
import gc
from pathlib import Path
from typing import BinaryIO

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import asyncio

from config import UPLOAD_DIR, MAX_FILE_SIZE_BYTES
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

# Health check endpoint
@app.get("/")
async def root():
    return {"status": "ok", "message": "Flutter Relay Server is running"}

@app.get("/health")
async def health():
    return {"status": "healthy"}


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


async def save_upload(file: UploadFile, filename: str | None = None) -> Path:
    """
    Streaming usul bilan faylni diskka yozish (2 GB gacha optimallashtirilgan)
    Memory-efficient: 2 MB chunks ishlatadi
    """
    target = UPLOAD_DIR / (filename or file.filename or "uploaded_file")
    await file.seek(0)
    
    bytes_written = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)
                bytes_written += len(chunk)
                
                # Har 100 MB yozilganda progress log
                if bytes_written % (100 * 1024 * 1024) == 0:
                    logger.info(f"Upload progress: {bytes_written / 1024 / 1024:.2f} MB written")
        
        logger.info(f"File saved successfully: {bytes_written / 1024 / 1024:.2f} MB")
    except Exception as e:
        # Agar xatolik bo'lsa, yarim yozilgan faylni o'chiramiz
        if target.exists():
            try:
                target.unlink(missing_ok=True)
            except:
                pass
        raise
    
    await file.seek(0)
    return target


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


async def _process_file_upload(
    file_path: Path,
    filename: str,
    caption: str | None,
    group_id: int | None,
    bot_token: str | None,
    button_text: str | None,
    button_url: str | None,
    button_active: bool,
    keep: bool,
):
    """
    Background task - faylni Telegram'ga yuborish (optimallashtirilgan)
    Memory-efficient va error handling bilan
    """
    temp_stream = None
    try:
        # Fayl mavjudligini tekshirish
        if not file_path.exists():
            logger.error(f"File does not exist: {file_path}")
            return
        
        file_size = file_path.stat().st_size
        logger.info(f"Starting Telegram upload: {filename} ({file_size / 1024 / 1024:.2f} MB)")
        
        # Streaming usul bilan faylni ochish
        target = file_path.open("rb")
        temp_stream = NamedStream(target, filename)
        
        # Telegram'ga yuborish
        await send_file_to_group(
            temp_stream,
            filename=filename,
            caption=caption,
            group_id=group_id,
            bot_token=bot_token,
            file_size=file_size,
            button_text=button_text,
            button_url=button_url,
            button_active=button_active,
        )
        
        logger.info(f"File sent successfully to Telegram: {filename}")
        
    except Exception as e:
        logger.error(f"Error in background task for {filename}: {e}", exc_info=True)
        # Background task'da xatolik bo'lsa ham, asosiy request'ga ta'sir qilmaydi
        # Faqat log qilamiz
    finally:
        # Resurslarni tozalash
        if temp_stream:
            try:
                temp_stream.close()
            except Exception as e:
                logger.warning(f"Error closing stream: {e}")
        
        # Memory cleanup
        gc.collect()
        
        # Agar keep=False bo'lsa, faylni o'chiramiz
        if not keep and file_path.exists():
            try:
                file_path.unlink(missing_ok=True)
                logger.info(f"Temporary file deleted: {filename}")
            except Exception as e:
                logger.warning(f"Could not delete temporary file {filename}: {e}")


@app.post("/deploy")
async def deploy(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    caption: str | None = Form(None),
    keep: bool = Form(False),
    group_id: int | None = Form(None),
    bot_token: str | None = Form(None),
    button_text: str | None = Form(None),
    button_url: str | None = Form(None),
    button_active: bool = Form(False),
) -> dict[str, int | str]:
    """
    Fayl yuklash endpoint (2 GB gacha optimallashtirilgan)
    Streaming upload, memory-efficient, background processing
    """
    saved_path: Path | None = None
    temp_path: Path | None = None
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

        # 3. Faylni diskka saqlash (streaming usul - memory-efficient)
        await file.seek(0)
        file_path: Path | None = None
        try:
            if keep:
                saved_path = await save_upload(file)
                filename_to_send = saved_path.name
                if size == 0:
                    size = saved_path.stat().st_size
                file_path = saved_path
            else:
                temp_filename = f"tmp-{uuid.uuid4().hex}-{filename_to_send}"
                temp_path = await save_upload(file, filename=temp_filename)
                if size == 0:
                    size = temp_path.stat().st_size
                file_path = temp_path
        except Exception as e:
            logger.error(f"Error saving file: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

        logger.info(f"File saved successfully: {filename_to_send} ({size / 1024 / 1024:.2f} MB)")

        # 4. Background task'ga qo'shish - Telegram'ga yuborish
        if file_path is None:
            raise HTTPException(status_code=500, detail="File path is None after saving")
        
        background_tasks.add_task(
            _process_file_upload,
            file_path,
            filename_to_send,
            caption,
            group_id,
            bot_token,
            button_text,
            button_url,
            button_active,
            keep,
        )

        logger.info(f"File upload queued for Telegram: {filename_to_send}")

    except HTTPException as e:
        logger.error(f"HTTPException: {e.detail}")
        raise
    except ValueError as e:
        logger.error(f"ValueError: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Invalid input: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing file upload: {e}", exc_info=True)
        error_msg = str(e)
        # Agar xatolik bo'lsa, saqlangan faylni o'chiramiz
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink(missing_ok=True)
            except:
                pass
        if saved_path and saved_path.exists() and not keep:
            try:
                saved_path.unlink(missing_ok=True)
            except:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to process file: {error_msg}")
    finally:
        # Resurslarni tozalash
        try:
            await file.close()
        except:
            pass
        
        # Memory cleanup
        gc.collect()

    filename = saved_path.name if saved_path else filename_to_send
    return {
        "status": "ok",
        "filename": filename,
        "size": size,
        "size_mb": round(size / 1024 / 1024, 2),
        "message": "File uploaded successfully. Processing in background..."
    }

