import asyncio
from telegram import Bot
from dotenv import load_dotenv
import os

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

async def get_updates():
    bot = Bot(token=BOT_TOKEN)
    updates = await bot.get_updates()
    
    print("🔍 Поиск ID групп...\n")
    
    for update in updates:
        if update.message and update.message.chat.type in ['group', 'supergroup', 'channel']:
            print(f"Название: {update.message.chat.title}")
            print(f"ID: {update.message.chat.id}")
            print(f"Тип: {update.message.chat.type}")
            print("-" * 40)
    
    print("\n💡 Добавьте бота в группы и отправьте сообщение, чтобы увидеть ID")

if __name__ == '__main__':
    asyncio.run(get_updates())
