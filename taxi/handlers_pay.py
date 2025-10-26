import asyncio
import hashlib
import json
import logging

import requests
from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.util import await_only
from yookassa import Configuration, Payment
import uuid

import config

Configuration.account_id = config.account_id
Configuration.secret_key = config.secret_key

import database
import kb

call_handler = Router()


class AdminFSM(StatesGroup):
    add_admin = State()
    waiting_for_phone = State()



#------------Подписка. Выбор и оплата--------------------------

# Выбрать подписку" | "select_product"
@call_handler.callback_query(F.data == "select_product")
async def select_product(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    try:
        # m = await bot.send_message(chat_id=user_id,
        #                        text="🔧 Бот работает в тестовом режиме! 🔧 \n"
        #                             "Мы дорабатываем и улучшаем его функционал, поэтому пока им можно пользоваться бесплатно.\n"
        #                             "Будем рады вашим отзывам и замечаниям! 😊",
        #                            reply_markup=kb.start_buttons())
        m = await bot.send_message(chat_id=user_id,
                                   text="Выберите подписку",
                                   reply_markup=kb.select_product())
        await bot.delete_message(chat_id=user_id,
                                 message_id=m.message_id - 1)
    except Exception as e:
        print(e)


#  Кнопка Назад | back_start_buttons
@call_handler.callback_query(F.data == "back_start_buttons")
async def select_product(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    try:
        m = await bot.send_message(chat_id=user_id,
                                   text="📜 Главное меню",
                                   reply_markup=kb.start_buttons())
        await bot.delete_message(user_id, m.message_id - 1)
    except Exception as e:
        print(e)

#  Кнопка Тестовый режим | test_product
@call_handler.callback_query(F.data == "test_product")
async def select_product(callback: CallbackQuery, bot: Bot):
    user_id = str(callback.from_user.id)
    print("test_product")
    try:
        end_date_test = database.get_test_product(user_id)
        if end_date_test: # Если значения нету. То есть еще не подключали тест
            m = await bot.send_message(chat_id=user_id,
                                       text=f"Вам предоставлен тестовый период до: {end_date_test}\n"
                                            f"Для работы нужно вступить в группу",
                                       reply_markup=kb.url_pay_chats())
            await bot.delete_message(user_id, m.message_id - 1)
        else:
            m = await bot.send_message(chat_id=user_id,
                                       text=f"Вы уже брали тестовый период\n"
                                            f"{database.date_product(user_id)}",
                                       reply_markup=kb.start_buttons())
            await bot.delete_message(user_id, m.message_id - 1)
    except Exception as e:
        print(e)


# VIP | vip_product
@call_handler.callback_query(F.data == "vip_product")
async def vip_product(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = str(callback.from_user.id)
    # Создаем кнопку для запроса номера телефона
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Отправить номер телефона", request_contact=True))
    await state.set_state(AdminFSM.waiting_for_phone)
    m = await bot.send_message(chat_id=user_id,
        text="Пожалуйста, отправьте ваш номер телефона.",
        reply_markup=builder.as_markup(resize_keyboard=True)
    )
    try:
        await bot.delete_message(chat_id=user_id, message_id=m.message_id - 1)
    except:
        pass
@call_handler.message(lambda message: message.contact, AdminFSM.waiting_for_phone)
async def process_phone(message: types.Message, bot: Bot,  state: FSMContext):
    user_id = str(message.from_user.id)
    phone_number = message.contact.phone_number
    user_name = message.from_user.username
    first_name = message.from_user.first_name
    await state.clear()
    await state.update_data(phone_number=phone_number)
    try:
        #------T-bank------
        pay = await send_pay_t_bank(user_id, phone_number) # True, payment_url, payment_id
        print(pay)
        if pay[0]:
            await state.update_data(id_pay=pay[2])  # Записываем в стейт идентификатор оплаты
            database.write_id_pay(user_id, pay[2])  # Записываем идентификатор оплаты

            m = await bot.send_message(chat_id=user_id,
                                       text="Стоимость подписки 499 рублей за 30 календарных дней с момента оплаты.\n"
                                            "Оплатите в течении 10 минут\n"
                                            "После оплаты нажмите кнопку «<b>Я оплатил</b>»\n",
                                       reply_markup=kb.vip_product_pay(pay[1]))
            await bot.delete_message(user_id, m.message_id - 1)
            await bot.delete_message(user_id, m.message_id - 2)
            # Ставим флаг оплаты на True
            await state.update_data(status_pay=True)


            # Запускаем отложенный процесс автоматической проверки оплаты
            await asyncio.gather(cheks_pay(user_id, bot, user_name, first_name, phone_number))
        else:
            m = await bot.send_message(chat_id=user_id,
                                       text=pay[1],
                                       reply_markup=kb.select_product())
            await bot.delete_message(user_id, m.message_id - 1)
    except Exception as e:
        print(e)

# async def star_chedule(user_id):
#     scheduler = AsyncIOScheduler()
#     scheduler.add_job(cheks_pay(user_id), 'interval', seconds=30)

#-----T-Bank----URL---pay_id---Проверка оплаты----
@call_handler.callback_query(F.data == "get_pay")
async def vip_product_pay(callback: CallbackQuery, bot: Bot, state: FSMContext):
    id_pay = (await state.get_data()).get("id_pay")
    user_id = str(callback.from_user.id)
    user_name = callback.from_user.username
    first_name = callback.from_user.first_name
    phone_number = (await state.get_data()).get("phone_number")
    # Запрашиваем данные платежа
    res_pay = await get_payment_status(id_pay)
    try:
        if res_pay.get("Success"):
            # Список идентификаторов оплаты
            text = ""
            ids_pay = database.get_id_pay(user_id).split(" ")
            for id_pay in ids_pay:
                text += f"\n<code>{id_pay}</code>"
            if "CONFIRMED" in res_pay.get("Status"):
                date_vip_product = database.vip_product(user_id) # Записываем + 31 день юзеру
                m = await bot.send_message(chat_id=user_id,
                                       text="🎉 Поздравляем! \n"
                                            "Вы успешно оплатили подписку VIP\n"
                                            f"Ваш подписка до: {date_vip_product}\n\n"
                                            "Вступите в группу и можете приступить к работе прямо сейчас\n\n"
                                            "Если не получается вступить, напишите в /support мы вас добавим",
                                       reply_markup=kb.url_pay_chats())
                # Удаляем идентификаторы платежей и отправляем отчет группу

                database.del_ids_pay(user_id) # Удаляем идентификаторы платежей
                data_text = (f"-----Успешная оплата----\n"
                             f"Подписка: VIP\n"
                             f"UserName: @{user_name}\n"
                             f"Имя: {first_name}\n"
                             f"id: {user_id}\n"
                             f"tel: {phone_number}\n"
                             f"Статус оплаты: {res_pay.get("Status")}\n"
                             f"Идентификатор(ы) оплаты: {text}")
                await bot.send_message(chat_id="-1002207784658",
                                       text=data_text)
                try:
                    await bot.delete_message(user_id, m.message_id -1)
                except Exception as e:
                    logging.exception(e)
            else:
               m =  await bot.send_message(chat_id=user_id,
                                       text="К сожалению мы не получили ваш платеж, пожалуйста проверьте. "
                                            "Если вы уверены что оплатили, напишите в чат поддержки"
                                       )
               data_text = (f"---Нажатие 'Я оплатил'---\n"
                            f"Подписка: VIP\n"
                            f"UserName: @{user_name}\n"
                            f"Имя: {first_name}\n"
                            f"id: <code>{user_id}</code>\n"
                            f"tel: {phone_number}\n"
                            f"Статус оплаты: {res_pay.get("Status")}\n"
                            f"Идентификатор(ы) оплаты: {text}")
               await bot.send_message(chat_id="-1002207784658",
                                      text=data_text)

               await bot.delete_message(user_id, m.message_id - 1)
    except Exception as e:
        logging.exception(e)


#-------Интернет Эквайринг Тинькофф-----------
async def send_pay_t_bank(user_id, phone):
    try:
        TINKOFF_INIT_URL = "https://securepay.tinkoff.ru/v2/Init"
        idempotence_key = str(uuid.uuid4()).replace("-", "")[20:]


        data = {"TerminalKey": config.terminal_key,
                "Amount": int(config.vip) * 100,
                "OrderId": f"{user_id}-n{idempotence_key}",
                "Password":config.terminal_password
        }
        #  Генерируем токен
        sorted_data = dict(sorted(data.items()))
        concatenated_string = ''.join(str(value) for value in sorted_data.values())
        hashed_string = hashlib.sha256(concatenated_string.encode()).hexdigest()
        # Создаем чек | Receipt
        Receipt = {
            "Phone": phone,  # Телефон клиента
            "Taxation": "patent",
            # Характеристики продукта(товара)
            "Items": [{  # Предметы(Товары), может быть несколько.
                "Name": "Подписка на пользование телеграм ботом @TransferGPT_bot",
                "Price": int(config.vip) * 100,
                "Quantity": 1,
                "Amount": int(config.vip) * 100,
                "Tax": "vat0"
            }]
        }
        # Добавляем чек с данными в data
        data["Receipt"] = Receipt

        data["Token"] = hashed_string
        del data["Password"]

        post_data_json = json.dumps(data, ensure_ascii=False)

        headers = {
            "Content-Type": "application/json"
        }

        # Отправляем POST-запрос в Tinkoff
        response = requests.post(TINKOFF_INIT_URL, data=post_data_json, headers=headers)
        print(response.json())
        if response.status_code != 200:
            return False, "Ошибка платежного шлюза, попробуйте еще раз через несколько минут."
        try:
            output_array = response.json()
        except json.JSONDecodeError as e:
            print(f"Ошибка при разборе JSON: {e}")
            return False
        # Проверяем успешность запроса
        if output_array.get("Success"):
            payment_url = output_array.get("PaymentURL") # Ссылка для платежа
            payment_id = output_array.get("PaymentId")  # Получаем ID платежа
            return True, payment_url, payment_id
        else:
            return [False, "Ошибка платежного шлюза, попробуйте еще раз через несколько минут."]
    except Exception as e:
        print(e)

#---Проверка оплаты----
async def get_payment_status(order_id):
    TINKOFF_GET_STATE_URL = "https://securepay.tinkoff.ru/v2/GetState"
    data = {
        "TerminalKey": config.terminal_key,
        "Password": config.terminal_password,
        "PaymentId": order_id,
    }
    # Генерируем Token
    sorted_data = dict(sorted(data.items()))  # Сортируем ключи
    concatenated_string = ''.join(str(value) for value in sorted_data.values())  # Склеиваем значения
    data["Token"] = hashlib.sha256(concatenated_string.encode()).hexdigest()  # SHA256-хеш
    del data["Password"]  # Удаляем пароль из запроса
    try:
        # Отправляем запрос
        response = requests.post(TINKOFF_GET_STATE_URL, json=data)
        output = response.json()
        return output
    except Exception as e:
        print(e)

#--------------Премиум подписка | Прием оплаты
# Premium | premium_product
@call_handler.callback_query(F.data == "premium_product")
async def select_product(callback: CallbackQuery, bot: Bot):
    await callback.answer("🛠 В разработке, скоро всё будет")
    user_id = str(callback.from_user.id)



#  Проверка оплаты по идентификаторам
async def cheks_pay(user_id, bot, user_name, first_name, phone_number):
    await asyncio.sleep(600)
    ids_pay = database.get_id_pay(user_id).split(" ")
    if ids_pay:
        for order_id in ids_pay:
            TINKOFF_GET_STATE_URL = "https://securepay.tinkoff.ru/v2/GetState"
            data = {
                "TerminalKey": config.terminal_key,
                "Password": config.terminal_password,
                "PaymentId": order_id,
            }
            # Генерируем Token
            sorted_data = dict(sorted(data.items()))  # Сортируем ключи
            concatenated_string = ''.join(str(value) for value in sorted_data.values())  # Склеиваем значения
            data["Token"] = hashlib.sha256(concatenated_string.encode()).hexdigest()  # SHA256-хеш
            del data["Password"]  # Удаляем пароль из запроса
            try:
                # Отправляем запрос
                response = requests.post(TINKOFF_GET_STATE_URL, json=data)
                output = response.json()
                if output.get("Success"):
                    if "CONFIRMED" in output.get("Status"):

                        # Список идентификаторов оплаты
                        text = ""
                        ids_pay = database.get_id_pay(user_id).split(" ")
                        for id_pay in ids_pay:
                            text += f"\n<code>{id_pay}</code>"

                        # Отправляем данные оплаты админу
                        data_text = (f"-----Успешная оплата----\n"
                                     f"Подписка: VIP\n"
                                     f"UserName: @{user_name}\n"
                                     f"Имя: {first_name}\n"
                                     f"id: {user_id}\n"
                                     f"tel: {phone_number}\n"
                                     f"Идентификатор(ы) оплаты: {text}")
                        await bot.send_message(chat_id="-1002207784658",
                                               text=data_text)
                        # Удаляем идентификаторы оплаты
                        database.del_ids_pay(user_id)

                        date_vip_product = database.vip_product(user_id)  # Записываем + 31 день юзеру
                        m = await bot.send_message(chat_id=user_id,
                                                   text="🎉 Поздравляем! \n"
                                                        "Вы успешно оплатили подписку VIP\n"
                                                        f"Ваш подписка до: {date_vip_product}\n\n"
                                                        "Вступите в группу и можете приступить к работе прямо сейчас\n\n"
                                                        "Если не получается вступить, напишите в /support мы вас добавим",
                                                   reply_markup=kb.url_pay_chats())
                        return output
                    else:
                        print(output)
            except Exception as e:
                print(e)


