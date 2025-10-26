import asyncio
from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, BotCommand, BotCommandScope, BotCommandScopeDefault, \
    BotCommandScopeChatMember, BotCommandScopeAllPrivateChats, BotCommandScopeChat, \
    BotCommandScopeAllChatAdministrators, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated, FSInputFile
from aiogram.filters import Command, CommandStart, ChatMemberUpdatedFilter
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from oauth2client.service_account import ServiceAccountCredentials
import gspread
import city_config

# Подключение к Google Sheets с использованием учетных данных
json_key = "search-new-keys.json"
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
credentials = ServiceAccountCredentials.from_json_keyfile_name(json_key, scope)
client = gspread.authorize(credentials)
base_group = "https://docs.google.com/spreadsheets/d/1ykAT1IyngkqoD-MPc69SWU9J9_Gfb3xLr9v-ZmOVa_8/edit?usp=sharing"
filters = "https://docs.google.com/spreadsheets/d/1BhIRhT9cGBILyyqUHfQvho94B_kOMCgrSr6dTtQV67M/edit?usp=sharing"



import database
import kb
import config


class AdminFSM(StatesGroup):
    myadmin = State()
    vip_one = State()
    list_group = State()
    update_fag = State()

admin = Router()

# @admin.message(Command("reset_bd"))
# async def reset_bd(message: Message, bot: Bot):
#     res = database.null_date_product()
#     if res:
#         await bot.send_message(chat_id=message.from_user.id, text="Выполнено!")

@admin.message(Command("myadmin"))
async def test(message: Message, state: FSMContext, bot: Bot):
    user_id = str(message.from_user.id)
    if user_id in config.admins:
        await bot.send_message(chat_id=user_id,
                               text="Выберите действие",
                               reply_markup=kb.admin_buttons()
                               )
        await state.set_state(AdminFSM.myadmin)

@admin.message(Command("developer"))
async def developer(message: Message, bot: Bot):
    user_id = str(message.from_user.id)
    await bot.send_message(chat_id=user_id,
                           text=f"Разработчик: @MansurTGram")

@admin.callback_query(F.data == "backup")
async def backup(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    user_id = callback.from_user.id
    bd = FSInputFile(path="database.db")
    await bot.send_document(chat_id=user_id,
                            document=bd)

# Запуск обновления фильтров
@admin.callback_query(F.data == "filters")
async def filters(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    await bot.send_message(chat_id=user_id, text="Собираю данные из Гугл таблицы...")
    res = await update_filters()
    if res:
        await bot.send_message(chat_id=user_id, text=f"Ошибка: {str(res)}")
    else:
        await bot.send_message(chat_id=user_id, text=f"Фильтры обновлены")

async def update_filters():
    try:
        filters = "https://docs.google.com/spreadsheets/d/1BhIRhT9cGBILyyqUHfQvho94B_kOMCgrSr6dTtQV67M/edit?usp=sharing"
        worksheet = client.open_by_url(filters)
        spreadsheet = worksheet.get_worksheet(0)
        # Обновление blacklist
        res = spreadsheet.col_values(1)
        city_config.blacklist[:] = res  # blacklist
        #  Обновление central
        res = spreadsheet.col_values(2)
        city_config.districts["central"][:] = res
        #  Обновление ЛДНР
        res = spreadsheet.col_values(3)
        city_config.districts["ЛДНР"][:] = res
        #  Обновление zap-her
        res = spreadsheet.col_values(4)
        city_config.districts["zap_her"][:] = res
        #  Обновление sev_zapad
        res = spreadsheet.col_values(5)
        city_config.districts["sev_zapad"][:] = res
        #  Обновление yug
        res = spreadsheet.col_values(6)
        city_config.districts["yug"][:] = res
        #  Обновление sev_kav
        res = spreadsheet.col_values(7)
        city_config.districts["sev_kav"][:] = res
        #  Обновление privolz
        res = spreadsheet.col_values(8)
        city_config.districts["privolz"][:] = res
        #  Обновление ural
        res = spreadsheet.col_values(9)
        city_config.districts["ural"][:] = res
        #  Обновление sibir
        res = spreadsheet.col_values(10)
        city_config.districts["sibir"][:] = res
        #  Обновление dalnevostok
        res = spreadsheet.col_values(11)
        city_config.districts["dalnevostok"][:] = res
        return False
    except Exception as e:
        return e





# Обновление руководства
@admin.callback_query(F.data == "update_fag")
async def update_fag(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await bot.send_message(chat_id=user_id, text="Отправьте  текст нового руководства\n\n"
                                                 "Принимается только текст, без фото и видео. "
                                                 "Но, вы можете отправить ссылку на фото/видео")
    await state.set_state(AdminFSM.update_fag)

@admin.message(AdminFSM.update_fag)
async def update_fag(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    text = message.html_text
    with open("update_fag.txt", "w") as f:
        f.write(text)
    await bot.send_message(chat_id=user_id, text="Руководство обновлено")
    with open("update_fag.txt", "r") as f:
        fag = f.read()
    await bot.send_message(chat_id=user_id, text=fag,
                           reply_markup=kb.admin_buttons())



@admin.callback_query(F.data == "logs")
async def logs(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    user_id = callback.from_user.id
    bd = FSInputFile(path="logs.txt")
    await bot.send_document(chat_id=user_id,
                            document=bd)

@admin.callback_query(F.data == "stata")
async def state(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    user_id = callback.from_user.id
    users = database.all_state()
    await bot.send_message(chat_id=user_id,
                           text=f"Всего запустивших бота: <b>{users[0]}</b>\n"
                                f"Всего с Тестовой подпиской: <b>{users[3]}</b>\n"
                                f"Всего с VIP подпиской: <b>{users[1]}</b>\n"
                                f"Всего с Premium подпиской: <b>{users[2]}</b>\n")


#  Обновление списка групп
@admin.callback_query(F.data == "list_group")
async def list_group(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await bot.send_message(chat_id=user_id,
                           text="Забираем данные из Гугл таблицы...")
    list_group = ""
    res = client.open_by_url(base_group).sheet1
    for i in res.get():
        if not "Ссылка" in i[1]:
            print(i)
            list_group += f"<a href='{i[1]}'>{i[0]}</a>\n"
    with open("list_group.txt", "w") as f:
        f.write(list_group)
    await asyncio.sleep(3)
    await bot.send_message(chat_id=user_id,
                           text="Данные обновлены, отправляю вам обновленный список групп")
    await asyncio.sleep(3)
    with open("list_group.txt", "r") as f:
        groups = f.read()
        await bot.send_message(chat_id=user_id,
                               text=groups, disable_web_page_preview=True)





@admin.callback_query(AdminFSM.myadmin)
async def myadmin(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = str(callback.from_user.id)
    date = callback.data
    await state.update_data(date=date)
    if date == "extend_one":
        await callback.answer()
        await bot.send_message(chat_id=user_id,
                               text="Вы выбрали продление VIP для одного пользователя\n"
                                    "Отправьте его username и срок продления в днях через пробел\n"
                                    "Пример: @username 10"
                               )
    elif date == "extend_premium_one":
        await callback.answer("🛠 В разработке")
        # await bot.send_message(chat_id=user_id,
        #                        text="Вы выбрали продление PREMIUM для одного пользователя\n"
        #                             "Отправьте его username и срок продления в днях через пробел\n"
        #                             "Пример: @username 10")

    elif date == "extend_all":
        await callback.answer("")
        await bot.send_message(chat_id=user_id,
                               text="Вы выбрали продление VIP для ВСЕХ пользователей, у которых есть или ранее была "
                                    "VIP подписка\n"
                                    "Введите количество дней на которое продлится\n"
                                    "Пример: 10")


    elif date == "extend_premium_all":
        await callback.answer("🛠 В разработке")
        # await bot.send_message(chat_id=user_id,
        #                        text="Вы выбрали продление PREMIUM для ВСЕХ пользователей\n"
        #                             "Введите количество дней на которое продлится всем юзерам\n"
        #                             "Пример: 10")
    elif date == "test_period":
        await callback.answer()
        await bot.send_message(chat_id=user_id,
                               text="Вы выбрали продление ТЕСТОВОГО ПЕРИОДА для пользователей у "
                                    "которых нет и не было VIP или PREMIUM подписки\n"
                                    "Если пользователь ранее покупал подписку, то выберите для него VIP продление\n\n"
                                    "Введите количество дней на которое продлится ТЕСТОВЫЙ ПЕРИОД\n"       
                                    "Пример: 10")
    elif date ==  "mailing":
        await callback.answer()
        await bot.send_message(chat_id=user_id,
                               text="Отправьте мне текстовое сообщение которое получат все пользователи бота\n"
                                    "Принимается только текст, без фото и видео. Но, вы можете отправить ссылку на фото/видео")

    elif date == "mailing_vip":
        await callback.answer()
        await bot.send_message(chat_id=user_id,
                               text="Отправьте мне текстовое сообщение которое получат все VIP пользователи бота\n"
                                    "Принимается только текст, без фото и видео. Но, вы можете отправить ссылку на фото/видео")


@admin.message(AdminFSM.myadmin)
async def extend(message: Message, state: FSMContext, bot: Bot):
    user_id = str(message.from_user.id)
    try:
        text = message.text.split(" ")
        date = (await state.get_data()).get("date")
        if date == "extend_one":
            user_name = str(text[0].strip().replace("@", "").replace("https://t.me/", ""))
            date_end = int(text[1].strip())
            print(user_name, date_end)
            res = database.vip_one(str(user_name), date_end)
            await bot.send_message(chat_id=user_id,
                                   text=f"Продлено до: {res}",
                                   reply_markup=kb.admin_buttons())
        elif date == "extend_all":
            time = message.text.strip().replace(".", "")
            try:
                database.vip_all_date(int(time))
                await bot.send_message(chat_id=user_id,
                                           text=f"Вы продлили всем пользователям(У кого был VIP) VIP подписку на количество дней: "
                                                f"<b>{time}</b>",
                                           reply_markup=kb.admin_buttons())
            except Exception as e:
                await bot.send_message(chat_id=user_id,
                                       text=f"Что то пошло не так, пожалуйста отправьте количество дней только цифрами")

        elif date == "test_period":
            time = message.text.strip().replace(".", "")
            try:
                res = database.test_all_date(int(time))
                if res:
                    await bot.send_message(chat_id=user_id,
                                           text=f"Вы продлили всем пользователям Тестовую подписку на количество дней: "
                                                f"<b>{time}</b>",
                                           reply_markup=kb.admin_buttons())
            except Exception as e:
                await bot.send_message(chat_id=user_id,
                                       text=f"Что то пошло не так, пожалуйста отправьте количество дней только цифрами")

        elif date == "mailing":
            text_mailing = message.html_text
            try:
                m = await bot.send_message(chat_id=user_id,
                                       text="Начата рассылка всем пользователям бота с интервалом в 10 секунд")

                users = database.all_get_users()
                for user in users:
                    try:
                       await bot.send_message(chat_id=user.user_id,
                                              text=text_mailing)
                       print("Сообщение отправлено")
                    except:
                        database.del_user(user.user_id)
                        print("Юзер удален")
                    await asyncio.sleep(10)

                await bot.send_message(chat_id=user_id,
                                       text="Рассылка завершена")
            except Exception as e:
                await bot.send_message(chat_id=user_id,
                                       text=f"Произошла ошибка: {str(e)}")


        elif date == "mailing_vip":
            text_mailing = message.html_text
            try:
                m = await bot.send_message(chat_id=user_id,
                                       text="Начата рассылка всем VIP пользователям бота с интервалом в 10 секунд")
                users = database.all_get_users()
                for user in users:

                    if user.type_product == "VIP":
                        try:
                           await bot.send_message(chat_id=user.user_id,
                                                  text=text_mailing)
                           print("Сообщение отправлено")
                        except Exception as e:
                            database.del_user(user.user_id)
                            print("Юзер удален\n"
                                  f"{e}")
                        await asyncio.sleep(10)




                await bot.send_message(chat_id=user_id,
                                       text="Рассылка завершена")
            except Exception as e:
                await bot.send_message(chat_id=user_id,
                                       text=f"Произошла ошибка: {str(e)}")

    except Exception as e:
        print(e)





