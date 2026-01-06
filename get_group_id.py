"""
GROUP_ID ni topish uchun yordamchi skript.
Bot'ni guruhga qo'shing va bu skriptni ishga tushiring.

Eslatma: Bu skript endi BOT_TOKEN ni .env dagi
`BOT_TOKEN` environment variable'dan oladi.
"""
import os
import asyncio
from telethon import TelegramClient
from config import API_ID, API_HASH


async def list_groups():
    """Bot qo'shilgan barcha guruhlarni ko'rsatadi"""
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        print("❌ BOT_TOKEN topilmadi.")
        print("Iltimos .env faylida yoki environment'da BOT_TOKEN ni o'rnating.")
        return

    client = TelegramClient('sessions/get_group_id', API_ID, API_HASH)
    
    try:
        await client.start(bot_token=bot_token)
        print("\n" + "="*60)
        print("Bot qo'shilgan guruhlar va kanallar:")
        print("="*60 + "\n")
        
        groups_found = False
        async for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                groups_found = True
                print(f"📌 Nomi: {dialog.name}")
                print(f"   ID: {dialog.id}")
                print(f"   Turi: {'Kanal' if dialog.is_channel else 'Guruh'}")
                print(f"   Username: @{dialog.entity.username}" if dialog.entity.username else "   Username: Yo'q")
                print("-" * 60)
        
        if not groups_found:
            print("❌ Bot hech qanday guruhga qo'shilmagan!")
            print("\nQadamlar:")
            print("1. Bot'ni guruhga qo'shing")
            print("2. Bot'ga yozish huquqi bering")
            print("3. Bu skriptni qayta ishga tushiring")
        else:
            print("\n✅ Yuqoridagi ID ni front-end yoki request parametrlarida GROUP_ID sifatida ishlating")
            print("   Masalan: group_id=-1001234567890")
        
    except Exception as e:
        print(f"❌ Xatolik: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(list_groups())

