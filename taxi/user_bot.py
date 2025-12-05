import asyncio
import itertools
import json
import logging
import html
import re  # Для очистки текста при сравнении
from aiogram import Bot
from telethon import TelegramClient, events
from telethon.tl import types
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import city_config
import config
import database
from main import bot

# --- КОНФИГУРАЦИЯ ---
forum = config.forum
LIST_FILE = "list_group_online.txt"
HISTORY_SIZE = 30 # Помним последние 30 заказов (чтобы точно ловить дубли)

# Глобальные переменные
titles_cache = {}  
mess_history = []  # Список словарей: [{'msg_id':..., 'hash':..., 'text':..., 'authors':[]}]
msg_queue = asyncio.Queue()  

# Загрузка конфига
json_file = "account/krasndr123.json"
with open(json_file, "r", encoding="utf-8") as f:
    json_data = json.load(f)

# --- КЛИЕНТ (ТУРБО РЕЖИМ) ---
client = TelegramClient(
    session="account/krasndr123.session",
    api_id=json_data["app_id"],
    api_hash=json_data["app_hash"],
    device_model=json_data["device"],
    system_version=json_data["sdk"],
    app_version=json_data["app_version"],
    system_lang_code=json_data["system_lang_code"],
    lang_code=json_data["lang_code"],
    sequential_updates=False 
)

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler()]
)

# Функция для создания "слепка" текста (убираем смайлы, пробелы, регистр)
def get_text_hash(text):
    # Оставляем только буквы и цифры
    return "".join(filter(str.isalnum, text.lower()))[:100]

# --- ВОРКЕР (ОТПРАВЩИК) ---
async def worker():
    print("🚀 Воркер запущен и ждет заказы...")
    while True:
        task = await msg_queue.get()
        try:
            text, id_group, mess_id, title, district = task
            await send_to_main_branch(text, id_group, mess_id, title, district)
            await asyncio.sleep(0.05)
        except Exception as e:
            print(f"Ошибка в воркере: {e}")
        finally:
            msg_queue.task_done()

# --- ФУНКЦИЯ ОТПРАВКИ И РЕДАКТИРОВАНИЯ ---
async def send_to_main_branch(text, id_group, mess_id, title, district):
    global mess_history
    
    # Подготовка данных
    safe_title = html.escape(title)
    # Ссылка без -100
    clean_group_id = str(id_group).replace("-100", "")
    url = f'<a href="https://t.me/c/{clean_group_id}/{mess_id}">➡️ <b>{safe_title}</b></a>'
    
    # Формируем полный текст (он нужен, если это будет новое сообщение)
    full_message = f"{text}\n\nИнформация:\n{url}"
    
    # Создаем хеш для сравнения (чистый текст заказа)
    current_hash = get_text_hash(text)

    # Уведомление юзеру
    asyncio.create_task(send_user_notif(district, full_message))

    try:
        # 1. Ищем дубль в истории
        found_item = None
        for item in mess_history:
            if item['hash'] == current_hash:
                found_item = item
                break
        
        if found_item:
            # --- ЭТО ДУБЛЬ ---
            
            # Если этот канал уже есть в списке авторов этого сообщения -> выходим
            if safe_title in found_item['authors']:
                return

            print(f"✏️ Редактируем заказ (добавляем {safe_title})")
            
            # Берем старый текст (с уже накопленными ссылками) и добавляем новую
            new_text_body = f"{found_item['text']}\n{url}"
            
            # Редактируем сообщение в канале
            await bot.edit_message_text(chat_id=forum,
                                        text=new_text_body,
                                        message_id=found_item['msg_id'],
                                        parse_mode="HTML",
                                        disable_web_page_preview=True)
            
            # Обновляем данные в памяти
            found_item['text'] = new_text_body
            found_item['authors'].append(safe_title)
            
            # Перемещаем сообщение в конец списка (как самое свежее), чтобы оно дольше жило в кеше
            mess_history.remove(found_item)
            mess_history.append(found_item)

        else:
            # --- ЭТО НОВЫЙ ЗАКАЗ ---
            print(f"📩 Новый заказ ({safe_title})")
            
            m = await bot.send_message(chat_id=forum,
                                       text=full_message,
                                       message_thread_id=177,
                                       parse_mode="HTML",
                                       disable_web_page_preview=True)
            
            # Добавляем в историю
            new_item = {
                'msg_id': m.message_id,
                'hash': current_hash,
                'text': full_message,   # Храним текст ВМЕСТЕ со ссылками
                'authors': [safe_title] # Список каналов, которые запостили это
            }
            mess_history.append(new_item)
            
            # Если история переполнилась, удаляем самый старый элемент
            if len(mess_history) > HISTORY_SIZE:
                mess_history.pop(0)

    except Exception as e:
        print(f"Ошибка отправки: {e}")

async def send_user_notif(district, message):
    try:
        user_id = database.get_notif_user_city(district)
        if user_id:
            await bot.send_message(chat_id=user_id, text=message)
    except Exception:
        pass 

# --- ОБРАБОТЧИК СООБЩЕНИЙ ---
@client.on(events.NewMessage)
async def my_event_handler(event):
    asyncio.create_task(process_event(event))

async def process_event(event):
    # 1. Пропускаем исходящие
    if event.out:
        return

    text = event.message.text
    if not text or len(text) < 20:
        return

    # 2. Быстрая проверка на стоп-слова
    for word in city_config.blacklist:
        if word.lower() in text.lower().replace("сегодня", ""):
            # print(f"Стоп-слово: {word}") # Раскомментируйте для отладки
            return

    # 3. ИГНОР ЛИСТ (Наш форум и спамеры)
    try:
        id_group = event.peer_id.channel_id
        # Нормализуем ID форума (убираем -100)
        clean_forum_id = int(str(config.forum).replace("-100", ""))
        
        ignored_ids = [
            clean_forum_id, 
            2451573337, 2432810487, 1384585087, 
            1695657275, 2010520161
        ]
        if id_group in ignored_ids:
            return
    except AttributeError:
        pass 

    # 4. Проверка на города
    text_lower = text.lower()
    found_districts = set()
    
    for district_name, keywords in city_config.districts.items():
        for keyword in keywords:
            if keyword.lower() in text_lower:
                found_districts.add(district_name)
                # Как только нашли город в этом округе, идем к следующему округу
                # (небольшая оптимизация, чтобы не перебирать все слова округа)
                break 

    if not found_districts:
        return 

    # --- ЕСЛИ ЗАКАЗ ПОДХОДИТ ---
    
    mess_id = event.id
    
    # Кеширование названия
    title = titles_cache.get(id_group, "Unknown")
    if title == "Unknown":
        try:
            chat = await event.get_chat()
            title = chat.title
            titles_cache[id_group] = title
        except:
            pass

    # Определяем название округа для уведомления
    district_map = {
        "central": "Центральный", "ЛДНР": "ЛДНР", "zap_her": "Запорожье и Херсон",
        "sev_zapad": "Северо-Западный", "yug": "Южный", "sev_kav": "Северо-Кавказский",
        "privolz": "Приволжский", "ural": "Уральский", "sibir": "Сибирский",
        "dalnevostok": "Дальневосточный"
    }
    
    found_key = list(found_districts)[0]
    district_name_ru = district_map.get(found_key, "Все заказы")

    # В очередь
    await msg_queue.put((text, id_group, mess_id, title, district_name_ru))


# --- ГЛАВНАЯ ФУНКЦИЯ ---
async def telebot():
    print("⏳ Запуск UserBot...")
    await client.start()
    
    asyncio.create_task(worker())
    
    print("🔄 Кеширование каналов...")
    async for dialog in client.iter_dialogs():
        if dialog.is_channel or dialog.is_group:
            titles_cache[dialog.id] = dialog.title

    print("✅ Бот готов!")

    try:
        users = await client.get_participants(config.forum)
        for user in users:
            database.write_user(str(user.id), user.username or "NoName")
            
        await bot.send_message(chat_id=config.admins[0], 
                               text=f"Бот перезагружен. В группе: {len(users)} чел.")
        
        asyncio.create_task(check_kicks(users))
    except Exception as e:
        print(f"Ошибка проверки участников: {e}")


async def check_kicks(users):
    for user in users:
        await asyncio.sleep(0.5) 
        user_id = str(user.id)
        if not database.date_product_end(user_id):
            try:
                await bot.ban_chat_member(chat_id=forum, user_id=user.id)
                await bot.unban_chat_member(chat_id=forum, user_id=user.id)
                print(f"Кикнут: {user.username}")
            except Exception:
                pass