import asyncio
import datetime
from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.enums import ChatType
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, BotCommand, BotCommandScope, BotCommandScopeDefault, \
    BotCommandScopeChatMember, BotCommandScopeAllPrivateChats, BotCommandScopeChat, \
    BotCommandScopeAllChatAdministrators, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated, FSInputFile
from aiogram.filters import Command, CommandStart, ChatMemberUpdatedFilter
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.event import Events
from aiogram.types import ChatJoinRequest
from datetime import datetime, timedelta, timezone
import pytz


import config
import database
import handlers_my_product
import kb
import handlers_pay
from my_admin import admin

REDIS_DSN = "redis://127.0.0.1:6379"
storage = RedisStorage.from_url(REDIS_DSN, key_builder=DefaultKeyBuilder(with_bot_id=True))

TOKEN = config.token  # Токен бота
m_admin = ""  # Админы
forum = -1002399917728
forum_url = "https://t.me/c/2399917728"  # Добавление /3 это ссылка на тему
forum_url_link = "https://t.me/+UshQe-gf0V04OTFi"

default = DefaultBotProperties(parse_mode="HTML")
bot = Bot(token=TOKEN, default=default)
dp = Dispatcher(storage=storage)
dp.include_routers(handlers_pay.call_handler, handlers_my_product.my_product_handler, admin)
timezone = pytz.timezone("Europe/Moscow")


#  На команду start
@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message, state: FSMContext):
    try:
        await state.clear()
        await set_commands()
        user_id = str(message.from_user.id)
        user_name = message.from_user.username
        print(f"{user_id} : {message.from_user.first_name} : @{message.from_user.username}")
        m = await message.answer(text=f"Добро пожаловать, {message.from_user.first_name}!")
        await message.answer(text="📜 Главное меню",
                             reply_markup=kb.start_buttons())
        database.write_user(user_id, user_name)
        await bot.delete_message(user_id, m.message_id - 1)
    except Exception as e:
        print(e)



@dp.message(Command("support"), F.chat.type == ChatType.PRIVATE)
async def stop_notif(message: Message):
    user_id = str(message.from_user.id)

    await bot.send_message(user_id, text="Здравствуйте. По всем вопросам в чат: <a href='https://t.me/+JJtf6d9WsGFkMjEy'>Обсуждения и общение</a>")


@dp.message(Command("stop"), F.chat.type == ChatType.PRIVATE)
async def stop_notif(message: Message):
    user_id = str(message.from_user.id)
    try:
        database.add_notif(user_id, "stop")
        m = await bot.send_message(user_id, text="🔕 Оповешения выключены")
    except Exception as e:
        print(e)



async def set_commands():
    commands = [
        BotCommand(
            command='start',
            description='♻️  Главное меню | Начать сначала'
        ),
        BotCommand(
            command='stop',
            description='Сбросить оповещения'
        ),
        BotCommand(
            command='support',
            description='Связь с админом'
        ),

    ]
    await bot.set_my_commands(commands, BotCommandScopeDefault())


# Вступление с подачей заявки
@dp.chat_join_request()
async def handle_join(event: ChatJoinRequest):
    user = event.from_user
    await bot.approve_chat_join_request(chat_id=event.chat.id, user_id=user.id)
    date = database.date_product_end(str(user.id))
    if date:
        await bot.send_message(chat_id=user.id,
                               text="Ваша заявка на вступление в группу одобрена\n"
                                    "Продуктивной работы!. 🚀")


    # await bot.ban_chat_member(chat_id=-1001246648784, user_id=user.id)
    # await bot.unban_chat_member(chat_id=-1001246648784, user_id=user.id)  # Чтобы не было перманентного бана

    # #  Проверка есть ли у юзера подписка
    # date = database.date_product_end(str(user.id))
    # if date:
    #     await bot.approve_chat_join_request(chat_id=event.chat.id, user_id=user.id)


# Вступление с пригласительной ссылкой и проверкой на подписку
GROUP_ID = forum
@dp.chat_member(F.new_chat_member.status == "member")  # Отслеживаем вступление
async def user_joined(event: ChatMemberUpdated):
    user = event.new_chat_member.user
    chat = event.chat
    #  Проверка есть ли у юзера подписка, если нет то выкидываем его из чата
    date = database.date_product_end(str(user.id))
    await asyncio.sleep(3)
    if not date:
        print("Выкидываем юзера из группы")
        await bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
        await bot.unban_chat_member(chat_id=chat.id, user_id=user.id)  # Чтобы не было перманентного бана
    else:
        print("У юзера есть подписка, оставляем в чате")

async def check_and_send_reminders():
    """Проверяет подписки и отправляет напоминания об оплате за 3  2 и 1 день."""
    print("Scheduler: Запущена проверка подписок для отправки уведомлений...")
    today = datetime.now(timezone).date()
    all_users = database.all_get_users()

    for user in all_users:
        if user.date_end_product:
            try:
                days_left = (user.date_end_product - today).days
                message_text = None

                if days_left == 3:
                    message_text = "Здравствуйте! Ваша подписка закончится через 3 дня. Не забудьте ее продлить, чтобы не потерять доступ."
                elif days_left == 2:
                    message_text = "Здравствуйте! Ваша подписка закончится через 2 дня. Не забудьте ее продлить, чтобы не потерять доступ."
                elif days_left == 1:
                    message_text = "Здравствуйте! Ваша подписка истекает уже завтра. Рекомендуем продлить ее сейчас, чтобы избежать перерывов в доступе."
                elif days_left < 0:
                    message_text = "Подписка закончилась, чтобы брать заказ в вип группе оплатите подписку в течении 15 дней. Иначе вы будете исключены из группы."

                if message_text:
                    await bot.send_message(user.user_id, message_text, reply_markup=kb.start_buttons())
                    print(f"Отправлено уведомление пользователю {user.user_name} ({user.user_id}), осталось дней: {days_left}")
                    await asyncio.sleep(15) # задержка чтобы не получить флудвейт
            except Exception as e:
                print(f"Ошибка при отправке уведомления пользователю {user.user_id}: {e}")

async def start_all_test_user():
    
    users = database.all_get_users()
    try:
        bd = FSInputFile(path="database.db")
        await bot.send_document(chat_id=config.admins[1],document=bd)

        bd = FSInputFile(path="database.db")
        await bot.send_document(chat_id=config.admins[0], document=bd)
    except Exception as e:
        print(e)

    try:
        today = datetime.now(timezone).date()
        for user in users:
            if user.date_end_product:
                if today > user.date_end_product:
                    days_expired = (today - user.date_end_product).days
                    # Если прошло 15 или более дней без оплаты - исключаем
                    if days_expired >= 15 and days_expired  <= -30:
                        try:
                            await asyncio.sleep(5)
                            await bot.ban_chat_member(chat_id=forum, user_id=user.user_id)
                            await bot.unban_chat_member(chat_id=forum, user_id=user.user_id)
                            print(f"У {user.user_name} подписка истекла {days_expired} дней назад, он исключен из группы")
                        except Exception as e:
                            print(f"Не удалось исключить {user.user_name}, ошибка: {e}")
                    else:
                        # Если прошло меньше 15 дней - ничего не делаем, даем льготный период
                        print(f"У {user.user_name} подписка истекла, но он в льготном периоде ({days_expired} из 15 дней)")
                else:
                    print(f"У {user.user_name} есть активная подписка")
            

    except Exception as e:
        print(e)

scheduler = AsyncIOScheduler()
scheduler.add_job(start_all_test_user, 'interval', seconds=86400)
scheduler.add_job(check_and_send_reminders, 'cron', hour=13, minute=50)




async def ai_bot(): # Запуск бота на aiogram
    print("Aiogram бот запущен!")
    await dp.start_polling(bot, allowed_updates=[
        "message",
        "inline_query",
        "chat_member",
        "my_chat_member",
        "callback_query",
        "chat_join_request",
    ])

