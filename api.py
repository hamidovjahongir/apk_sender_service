import os
import shutil
import uuid
import logging
from pathlib import Path
from typing import BinaryIO

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
import asyncio

from config import UPLOAD_DIR, MAX_FILE_SIZE_BYTES
from telegram_uploader import send_file_to_group

logger = logging.getLogger(__name__)

app = FastAPI(title="Flutter Relay Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request timeout'ni oshirish (katta fayllar uchun)
@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    # Railway'da timeout cheklovi bo'lishi mumkin, lekin biz optimallashtiramiz
    response = await call_next(request)
    return response


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
    target = UPLOAD_DIR / (filename or file.filename or "uploaded_file")
    # Streaming usul bilan faylni diskka yozish (katta fayllar uchun)
    CHUNK_SIZE = 1024 * 1024  # 1 MB chunks
    await file.seek(0)
    
    with target.open("wb") as out:
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break
            out.write(chunk)
    
    await file.seek(0)  # Keyinroq o'qish uchun qaytarish
    return target


async def _get_upload_size(file: UploadFile) -> int:
    try:
        # Fayl hajmini olish - file.file dan o'qamiz (tezroq)
        await file.seek(0)
        try:
            file.file.seek(0, os.SEEK_END)
            size = file.file.tell()
            file.file.seek(0)
            await file.seek(0)
            return size
        except:
            # Agar file.file ishlamasa, chunk-by-chunk o'qib hisoblaymiz
            await file.seek(0)
            size = 0
            CHUNK_SIZE = 1024 * 1024  # 1 MB chunks
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
    """Background task - faylni Telegram'ga yuborish"""
    try:
        logger.info(f"Processing file upload: {filename}")
        target = file_path.open("rb")
        temp_stream = NamedStream(target, filename)
        
        await send_file_to_group(
            temp_stream,
            filename=filename,
            caption=caption,
            group_id=group_id,
            bot_token=bot_token,
            file_size=file_path.stat().st_size,
            button_text=button_text,
            button_url=button_url,
            button_active=button_active,
        )
        
        temp_stream.close()
        
        # Agar keep=False bo'lsa, faylni o'chiramiz
        if not keep and file_path.exists():
            file_path.unlink(missing_ok=True)
            
        logger.info(f"File sent successfully: {filename}")
    except Exception as e:
        logger.error(f"Error in background task: {e}", exc_info=True)
        # Xatolik bo'lsa ham faylni o'chirishga harakat qilamiz
        if not keep and file_path.exists():
            try:
                file_path.unlink(missing_ok=True)
            except:
                pass


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
    saved_path: Path | None = None
    temp_path: Path | None = None
    filename_to_send = file.filename or "unknown_file"
    size = 0

    try:
        # Fayl hajmini aniqlash (optimallashtirilgan)
        try:
            # Avval Content-Length header'dan o'qib ko'ramiz
            content_length = file.headers.get("content-length")
            if content_length:
                size = int(content_length)
                logger.info(f"File size from header: {size} bytes ({size / 1024 / 1024:.2f} MB)")
            else:
                # Agar header yo'q bo'lsa, faylni o'qib hisoblaymiz
                size = await _get_upload_size(file)
                logger.info(f"File size determined: {size} bytes ({size / 1024 / 1024:.2f} MB)")
        except Exception as e:
            logger.error(f"Error determining file size: {e}")
            # Fayl hajmini aniqlab bo'lmasa ham davom etamiz
            size = 0

        if size > 0 and size > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 2GB Telegram limit")

        # Faylni diskka saqlash (streaming usul)
        await file.seek(0)
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

        logger.info(f"File saved: {filename_to_send} ({size / 1024 / 1024:.2f} MB)")

        # Background task'ga qo'shish - Telegram'ga yuborish
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

        logger.info(f"File upload queued: {filename_to_send}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing file: {e}", exc_info=True)
        # Agar xatolik bo'lsa, saqlangan faylni o'chiramiz
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink(missing_ok=True)
            except:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")
    finally:
        try:
            await file.close()
        except:
            pass

    filename = saved_path.name if saved_path else filename_to_send
    return {
        "status": "ok",
        "filename": filename,
        "size": size,
        "message": "File uploaded successfully. Processing in background..."
    }

