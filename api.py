import os
import shutil
import uuid
import logging
from pathlib import Path
from typing import BinaryIO

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
    # Faylni o'qib diskka yozish
    content = await file.read()
    with target.open("wb") as out:
        out.write(content)
    await file.seek(0)  # Keyinroq o'qish uchun qaytarish
    return target


async def _get_upload_size(file: UploadFile) -> int:
    try:
        # Fayl hajmini olish - avval o'qib olamiz
        await file.seek(0)
        content = await file.read()
        size = len(content)
        await file.seek(0)  # Boshiga qaytish
        return size
    except Exception as e:
        # Agar o'qib bo'lmasa, file.file dan o'qamiz
        logger.warning(f"Could not determine file size directly: {e}")
        try:
            file.file.seek(0, os.SEEK_END)
            size = file.file.tell()
            file.file.seek(0)
            await file.seek(0)
            return size
        except Exception as e2:
            logger.error(f"Error getting file size: {e2}")
            # Agar hech qanday usul ishlamasa, 0 qaytaramiz
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
        # Fayl hajmini aniqlash
        try:
            size = await _get_upload_size(file)
            logger.info(f"File size determined: {size} bytes ({size / 1024 / 1024:.2f} MB)")
        except Exception as e:
            logger.error(f"Error determining file size: {e}")
            # Fayl hajmini aniqlab bo'lmasa ham davom etamiz

        if size > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 2GB Telegram limit")

        # Faylni diskka saqlash
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

