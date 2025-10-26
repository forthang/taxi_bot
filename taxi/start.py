import asyncio


from main import ai_bot, scheduler
from my_admin import update_filters
from user_bot import telebot


async def main():
    scheduler.start()
    await asyncio.gather(ai_bot(), update_filters(), telebot()) #ai_bot()


if __name__ == '__main__':
    asyncio.run(main())