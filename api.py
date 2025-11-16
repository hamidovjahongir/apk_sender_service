import os
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncio

from config import UPLOAD_DIR, MAX_FILE_SIZE_BYTES
from telegram_uploader import send_file_to_group

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


def save_upload(file: UploadFile, filename: str | None = None) -> Path:
    target = UPLOAD_DIR / (filename or file.filename)
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return target


def _get_upload_size(file: UploadFile) -> int:
    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)
    return size


@app.post("/deploy")
async def deploy(
    file: UploadFile = File(...),
    caption: str | None = Form(None),
    keep: bool = Form(False),
    group_id: int | None = Form(None),
    bot_token: str | None = Form(None),
) -> dict[str, int | str]:
    size = _get_upload_size(file)
    if size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 2GB Telegram limit")

    saved_path: Path | None = None
    temp_path: Path | None = None
    temp_stream: NamedStream | None = None
    target: Path | BinaryIO
    filename_to_send = file.filename

    try:
        if keep:
            await file.seek(0)
            saved_path = save_upload(file)
            target = saved_path
            filename_to_send = saved_path.name
        else:
            await file.seek(0)
            temp_filename = f"tmp-{uuid.uuid4().hex}-{file.filename}"
            temp_path = save_upload(file, filename=temp_filename)
            base_stream = temp_path.open("rb")
            temp_stream = NamedStream(base_stream, filename_to_send)
            target = temp_stream

        await send_file_to_group(
            target,
            filename=filename_to_send,
            caption=caption,
            group_id=group_id,
            bot_token=bot_token,
            file_size=size,
        )
    finally:
        await file.close()
        if temp_stream:
            temp_stream.close()
        if temp_path:
            temp_path.unlink(missing_ok=True)

    filename = saved_path.name if saved_path else file.filename
    return {"status": "ok", "filename": filename, "size": size}

