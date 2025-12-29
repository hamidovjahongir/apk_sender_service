import asyncio
import io
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.custom import Button

from config import (
    API_HASH,
    API_ID,
    BOT_TOKEN,
    GROUP_ID,
    SESSIONS_DIR,
    SESSION_PATH,
    TELEGRAM_CHUNK_SIZE_BYTES,
)


def _session_path_for_token(bot_token: str | None) -> Path:
    if not bot_token:
        return SESSION_PATH
    hashed = sha256(bot_token.encode("utf-8")).hexdigest()
    return SESSIONS_DIR / f"bot_{hashed}.session"


def _overall_caption(
    caption: str | None,
    filename: str,
    part: int,
    total_parts: int | None,
) -> str:
    base = caption or filename
    if total_parts and total_parts > 1:
        return f"{base} (part {part}/{total_parts})"
    return base


async def _send_single(
    client: TelegramClient,
    target_group: int,
    payload: Path | BinaryIO,
    filename: str,
    caption: str | None,
    chunk_size: int | None = None,
    button_text: str | None = None,
    button_url: str | None = None,
    button_active: bool = False,
) -> None:
    send_kwargs = {
        "caption": caption or "New Flutter release",
        "force_document": True,
        "allow_cache": False,
    }

    send_kwargs["file_name"] = filename

    if chunk_size is not None:
        send_kwargs["chunk_size"] = chunk_size

    # Button qo'shish - faqat active bo'lsa
    if button_active and button_text and button_url:
        buttons = [[Button.url(text=button_text, url=button_url)]]
        send_kwargs["buttons"] = buttons

    await client.send_file(target_group, payload, **send_kwargs)


async def _dispatch_send(
    client: TelegramClient,
    target_group: int,
    payload: Path | BinaryIO,
    filename: str,
    caption: str | None,
    file_size: int | None,
    chunk_size: int | None,
    button_text: str | None = None,
    button_url: str | None = None,
    button_active: bool = False,
) -> None:
    await _send_single(
        client,
        target_group,
        payload,
        filename,
        caption,
        chunk_size,
        button_text,
        button_url,
        button_active,
    )


async def send_file_to_group(
    payload: Path | BinaryIO,
    filename: str,
    caption: str | None = None,
    group_id: int | None = None,
    bot_token: str | None = None,
    file_size: int | None = None,
    button_text: str | None = None,
    button_url: str | None = None,
    button_active: bool = False,
) -> None:
    target_group = group_id if group_id is not None else GROUP_ID
    target_token = bot_token if bot_token is not None else BOT_TOKEN
    session_path = _session_path_for_token(target_token)

    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.start(bot_token=target_token)

    try:
        await _dispatch_send(
            client,
            target_group,
            payload,
            filename,
            caption,
            file_size,
            TELEGRAM_CHUNK_SIZE_BYTES,
            button_text,
            button_url,
            button_active,
        )
    except FloodWaitError as exc:
        await asyncio.sleep(exc.seconds + 1)
        return await send_file_to_group(
            payload,
            filename,
            caption,
            group_id,
            bot_token,
            file_size,
            button_text,
            button_url,
            button_active,
        )
    except RPCError as exc:
        raise exc
    finally:
        await client.disconnect()

