from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

import config
import database
import kb

my_product_handler = Router()
class AdminFSM(StatesGroup):
    add_notif_city = State()


#----------Мои подписки-------------------
#  Мои подписки | my_product
@my_product_handler.callback_query(F.data == "my_product")
async def my_product(callback: CallbackQuery, bot: Bot):
    user_id = str(callback.from_user.id)
    if user_id in config.admins:
        try:
            m = await bot.send_message(chat_id=user_id,
                                       text=
                                            f"Выберите округ или включите оповещения о новых заказах\n"
                                            f"➡️ <a href='https://t.me/+dP6FgtKdMi9mNWZi'><b>Вступите в группу</b></a>",
                                       reply_markup=kb.states()
                                       )
            await bot.delete_message(chat_id=user_id,
                                     message_id=m.message_id - 1)
        except Exception as e:
            print(e)
        return
    date = database.date_product_end(user_id)
    if date:
        try:
            m = await bot.send_message(chat_id=user_id,
                                       text=f"{database.date_product(user_id)}\n\n"
                                            f"Выберите округ или включите оповещения о новых заказах\n"
                                            f"➡️ <a href='https://t.me/+dP6FgtKdMi9mNWZi'><b>Вступите в группу</b></a>",
                                       reply_markup=kb.states()
                                       )
            await bot.delete_message(chat_id=user_id,
                                     message_id=m.message_id - 1)
        except Exception as e:
            print(e)
    else:
        try:
            m = await bot.send_message(chat_id=user_id,
                                       text=f"У вас нет активных подписок для работы в этом разделе. Выберите подходящую вам.",
                                       reply_markup=kb.select_product()
                                       )
            await bot.delete_message(chat_id=user_id,
                                     message_id=m.message_id - 1)
        except Exception as e:
            print(e)

# Получать оповещения" | "notif_city"
@my_product_handler.callback_query(F.data == "notif")
async def notif_city(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    try:
        m = await bot.send_message(chat_id=user_id,
                                   text=f"Выбираете нужный округ, и бот присылает вам все появляющиеся заказы по этому округу в реальном времени.\n\n"
                                        f"Одновремено оповещения можно включить только для одного округа, или для всех\n\n"
                                        f"Чтобы отключить оповещения: Отправьте /stop\n"
                                        f"Эту команду можно также найти в левом нижнем меню\n\n"
                                        f"Выберите округ",
                                   reply_markup=kb.notif_states())
        await state.set_state(AdminFSM.add_notif_city)
        await bot.delete_message(chat_id=user_id,
                                 message_id=m.message_id - 1)
    except Exception as e:
        print(e)

# Вывод кнопок ссылок городов | url_buttons
@my_product_handler.callback_query(F.data == "url_buttons")
async def url_buttons(callback: CallbackQuery, bot: Bot):
   user_id = callback.from_user.id
   try:
       m = await bot.send_message(chat_id=user_id, text="Выбор округа",
                                  reply_markup=kb.states())
       await bot.delete_message(chat_id=user_id,
                                message_id=m.message_id - 1)
   except Exception as e:
       print(e)


# База групп | Будет отправлять список групп
@my_product_handler.callback_query(F.data == "baza_chats")
async def url_buttons(callback: CallbackQuery, bot: Bot):
    user_id = str(callback.from_user.id)
    date = database.date_product_end(user_id)
    if date:
        type_product = database.get_type_product(user_id)
        if "VIP" in type_product:
            await callback.message.answer(text="""
<b>Руководство по вступлению в группы</b>  

Оформление профиля водителя: 
• Главное фото: транспортное средство с видимым государственным номером в фронтальной проекции 
• Личные данные: имя 
• Контакты: действующий телефонный номер 
• Информация профиля: характеристики автомобиля, государственный номер, год выпуска, местоположение 
• Идентификация: корректно настроенный публичный @username

Выполнение указанных требований существенно ускоряет процедуру рассмотрения заявки на членство. Водителям, соблюдающим установленные нормы, гарантируется рассмотрение заявки. При обнаружении нарушений правил оформления профиля администрация оставляет за собой право: 
• Отклонить заявку на вступление 
• Запросить дополнительные подтверждающие документы

Каталог актуальных ссылок регулярно обновляется

При отсутствии желаемого сообщества в списке рекомендуется направить запрос в службу поддержки для получения актуальной информации.

            """)

            with open("list_group.txt", "r") as f:
                list_group = f.read()
                await bot.send_message(chat_id=user_id,
                                       text=list_group, disable_web_page_preview=True,
                                       protect_content=True)
            #                 try:
            #     p = Path(LIST_FILE)
            #     if not p.exists():
            #         text = "Список ещё не сформирован. Попробуйте позже."
            #     else:
            #         text = p.read_text(encoding="utf-8").strip() or "Каналы не найдены."
            # except Exception as e:
            #     text = f"Не удалось прочитать список: {e}"

            # for part in _split_text(text):
            #     await bot.send_message(
            #         chat_id=int(user_id),
            #         text=part,
            #         disable_web_page_preview=True,
            #         protect_content=True
            #     )
                

        else:
            await callback.answer(text="Доступно в VIP подписке")
    else:
        await callback.answer(text="Доступно в VIP подписке")



#  Руководство пользователя | guide
@my_product_handler.callback_query(F.data == "guide")
async def url_buttons(callback: CallbackQuery, bot: Bot):
   user_id = callback.from_user.id
   with open("update_fag.txt", "r") as f:
       fag = f.read()
   try:
       m = await bot.send_message(chat_id=user_id,
                              text=fag)

       await callback.answer()
       await bot.delete_message(chat_id=user_id,
                                message_id=m.message_id - 1)
   except Exception as e:
       print(e)


# Нажатие на выбор города для получения оповещений
@my_product_handler.callback_query(AdminFSM.add_notif_city)
async def add_notif(callback: CallbackQuery, bot: Bot, state: FSMContext):

    try:

        data_city = callback.data
        user_id = str(callback.from_user.id)
        database.add_notif(user_id, data_city)
        
        m = await bot.send_message(chat_id=user_id, text=f"Вы включили оповещения о новых заказах. "
                                                         f"Как только появится заказ, я его сразу вам отправлю.\n"
                                                         f"Отключить оповещения: <b>/stop</b>",
                                   reply_markup=kb.start_buttons())
        await bot.delete_message(chat_id=user_id,
                                 message_id=m.message_id - 1)
        await state.clear()
    except Exception as e:
        print(e)

