import asyncio
import logging
import sqlite3
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO, Union

from telethon import TelegramClient
from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser
from telethon.errors import FloodWaitError, RPCError, SessionPasswordNeededError, PeerIdInvalidError
from telethon.tl.custom import Button

logger = logging.getLogger(__name__)

# Session locks - har bir session fayl uchun alohida lock
_session_locks: dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()

from config import (
    API_HASH,
    API_ID,
    SESSIONS_DIR,
    SESSION_PATH,
    TELEGRAM_CHUNK_SIZE_BYTES,
)


def _session_path_for_token(bot_token: str | None) -> Path:
    if not bot_token:
        return SESSION_PATH
    hashed = sha256(bot_token.encode("utf-8")).hexdigest()
    return SESSIONS_DIR / f"bot_{hashed}.session"


async def _get_session_lock(session_path_str: str) -> asyncio.Lock:
    """Har bir session fayl uchun alohida lock olish"""
    async with _locks_lock:
        if session_path_str not in _session_locks:
            _session_locks[session_path_str] = asyncio.Lock()
        return _session_locks[session_path_str]


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
    target_group: Union[int, InputPeerChannel, InputPeerChat, InputPeerUser, object],
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
    target_group: Union[int, InputPeerChannel, InputPeerChat, InputPeerUser, object],
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
    # group_id va bot_token endi faqat request orqali keladi.
    # Agar kelmasa, aniq xatolik qaytaramiz.
    if group_id is None:
        raise ValueError("group_id is required but was not provided.")
    if bot_token is None:
        raise ValueError("bot_token is required but was not provided.")

    target_group = group_id
    target_token = bot_token
    session_path = _session_path_for_token(target_token)
    # Path obyektini str ga o'zgartirish (Telethon talab qiladi)
    session_path_str = str(session_path)

    # Session lock olish (parallel request'larni oldini olish uchun)
    session_lock = await _get_session_lock(session_path_str)
    
    client = None
    retry_count = 0
    
    while retry_count < max_retries:
        client = None
        try:
            # Lock bilan session faylga kirish (barcha operatsiyalar lock ichida)
            async with session_lock:
                logger.info(f"Connecting to Telegram (attempt {retry_count + 1}/{max_retries})")
                client = TelegramClient(session_path_str, API_ID, API_HASH)
                
                try:
                    await client.start(bot_token=target_token)
                except sqlite3.OperationalError as db_error:
                    if "database is locked" in str(db_error).lower():
                        logger.warning(f"Database locked, will retry after lock release...")
                        if client:
                            try:
                                await client.disconnect()
                            except:
                                pass
                        client = None
                        # Lock chiqadi va retry qiladi
                        raise
                
                # Entity'ni resolve qilish (guruh/channel topish)
                # Bot token bilan ishlatganda, ba'zan get_entity() ishlamaydi, lekin send_file() to'g'ridan-to'g'ri integer ID bilan ishlaydi
                # Shuning uchun biz avval entity'ni resolve qilishga urinamiz, lekin agar ishlamasa, to'g'ridan-to'g'ri yuborishga urinamiz
                entity = None
                entity_resolved = False
                
                # Usul 1: To'g'ridan-to'g'ri get_entity (eng tez usul)
                try:
                    entity = await client.get_entity(target_group)
                    logger.info(f"Found entity via get_entity: {type(entity).__name__}")
                    entity_resolved = True
                except Exception as entity_error:
                    # Entity resolve qilinmadi - bu normal, chunki bot token bilan ba'zan ishlamaydi
                    logger.debug(f"get_entity failed (will try direct send): {entity_error}")
                
                # Usul 2: Agar ishlamasa, get_input_entity bilan urinib ko'ramiz
                if not entity_resolved:
                    try:
                        entity = await client.get_input_entity(target_group)
                        entity_type = type(entity).__name__
                        logger.info(f"Found entity via get_input_entity: {entity_type}")
                        
                        # InputPeerChat eski format - Telegram endi superguruhlar uchun ishlamaydi
                        # Shuning uchun integer ID'ni ishlatamiz (Telethon avtomatik convert qiladi)
                        if isinstance(entity, InputPeerChat):
                            logger.warning("InputPeerChat detected (old format), using integer ID instead")
                            entity = target_group  # Integer ID'ni ishlatamiz
                            # entity_resolved = False qoldiramiz, chunki integer ID'ni ishlatmoqdamiz
                        else:
                            entity_resolved = True
                    except Exception as input_error:
                        # Entity resolve qilinmadi - bu normal, chunki bot token bilan ba'zan ishlamaydi
                        logger.debug(f"get_input_entity failed (will try direct send): {input_error}")
                
                # Usul 3: Agar entity resolve qilinmagan bo'lsa, avval test xabari yuborib entity'ni cache'ga yuklaymiz
                # Bu bot token bilan ishlatganda entity'ni resolve qilish uchun zarur
                if not entity_resolved:
                    logger.info(f"Entity not resolved, trying to send a test message to cache the entity...")
                    try:
                        # Avval test xabari yuborib entity'ni cache'ga yuklaymiz
                        # Bu bot token bilan ishlatganda entity'ni resolve qilish uchun zarur
                        await client.send_message(target_group, ".")
                        logger.info("Test message sent successfully, entity should be cached now")
                        # Endi entity'ni qayta resolve qilishga urinamiz
                        try:
                            entity = await client.get_entity(target_group)
                            logger.info(f"Entity resolved after test message: {type(entity).__name__}")
                            entity_resolved = True
                        except Exception:
                            # Agar hali ham ishlamasa, integer ID'ni ishlatamiz
                            logger.info("Entity still not resolved, using integer ID")
                            entity = target_group
                    except Exception as test_msg_error:
                        error_msg = str(test_msg_error).lower()
                        if "could not find" in error_msg or "not found" in error_msg:
                            logger.error(f"Cannot send test message: Bot cannot access group/channel with ID {target_group}")
                            logger.error("Make sure:")
                            logger.error("1. Bot is added to the group/channel")
                            logger.error("2. Bot has permission to send messages")
                            logger.error("3. GROUP_ID is correct")
                            if client:
                                try:
                                    await client.disconnect()
                                except:
                                    pass
                            raise ValueError(f"Cannot access group/channel with ID {target_group}. Make sure the bot is added to the group and has proper permissions.")
                        else:
                            # Boshqa xatolik - integer ID bilan urinib ko'ramiz
                            logger.warning(f"Test message failed (non-critical): {test_msg_error}")
                            logger.info("Trying direct send with integer ID")
                            entity = target_group
                
                file_size_str = f"{file_size / 1024 / 1024:.2f} MB" if file_size else "unknown size"
                logger.info(f"Sending file to Telegram: {filename} ({file_size_str})")
                
                # Entity yoki integer ID'ni ishlatamiz
                # Agar entity InputPeerChat bo'lsa yoki resolve qilinmagan bo'lsa, integer ID'ni ishlatamiz
                # Telethon send_file() chaqiruvida avtomatik ravishda resolve qiladi
                
                # InputPeerChat yoki boshqa noto'g'ri format bo'lsa, darhol integer ID'ni ishlatamiz
                if isinstance(entity, InputPeerChat):
                    logger.warning("InputPeerChat detected, using integer ID directly")
                    entity = target_group
                
                try:
                    await _dispatch_send(
                        client,
                        entity,  # Resolved entity yoki integer ID
                        payload,
                        filename,
                        caption,
                        file_size,
                        TELEGRAM_CHUNK_SIZE_BYTES,
                        button_text,
                        button_url,
                        button_active,
                    )
                except PeerIdInvalidError as peer_error:
                    # Agar PeerIdInvalidError bo'lsa va entity hali ham InputPeerChat yoki boshqa noto'g'ri format bo'lsa,
                    # integer ID bilan qayta urinamiz
                    if isinstance(entity, (InputPeerChat, InputPeerChannel, InputPeerUser)) or (isinstance(entity, int) and entity != target_group):
                        logger.warning(f"PeerIdInvalidError with entity type {type(entity).__name__}, retrying with integer ID {target_group}")
                        # Payload'ni qayta o'qish uchun seek qilamiz
                        if hasattr(payload, 'seek'):
                            try:
                                payload.seek(0)
                            except:
                                pass
                        try:
                            await _dispatch_send(
                                client,
                                target_group,  # Integer ID'ni to'g'ridan-to'g'ri ishlatamiz
                                payload,
                                filename,
                                caption,
                                file_size,
                                TELEGRAM_CHUNK_SIZE_BYTES,
                                button_text,
                                button_url,
                                button_active,
                            )
                        except PeerIdInvalidError:
                            # Agar integer ID ham ishlamasa, bot guruhga qo'shilmagan yoki ruxsati yo'q
                            logger.error(f"PeerIdInvalidError even with integer ID {target_group}")
                            logger.error("This means the bot cannot access the group/channel.")
                            logger.error("Possible reasons:")
                            logger.error("1. Bot is NOT added to the group/channel")
                            logger.error("2. Bot has NO permission to send messages")
                            logger.error("3. GROUP_ID is incorrect")
                            raise ValueError(f"Cannot send file: Bot cannot access group/channel with ID {target_group}. Make sure the bot is added to the group and has permission to send messages.")
                    else:
                        # Boshqa PeerIdInvalidError - bot guruhga qo'shilmagan yoki ruxsati yo'q
                        logger.error(f"PeerIdInvalidError with integer ID {target_group}")
                        logger.error("This means the bot cannot access the group/channel.")
                        logger.error("Possible reasons:")
                        logger.error("1. Bot is NOT added to the group/channel")
                        logger.error("2. Bot has NO permission to send messages")
                        logger.error("3. GROUP_ID is incorrect")
                        raise ValueError(f"Cannot send file: Bot cannot access group/channel with ID {target_group}. Make sure the bot is added to the group and has permission to send messages.")
                
                logger.info(f"File sent successfully: {filename}")
                
                # Muvaffaqiyatli yuborildi, disconnect qilamiz
                if client:
                    try:
                        await client.disconnect()
                    except:
                        pass
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
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
            client = None
            continue
            
        except SessionPasswordNeededError:
            logger.error("Session password needed - this should not happen with bot token")
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
            raise RPCError("Session password needed")
            
        except (sqlite3.OperationalError, Exception) as db_error:
            error_str = str(db_error).lower()
            if "database is locked" in error_str:
                logger.warning(f"Database locked error, retrying... (attempt {retry_count + 1}/{max_retries})")
                retry_count += 1
                if retry_count >= max_retries:
                    if client:
                        try:
                            await client.disconnect()
                        except:
                            pass
                    raise RPCError(f"Database locked after {max_retries} attempts")
                await asyncio.sleep(1 + retry_count)  # Exponential backoff
                if client:
                    try:
                        await client.disconnect()
                    except:
                        pass
                client = None
                # Payload'ni qayta o'qish uchun seek qilamiz
                if hasattr(payload, 'seek'):
                    try:
                        payload.seek(0)
                    except:
                        pass
                continue
            elif isinstance(db_error, sqlite3.OperationalError):
                logger.error(f"SQLite error: {db_error}", exc_info=True)
                if client:
                    try:
                        await client.disconnect()
                    except:
                        pass
                raise
            else:
                # Boshqa xatoliklar
                logger.error(f"Unexpected error: {db_error}", exc_info=True)
                if client:
                    try:
                        await client.disconnect()
                    except:
                        pass
                raise
                
        except ValueError as exc:
            # ValueError - entity topilmadi yoki noto'g'ri (bot guruhga qo'shilmagan)
            error_msg = str(exc).lower()
            if "could not find" in error_msg or "not found" in error_msg or "not in the group" in error_msg:
                logger.error(f"Entity resolution failed: {exc}")
                logger.error("This error means the bot cannot find the group/channel.")
                logger.error("Possible reasons:")
                logger.error("1. Bot is NOT added to the group/channel")
                logger.error("2. GROUP_ID is incorrect")
                logger.error("3. Bot was removed from the group")
                logger.error("4. Bot doesn't have permission to access the group")
                if client:
                    try:
                        await client.disconnect()
                    except:
                        pass
                # Bu xatolikni retry qilish kerak emas - bot guruhga qo'shilmagan
                raise ValueError(f"Cannot send file: Bot cannot access group/channel with ID {target_group}. Make sure the bot is added to the group and has proper permissions.")
            else:
                # Boshqa ValueError'lar
                logger.error(f"ValueError: {exc}", exc_info=True)
                if client:
                    try:
                        await client.disconnect()
                    except:
                        pass
                raise
                
        except PeerIdInvalidError as exc:
            # PeerIdInvalidError - bot guruhga qo'shilmagan yoki ruxsati yo'q
            error_msg = str(exc).lower()
            logger.error(f"PeerIdInvalidError: {exc}")
            logger.error("This usually means:")
            logger.error("1. Bot is NOT added to the group/channel")
            logger.error("2. Bot has NO permission to send messages")
            logger.error("3. GROUP_ID is incorrect")
            logger.error("4. Group was upgraded to supergroup (use new ID)")
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
            raise ValueError(f"Cannot send file: Bot cannot access group/channel with ID {target_group}. Make sure the bot is added to the group and has permission to send messages.")
            
        except RPCError as exc:
            error_msg = str(exc).lower()
            # Agar "could not find" xatoligi bo'lsa, bu ham entity topilmaganligini ko'rsatadi
            if "could not find" in error_msg or "not found" in error_msg:
                logger.error(f"RPC error - Entity not found: {exc}")
                logger.error("This usually means:")
                logger.error("1. Bot is NOT added to the group/channel")
                logger.error("2. GROUP_ID is incorrect")
                logger.error("3. Bot was removed from the group")
                if client:
                    try:
                        await client.disconnect()
                    except:
                        pass
                raise ValueError(f"Cannot send file: Bot cannot access group/channel with ID {target_group}. Make sure the bot is added to the group and has proper permissions.")
            
            logger.error(f"RPC error (attempt {retry_count + 1}/{max_retries}): {exc}")
            retry_count += 1
            if retry_count >= max_retries:
                if client:
                    try:
                        await client.disconnect()
                    except:
                        pass
                raise exc
            # Kichik kutish va qayta urinish
            await asyncio.sleep(2)
            # Payload'ni qayta o'qish uchun seek qilamiz
            if hasattr(payload, 'seek'):
                try:
                    payload.seek(0)
                except:
                    pass
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
            client = None
            continue
    
    # Agar barcha urinishlar muvaffaqiyatsiz bo'lsa
    raise RPCError(f"Failed to send file after {max_retries} attempts")

