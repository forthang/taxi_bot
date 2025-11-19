import asyncio
import itertools
import json
import random
import time
import re

from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon.tl import functions, types
from telethon.sync import TelegramClient, events
from telethon.tl import functions, types
from telethon.tl.functions.account import UpdateUsernameRequest
from telethon.tl.functions.messages import GetMessagesViewsRequest, GetDialogsRequest, DeleteHistoryRequest
from telethon.tl.functions.stories import SendStoryRequest
from telethon.tl.types import SendMessageTypingAction, InputMediaUploadedPhoto
from aiogram import Bot
import logging
from telethon.extensions.html import HTMLParser
import city_config
import config
import database
from city_config import blacklist
from main import bot

from pathlib import Path
from datetime import timedelta
import os, uuid

forum = config.forum


# Номера веток группы
cities = {
    "Центральный": 26,
    "ЛДНР": 74,
    "Запорожье и Херсон": 75,
    "Северо-Кавказский": 35,
    "Северо-Западный": 28,
    "Поволжье": 78,
    "Южный": 79,
    "Приволжский": 80,
    "Уральский": 82,
    "Сибирский": 32,
    "Дальневосточный": 78
}

json_file = "account/krasndr123.json"
with open(json_file, "r", encoding="utf-8") as f:
    json_data = json.load(f)

client = TelegramClient(session="account/krasndr123.session",
                        api_id=json_data["app_id"],
                        api_hash=json_data["app_hash"],
                        device_model=json_data["device"],
                        system_version=json_data["sdk"],
                        app_version=json_data["app_version"],
                        system_lang_code=json_data["system_lang_code"],
                        lang_code=json_data["lang_code"],
                        )



# общий путь к файлу, который видят ОБА процесса (положи в общую папку проекта)
LIST_FILE = "list_group_online.txt"

def _atomic_write_text(path, text: str, encoding: str = "utf-8"):
    p = Path(path)  
    p.parent.mkdir(parents=True, exist_ok=True)

    # временный файл в той же папке, имя: <оригинал>.tmp.<UUID>
    tmp = p.with_name(p.name + f".tmp.{uuid.uuid4().hex}")

    with open(tmp, "w", encoding=encoding) as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp, p)

async def _iter_all_dialogs(client):
    # основной список
    async for d in client.iter_dialogs(limit=None):
        yield d
    # архив
    async for d in client.iter_dialogs(limit=None, archived=True):
        yield d


async def collect_user_channels_and_groups(client) -> list[str]:
    """
    Возвращает строки:
      - публичный канал:  '📣 <a href='https://t.me/username'>Название</a>'
      - приватный канал:  '🔒 Название — приватный канал'
      - публичная группа: '👥 <a href='https://t.me/username'>Название</a>'
      - приватная группа: '🔐 Название — приватная группа'
    Учитываем: broadcast (каналы), megagroup (супергруппы), Chat (обычные группы).
    Охватываем и архив.
    """
    lines = []
    seen_ids = set()

    async for dialog in _iter_all_dialogs(client):
        ent = dialog.entity

        # Каналы/Супергруппы
        if isinstance(ent, types.Channel):
            if ent.id in seen_ids:
                continue
            seen_ids.add(ent.id)

            title = (ent.title or "").strip() or "(без названия)"
            # Экранируем HTML-символы в названии, чтобы избежать проблем с разметкой
            title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            username = getattr(ent, "username", None)

            if getattr(ent, "broadcast", False):
                # канал
                if username:
                    lines.append(f"📣 <a href='https://t.me/{username}'>{title}</a>")
                else:
                    lines.append(f"🔒 {title} — приватный канал")
            elif getattr(ent, "megagroup", False):
                # супергруппа
                if username:
                    lines.append(f"👥 <a href='https://t.me/{username}'>{title}</a>")
                else:
                    lines.append(f"🔐 {title} — приватная группа")

        # Обычные группы (устаревший тип)
        elif isinstance(ent, types.Chat):
            if ent.id in seen_ids:
                continue
            seen_ids.add(ent.id)

            title = (ent.title or "").strip() or "(без названия)"
            title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            username = getattr(ent, "username", None)
            if username:
                lines.append(f"👥 <a href='https://t.me/{username}'>{title}</a>")
            else:
                lines.append(f"🔐 {title} — приватная группа")

    # сортируем и убираем дубли по тексту
    lines = sorted(list(dict.fromkeys(lines)), key=str.casefold)
    return lines


async def update_channels_list_file(client):
    try:
        lines = await collect_user_channels_and_groups(client)
        if not lines:
            me = await client.get_me()
            text = "Каналы/группы не найдены." 
        else:
            text = "\n".join(lines)

        _atomic_write_text(LIST_FILE, text)
        logging.info("list_group_online.txt обновлён: %s записей", len(lines))
    except Exception as e:
        logging.exception("Ошибка при обновлении списка: %s", e)
        _atomic_write_text(LIST_FILE, f"Не удалось сформировать список: {e}")

#  Оповещение для юзера который это включил
async def send_user_notif(district, message):
    # Находим Юзера с этим городом и отправляем ему заказ
    try:
        user_id = database.get_notif_user_city(district)
        if user_id:
            await bot.send_message(chat_id=user_id,
                                   text=message)
    except Exception as e:
        try:
            user_id = database.get_notif_user_city(district)
            res = database.del_user(str(user_id))
            await bot.send_message(chat_id="-1002451573337",  # Error logs| Exception
                                   text=f"<b>send_user_notif:</b> {str(e)}\n"
                                        f"Delete: {res}")
        except Exception as e:
            await bot.send_message(chat_id="-1002451573337",  # Error logs| Exception
                                   text=f"<b>send_user_notif:</b> {str(e)}\n"
                                        )


mess_group_primary = []
mess_select_group = []
#   Отправляем заказ в общую и нужную ветку
async def send_group(text, branch, id_group, mess_id, title, district):
    global mess_group_primary
    global mess_select_group

    #  Тестирование

    url = f'<a href="https://t.me/c/{id_group}/{mess_id}">➡️ <b>{title}</b></a>'
    message = f"{text}\n\nИнформация:\n{url}"
    await send_user_notif(district, message)
    try:
        srez = message[:30]
        #  Все заказы
        if branch == 177:
            if mess_group_primary:
                if mess_group_primary[1] == srez:  # Если одинаково, то редактируем
                    print("Попал в редактирование все заказы")
                    new_mess = f"{mess_group_primary[2]}\n{url}"
                    await bot.edit_message_text(chat_id=forum,
                                                text=new_mess,
                                                message_id=mess_group_primary[0])
                    mess_group_primary[2] = new_mess

                else:
                    print("Новый заказ")
                    m = await bot.send_message(chat_id=forum,
                                               text=message,
                                               message_thread_id=branch
                                               )
                    print(m.message_id)
                    mess_group_primary[0] = m.message_id
                    mess_group_primary[1] = srez
                    mess_group_primary[2] = message
            else:
                print("Впервые во все заказы")
                m = await bot.send_message(chat_id=forum,
                                           text=message,
                                           message_thread_id=branch
                                           )
                print(m.message_id)
                mess_group_primary.append(m.message_id)
                mess_group_primary.append(srez)
                mess_group_primary.append(message)
        # Вторичная ветка
        else:
            if mess_select_group:
                #  Если срез совпал, начинаем работу с ветками
                if mess_select_group[1] == srez:
                    print("Срез совпал")
                    # Если одинаково, то редактируем. 1 ветка
                    if mess_select_group[3] == branch and not title == mess_select_group[7]:
                        print("Попал в редактирование 1 ветки")
                        new_mess = f"{mess_select_group[2]}\n{url}"
                        await bot.edit_message_text(chat_id=forum,
                                                    text=new_mess,
                                                    message_id=mess_select_group[0]) # 100
                        mess_select_group[2] = new_mess
                        mess_select_group[7] = title

                    # Если одинаково, то редактируем. 2 ветка
                    elif mess_select_group[4] == branch: # branch 2 ветки
                        print("Попал в редактирование ветки 2")
                        print(title)
                        print(mess_select_group[8])
                        if not title == mess_select_group[8]:
                            new_mess = f"{mess_select_group[6]}\n{url}"
                            await bot.edit_message_text(chat_id=forum,
                                                        text=new_mess,
                                                        message_id=mess_select_group[5])
                            mess_select_group[6] = new_mess
                            mess_select_group[8] = title
                        else:
                            return
                    else:
                        print("Новый пост ветки 2")
                        m = await bot.send_message(chat_id=forum,
                                                   text=message,
                                                   message_thread_id=branch)
                        #  Второй бранч
                        mess_select_group[4] = branch
                        mess_select_group[5] = m.message_id
                        mess_select_group[8] = title
                        return
                #  Если в mess_select_group есть, но срез не совпал
                else:
                    print("Новый 1 пост 2 ветки")
                    m = await bot.send_message(chat_id=forum,
                                               text=message,
                                               message_thread_id=branch
                                               )

                    mess_select_group.append(m.message_id)  # id первой ветки [0]
                    mess_select_group.append(srez)  # [1]
                    mess_select_group.append(message)  # [2] Пост для первой ветки
                    mess_select_group.append(branch)  # branch 1 ветки [3]

                    mess_select_group.append(0)  # 1 пост 2 ветки [4] branch 2 ветки
                    mess_select_group.append(0)  # 1 пост 2 ветки [5] message_id 2 ветки
                    mess_select_group.append(0)  # 1 пост 2 ветки [6]
                    mess_select_group.append(message)  # 1 пост 2 ветки [6]


            #  Новый 1 пост 1 ветки
            else:
                print("Новый 1 пост 1 ветки")
                m = await bot.send_message(chat_id=forum,
                                           text=message,
                                           message_thread_id=branch
                                           )

                mess_select_group.append(m.message_id) # id первой ветки [0]
                mess_select_group.append(srez) #  [1]
                mess_select_group.append(message) #  [2]
                mess_select_group.append(branch) # 1 пост 1 ветки [3]


                mess_select_group.append(0) # 1 пост 2 ветки [4] branch 2 ветки
                mess_select_group.append(0) # 1 пост 2 ветки [5] message_id 2 ветки
                mess_select_group.append(message) # 1 пост 2 ветки [6]

                # Title для проверки 1 ветки на его одинаковость
                mess_select_group.append(title) # Title для 1 ветки [7]
                mess_select_group.append(title) # Title для 1 ветки [8]

    except Exception as e:
        print(e)


@client.on(events.NewMessage)
async def my_event_handler(event):
    client.parse_mode = 'html'
    global title_groups
    print("---------------")
    text = event.message.text
    if len(text) < 20:  # Если символов меньше 30 то это скорее всего не заявка
        return
    # Проверка на blacklist
    if not any(keyword in text.replace("СЕГОДНЯ", "") for keyword in city_config.blacklist):
        print("Проверку на стоп слова прошли")

        try:
            id_channel = f"-100{str(event.peer_id.channel_id)}"
            info_channel = await client.get_entity(int(id_channel))
            title = info_channel.title
            id_group = event.peer_id.channel_id
            if str(id_group) in str(forum):  # Игнор Transfer GPT
                return
            if str(id_group) in str(2451573337):  # Игнор Error logs| Exception
                return
            if str(id_group) in str(2432810487):  # Игнор Обсуждения и общение
                return
            if str(id_group) in str(1384585087):  # спам
                return
            if str(id_group) in str(1695657275):  # спам
                return
            if str(id_group) in str(2010520161):  # спам
                return
            text = event.message.text
            mess_id = event.id
            print(title)
            if len(text) < 20: # Если символов меньше 30, то это скорее всего не заявка
                return
            res = True

            # Проверяем наличие города в тексте
            if any(keyword.lower() in text.lower()
                   for keyword in itertools.chain.from_iterable(city_config.districts.values())):
                # Отправляем во "Все заказы"
                await send_group(text, 177, id_group, mess_id, title, "Все заказы")

                # Фильтр По ключевым словам
                str_city = [] # Определяем пункт А
                for keyword in itertools.chain.from_iterable(city_config.districts.values()):
                    if keyword.lower() in text.lower():
                        str_city.append(keyword.lower())

                res_city = [str_city[0], str_city[-1]]
                print(res_city)

                positions = {city: text.lower().find(city) for city in res_city if text.lower().find(city) != -1}
                first_city = min(positions, key=positions.get) if positions else None
                print(first_city)

                #  Центральный
                if any(keyword.lower() in first_city for keyword in city_config.districts["central"]):
                    # Отправляем сообщение в нужную ветку
                    await send_group(text, 26, id_group, mess_id, title, "Центральный")
                    return
                #  ЛДНР
                if any(keyword.lower() in first_city for keyword in city_config.districts["ЛДНР"]):
                    await send_group(text, 74, id_group, mess_id, title, "ЛДНР")
                    return
                #  Запорожье и Херсон
                if any(keyword.lower() in first_city for keyword in city_config.districts["zap_her"]):
                    await send_group(text, 75, id_group, mess_id, title, "Запорожье и Херсон")
                    return
                #  Северо-Западный
                if any(keyword.lower() in first_city for keyword in city_config.districts["sev_zapad"]):
                    await send_group(text, 28, id_group, mess_id, title, "Северо-Западный")
                    return
                # Южный округ
                if any(keyword.lower() in first_city for keyword in city_config.districts["yug"]):
                    await send_group(text, 79, id_group, mess_id, title, "Южный")
                    return
                # Северо Кавказский округ
                if any(keyword.lower() in first_city for keyword in city_config.districts["sev_kav"]):
                    await send_group(text, 35, id_group, mess_id, title, "Северо-Кавказский")
                    return
                # Приволжский округ
                if any(keyword.lower() in first_city for keyword in city_config.districts["privolz"]):
                    await send_group(text, 80, id_group, mess_id, title, "Приволжский")
                    return
                # Уральский округ
                if any(keyword.lower() in first_city for keyword in city_config.districts["ural"]):
                    await send_group(text, 82, id_group, mess_id, title, "Уральский")
                    return
                #  Сибирский
                if any(keyword.lower() in first_city for keyword in city_config.districts["sibir"]):
                    await send_group(text, 32, id_group, mess_id, title, "Сибирский")
                    return
                #  Дальневосточный
                if any(keyword.lower() in first_city for keyword in city_config.districts["dalnevostok"]):
                    await send_group(text, 78, id_group, mess_id, title, "Дальневосточный")
                    return
            else:
                try:
                    await bot.send_message(chat_id="-1002451573337",  # Error logs| Exception
                                           text=f"<b>Не прошел фильтр:</b> {text}")
                except:
                    await client.send_message(entity=-1002451573337,
                                              message=f"<b>Не прошел фильтр:</b> {text}")
        except Exception as e:
            print(e)
            try:
                await bot.send_message(chat_id="-1002451573337",  # Error logs| Exception
                                       text=f"<b>my_event_handler:</b> {str(e)}")
            except Exception as error:
                await client.send_message(entity=-1002451573337,  # Error logs| Exception
                                          message=f"<b>my_event_handler:</b> {str(e)}\n"
                                                  f"{error}")

# Настройка логирования: запись в файл logs.txt
logging.basicConfig(
    level=logging.INFO,  # Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(levelname)s - %(message)s",  # Формат сообщения
    datefmt="%Y-%m-%d %H:%M:%S",  # Формат даты и времени
    handlers=[
        logging.FileHandler("logs.txt", encoding="utf-8"),  # Запись в файл
        logging.StreamHandler()  # Вывод в консоль
    ]
)


async def telebot():
    await client.start()
    me = await client.get_me()
    print(f"Юзер бот {me.username} запущен!")

    # if me:
        # logging.INFO(f"Юзер бот запущен: {me.username}")
        # print("Юзер бот запущен!")

    await update_channels_list_file(client)
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(update_channels_list_file, "interval", hours=24, args=[client],)

    scheduler.start()




    users = await client.get_participants(config.forum)
    all_users = []
    for user in users:
        user_id = str(user.id)
        user_name = user.username
        all_users.append(user.id)
        database.write_user(user_id, user_name)
    try:
        await bot.send_message(chat_id=config.admins[0],
                               text=f"Запуск бота!\n"
                                    f"Всего: {len(all_users)}")
        for user in users:
            user_id = str(user.id)
            date = database.date_product_end(user_id)
            database.del_ids()
            await asyncio.sleep(1)
            if not date: # Если False
                try:
                    await bot.ban_chat_member(chat_id=forum, user_id=user_id)
                    await bot.unban_chat_member(chat_id=forum,
                                                user_id=user_id)  # Чтобы не было перманентного бана

                    await bot.send_message(chat_id=config.admins[0],
                                           text=f"У @{user.username} кончилась подписка, он исключен из группы")
                    print(f"У {user.username} кончилась подписка, он исключен из группы")

                except Exception as e:
                        await bot.send_message(chat_id=config.admins[0],
                                               text=f"{str(e)}\n"
                                                    f"{user.id} @{user.username}")
                        try:
                            await bot.ban_chat_member(chat_id=forum, user_id=user_id)
                            await bot.unban_chat_member(chat_id=forum,
                                                        user_id=user_id)  # Чтобы не было перманентного бана

                            await bot.send_message(chat_id=config.admins[0],
                                                   text=f"Удален из группы\n"
                                                        f"{user.id} @{user.username}")
                        except Exception as e:
                            await bot.send_message(chat_id=config.admins[0],
                                                   text=f"Не получается удалить"
                                                        f"{str(e)}\n"
                                                        f"{user.id} @{user.username}")

            else:
                pass
                # res = database.date_product(user_id)
                # await bot.send_message(chat_id=config.admins[0],
                #                        text=f"@{user.username}: {res.replace("Ваш", "")}")
    except Exception as e:
        await bot.send_message(chat_id=config.admins[0],
                               text=f"{e}")