import os
import shutil
import uuid
import logging
from pathlib import Path
from typing import BinaryIO

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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


@app.post("/deploy")
async def deploy(
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
    temp_stream: NamedStream | None = None
    target: Path | BinaryIO
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
            target = saved_path
            filename_to_send = saved_path.name
            if size == 0:
                size = saved_path.stat().st_size
        else:
            temp_filename = f"tmp-{uuid.uuid4().hex}-{filename_to_send}"
            temp_path = await save_upload(file, filename=temp_filename)
            if size == 0:
                size = temp_path.stat().st_size
            base_stream = temp_path.open("rb")
            temp_stream = NamedStream(base_stream, filename_to_send)
            target = temp_stream

        logger.info(f"Sending file to Telegram: {filename_to_send} ({size / 1024 / 1024:.2f} MB)")

        # Telegram'ga yuborish
        await send_file_to_group(
            target,
            filename=filename_to_send,
            caption=caption,
            group_id=group_id,
            bot_token=bot_token,
            file_size=size,
            button_text=button_text,
            button_url=button_url,
            button_active=button_active,
        )

        logger.info(f"File sent successfully: {filename_to_send}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send file: {str(e)}")
    finally:
        try:
            await file.close()
        except:
            pass
        if temp_stream:
            try:
                temp_stream.close()
            except:
                pass
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink(missing_ok=True)
            except:
                pass

    filename = saved_path.name if saved_path else filename_to_send
    return {"status": "ok", "filename": filename, "size": size}

