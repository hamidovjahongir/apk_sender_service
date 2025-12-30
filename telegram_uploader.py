import asyncio
import logging
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError, SessionPasswordNeededError
from telethon.tl.custom import Button

logger = logging.getLogger(__name__)

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
    max_retries: int = 3,
) -> None:
    """
    Faylni Telegram guruhiga yuborish (optimallashtirilgan, retry mechanism bilan)
    
    Args:
        payload: Fayl path yoki BinaryIO stream
        filename: Fayl nomi
        caption: Fayl caption
        group_id: Target group ID
        bot_token: Bot token
        file_size: Fayl hajmi (bytes)
        button_text: Tugma matni
        button_url: Tugma URL
        button_active: Tugma faolligi
        max_retries: Maksimal retry soni
    """
    target_group = group_id if group_id is not None else GROUP_ID
    target_token = bot_token if bot_token is not None else BOT_TOKEN
    session_path = _session_path_for_token(target_token)

    client = None
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            logger.info(f"Connecting to Telegram (attempt {retry_count + 1}/{max_retries})")
            client = TelegramClient(session_path, API_ID, API_HASH)
            await client.start(bot_token=target_token)
            
            file_size_str = f"{file_size / 1024 / 1024:.2f} MB" if file_size else "unknown size"
            logger.info(f"Sending file to Telegram: {filename} ({file_size_str})")
            
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
            
            logger.info(f"File sent successfully: {filename}")
            return  # Muvaffaqiyatli yuborildi
            
        except FloodWaitError as exc:
            wait_time = exc.seconds + 1
            logger.warning(f"FloodWait error: waiting {wait_time} seconds...")
            await asyncio.sleep(wait_time)
            retry_count += 1
            # Payload'ni qayta o'qish uchun seek qilamiz
            if hasattr(payload, 'seek'):
                try:
                    payload.seek(0)
                except:
                    pass
            continue
            
        except SessionPasswordNeededError:
            logger.error("Session password needed - this should not happen with bot token")
            raise RPCError("Session password needed")
            
        except RPCError as exc:
            logger.error(f"RPC error (attempt {retry_count + 1}/{max_retries}): {exc}")
            retry_count += 1
            if retry_count >= max_retries:
                raise exc
            # Kichik kutish va qayta urinish
            await asyncio.sleep(2)
            # Payload'ni qayta o'qish uchun seek qilamiz
            if hasattr(payload, 'seek'):
                try:
                    payload.seek(0)
                except:
                    pass
            continue
            
        except Exception as exc:
            logger.error(f"Unexpected error: {exc}", exc_info=True)
            raise exc
            
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
    
    # Agar barcha urinishlar muvaffaqiyatsiz bo'lsa
    raise RPCError(f"Failed to send file after {max_retries} attempts")

