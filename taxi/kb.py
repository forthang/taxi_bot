from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from config import forum


def start_buttons():
    select_product = InlineKeyboardButton(text="🧰 Выбрать подписку", callback_data="select_product")
    my_product = InlineKeyboardButton(text="🚖 Приступить к работе 🚘", callback_data="my_product")
    baza_chats = InlineKeyboardButton(text="📙 База групп", callback_data="baza_chats")
    support = InlineKeyboardButton(text="🛠 Поддержка и предложения", url="https://t.me/+JJtf6d9WsGFkMjEy")
    info = InlineKeyboardButton(text="📓 Руководство пользователя", callback_data="guide")
    buttons = [[my_product], [select_product], [baza_chats], [info], [support]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def select_product():
    test_product = InlineKeyboardButton(text="🆓 Потестить", callback_data="test_product")
    vip_product = InlineKeyboardButton(text="👑 VIP", callback_data="vip_product")
    premium_product = InlineKeyboardButton(text="💎 PREMIUM", callback_data="premium_product")
    back = InlineKeyboardButton(text="🔙 Назад", callback_data="back_start_buttons")
    buttons = [[test_product],  [vip_product], [premium_product],[back]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)



def states(): # Округи
    all_city = InlineKeyboardButton(text="Все заказы", url="https://t.me/c/2399917728/177")
    ldnr = InlineKeyboardButton(text="ЛДНР", url="https://t.me/c/2399917728/74")
    zap_her = InlineKeyboardButton(text="Запорожье и Херсон", url="https://t.me/c/2399917728/75")
    central = InlineKeyboardButton(text="Центральный", url="https://t.me/c/2399917728/26")
    sev_zap = InlineKeyboardButton(text="Северо-Западный", url="https://t.me/c/2399917728/28")
    yug = InlineKeyboardButton(text="Южный", url="https://t.me/c/2399917728/79")
    sev_kav = InlineKeyboardButton(text="Северо-Кавказский", url="https://t.me/c/2399917728/35")
    privolz = InlineKeyboardButton(text="Приволжский", url="https://t.me/c/2399917728/80")
    ural = InlineKeyboardButton(text="Уральский", url="https://t.me/c/2399917728/82")
    sibir = InlineKeyboardButton(text="Сибирский", url="https://t.me/c/2399917728/32")
    dalnevostok = InlineKeyboardButton(text="Дальневосточный", url="https://t.me/c/2399917728/78")
    notif = InlineKeyboardButton(text="🔔 Включить оповещения", callback_data="notif")
    # url = InlineKeyboardButton(text="Вступить в группу", url="https://t.me/+dgBmzYAu_P0zZmYy")
    back = InlineKeyboardButton(text="🔙 Назад", callback_data="back_start_buttons")

    buttons = [[all_city], [ldnr], [zap_her], [central], [sev_zap], [yug], [sev_kav], [privolz],
               [ural], [sibir], [dalnevostok], [notif], [back]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Ссылка для вступления в группу
def url_pay_chats():
    url = InlineKeyboardButton(text="Вступить в группу", url=config.url)
    return InlineKeyboardMarkup(inline_keyboard=[[url]])


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


# Выбор уведомлений
def notif_states():
    all_orders = InlineKeyboardButton(text="Все заказы", callback_data="Все заказы")
    ldnr = InlineKeyboardButton(text="ЛДНР", callback_data="ЛДНР")
    zap_her = InlineKeyboardButton(text="Запорожье и Херсон", callback_data="Запорожье и Херсон")
    central = InlineKeyboardButton(text="Центральный", callback_data="Центральный")
    sev_zap = InlineKeyboardButton(text="Северо-Западный", callback_data="Северо-Западный")
    yug = InlineKeyboardButton(text="Южный", callback_data="Южный")
    sev_kav = InlineKeyboardButton(text="Северо-Кавказский", callback_data="Северо-Кавказский")
    privolz = InlineKeyboardButton(text="Приволжский", callback_data="Приволжский")
    ural = InlineKeyboardButton(text="Уральский", callback_data="Уральский")
    sibir = InlineKeyboardButton(text="Сибирский", callback_data="Сибирский")
    dal_vostok = InlineKeyboardButton(text="Дальневосточный", callback_data="Дальневосточный")
    back = InlineKeyboardButton(text="🔙 Назад", callback_data="back_start_buttons")
    buttons = [[all_orders], [ldnr], [zap_her], [central], [sev_zap], [yug], [sev_kav], [privolz],
               [ural], [sibir], [dal_vostok], [back]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Функция vip_product | Кнопка оплатить
def vip_product_pay(confirmation_url):
    pay = InlineKeyboardButton(text="Оплатить", url=confirmation_url)
    get_pay = InlineKeyboardButton(text="Я оплатил", callback_data="get_pay")
    back = InlineKeyboardButton(text="🔙 Назад", callback_data="back_start_buttons")
    return InlineKeyboardMarkup(inline_keyboard=[[pay], [get_pay], [back]])


#------------Admin_buttons-----------------
def admin_buttons():
    pay_user_test = InlineKeyboardButton(text="🆓 Продлить Тест всем", callback_data="test_period")
    pay_user_vip = InlineKeyboardButton(text="👑 Продлить VIP одному", callback_data="extend_one")
    pay_users_vip = InlineKeyboardButton(text="👑 Продлить VIP всем", callback_data="extend_all")
    pay_user_premium = InlineKeyboardButton(text="💎 Продлить PREMIUM одному", callback_data="extend_premium_one")
    pay_users_premium = InlineKeyboardButton(text="💎 Продлить PREMIUM всем", callback_data="extend_premium_all")
    mailing = InlineKeyboardButton(text="📤 Рассылка", callback_data="mailing")
    mailing_vip = InlineKeyboardButton(text="📤 Рассылка для VIP", callback_data="mailing_vip")
    update_fag = InlineKeyboardButton(text="📓 Обновить руководство", callback_data="update_fag")
    list_group = InlineKeyboardButton(text="♻️ Обновить список групп", callback_data="list_group")
    filters = InlineKeyboardButton(text="♻️ Обновить данные фильтров", callback_data="filters")
    stata_all = InlineKeyboardButton(text="📊 Статистика", callback_data="stata")
    backup = InlineKeyboardButton(text="💾 Бэкап БД", callback_data="backup")
    logs = InlineKeyboardButton(text="📄 Логи", callback_data="logs")
    buttons = [[pay_user_test], [pay_user_vip], [pay_users_vip], [pay_user_premium], [pay_users_premium],
              [mailing], [mailing_vip],[update_fag], [list_group], [filters], [stata_all], [backup], [logs]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
