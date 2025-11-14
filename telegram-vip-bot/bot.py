import os
import asyncio
import sqlite3
import hashlib
import json
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import aiohttp
from ai_processor import DeepSeekProcessor

# Загружаем переменные окружения
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
TINKOFF_TERMINAL_KEY = os.getenv('TINKOFF_TERMINAL_KEY')
TINKOFF_SECRET_KEY = os.getenv('TINKOFF_SECRET_KEY')
FREE_GROUP_ID = int(os.getenv('FREE_GROUP_ID'))
VIP_GROUP_ID = int(os.getenv('VIP_GROUP_ID'))
SERVER_URL = os.getenv('SERVER_URL')
MESSAGE_DELAY = int(os.getenv('MESSAGE_DELAY', 30))
VIP_PRICE = int(os.getenv('VIP_PRICE', 299))
VIP_CHANNEL_LINK = os.getenv('VIP_CHANNEL_LINK', 'https://t.me/+JJiPdE2FK0M3ZDAy')

# Инициализация базы данных
def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    
    # Таблица пользователей
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            is_vip INTEGER DEFAULT 0,
            vip_until TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица платежей
    c.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            payment_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount INTEGER,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # Таблица заказов такси
    c.execute('''
        CREATE TABLE IF NOT EXISTS taxi_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route TEXT,
            date TEXT,
            time TEXT,
            price INTEGER,
            passengers INTEGER,
            luggage TEXT,
            vehicle_type TEXT,
            additional_services TEXT,
            status TEXT DEFAULT 'active',
            contact TEXT,
            is_valid BOOLEAN DEFAULT 1,
            source_message TEXT,
            sender_id INTEGER,
            sender_username TEXT,
            sender_first_name TEXT,
            sender_last_name TEXT,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# Класс для работы с Тинькофф Кассой
class TinkoffPayment:
    def __init__(self):
        self.terminal_key = TINKOFF_TERMINAL_KEY
        self.secret_key = TINKOFF_SECRET_KEY
        self.api_url = "https://securepay.tinkoff.ru/v2/"
    
    def generate_token(self, params):
        """Генерация токена для подписи запроса"""
        # Создаем копию параметров для генерации токена
        token_params = params.copy()
        token_params['Password'] = self.secret_key
        
        # Сортируем ключи
        sorted_params = sorted(token_params.items())
        
        # Конкатенируем только скалярные значения (без DATA, Receipt)
        values = ''.join([str(v) for k, v in sorted_params if k not in ['Token', 'DATA', 'Receipt']])
        
        return hashlib.sha256(values.encode()).hexdigest()
    
    async def init_payment(self, amount, order_id, user_id, description):
        """Инициализация платежа"""
        # Конструируем объект params
        params = {
            'TerminalKey': self.terminal_key,
            'Amount': amount * 100,  # В копейках
            'OrderId': str(order_id),  # Строка
            'Description': 'оплата',
            'SuccessURL': f'http://t.me/VipTaxiPrivat_bot?start=success_{user_id}',
            'FailURL': f'http://t.me/VipTaxiPrivat_bot?start=fail',
            'DATA': {
                'user_id': str(user_id)
            },
            'Receipt': {
                'Email': 'test@example.com',
                'Phone': '+79990000000',
                'Taxation': 'usn_income',
                'Items': [
                    {
                        'Name': 'товар',
                        'Price': amount * 100,  # Цена в копейках
                        'Quantity': 1.00,  # Количество
                        'Amount': amount * 100,  # Сумма в копейках
                        'Tax': 'none'  # Налог (none для УСН)
                    }
                ]
            }
        }
        
        # Генерируем токен
        params['Token'] = self.generate_token(params)
        
        print(f"Отправляем запрос в Тинькофф: {params}")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f'{self.api_url}Init', json=params) as response:
                result = await response.json()
                print(f"Ответ от Тинькофф: {result}")
                
                if result.get('Success'):
                    return result
                else:
                    print(f"Ошибка API Тинькофф: {result}")
                    return result

    async def cancel_payment(self, payment_id, amount=None):
        """Отмена платежа"""
        # Формируем параметры
        params = {
            'TerminalKey': self.terminal_key,
            'PaymentId': payment_id
        }
        
        # Добавляем сумму только если передана
        if amount is not None:
            params['Amount'] = amount
        
        # Генерируем токен
        params['Token'] = self.generate_token(params)
        
        print(f"Отправляем запрос отмены в Тинькофф: {params}")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f'{self.api_url}Cancel', json=params) as response:
                result = await response.json()
                print(f"Ответ отмены от Тинькофф: {result}")
                
                if result.get('Success'):
                    return True
                else:
                    print(f"Ошибка отмены платежа: {result}")
                    return False
    
    async def check_payment_status(self, payment_id):
        """Проверка статуса платежа"""
        params = {
            'TerminalKey': self.terminal_key,
            'PaymentId': payment_id
        }
        params['Token'] = self.generate_token(params)
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f'{self.api_url}GetState', json=params) as response:
                return await response.json()

# Функции для работы с базой данных
def add_user(user_id, username):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
            (user_id, username))
    conn.commit()
    conn.close()

def set_user_vip(user_id, days=30):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("""UPDATE users 
                SET is_vip = 1, 
                    vip_until = datetime('now', '+{} days')
                WHERE user_id = ?""".format(days), (user_id,))
    conn.commit()
    conn.close()

def is_user_vip(user_id):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("""SELECT is_vip, vip_until FROM users WHERE user_id = ?""", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result and result[0] == 1:
        vip_until = datetime.fromisoformat(result[1])
        if vip_until > datetime.now():
            return True
    return False

def add_payment(payment_id, user_id, amount, status='PENDING'):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO payments (payment_id, user_id, amount, status) VALUES (?, ?, ?, ?)",
            (payment_id, user_id, amount, status))
    conn.commit()
    conn.close()

def add_taxi_order(order_data, sender_info=None):
    """Добавление заказа такси в базу данных"""
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO taxi_orders (
            route, date, time, price, passengers, luggage, 
            vehicle_type, additional_services, status, contact, 
            is_valid, source_message, sender_id, sender_username, 
            sender_first_name, sender_last_name, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        order_data.get('route'),
        order_data.get('date'),
        order_data.get('time'),
        order_data.get('price'),
        order_data.get('passengers'),
        order_data.get('luggage'),
        order_data.get('vehicle_type'),
        order_data.get('additional_services'),
        order_data.get('status', 'active'),
        order_data.get('contact'),
        order_data.get('is_valid', True),
        order_data.get('source_message'),
        sender_info.get('id') if sender_info else None,
        sender_info.get('username') if sender_info else None,
        sender_info.get('first_name') if sender_info else None,
        sender_info.get('last_name') if sender_info else None,
        order_data.get('processed_at')
    ))
    conn.commit()
    conn.close()

def get_taxi_orders(limit=50):
    """Получение заказов такси"""
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('''
        SELECT * FROM taxi_orders 
        WHERE is_valid = 1 
        ORDER BY created_at DESC 
        LIMIT ?
    ''', (limit,))
    orders = c.fetchall()
    conn.close()
    return orders

def update_payment_status(payment_id, status):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("UPDATE payments SET status = ? WHERE payment_id = ?", (status, payment_id))
    conn.commit()
    conn.close()

def remove_expired_vip_users():
    """Удаление пользователей с истекшим VIP статусом"""
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    
    # Находим пользователей с истекшим VIP статусом
    c.execute('''
        SELECT user_id, username 
        FROM users 
        WHERE is_vip = 1 AND vip_until < datetime('now')
    ''')
    
    expired_users = c.fetchall()
    
    for user_id, username in expired_users:
        # Убираем VIP статус
        c.execute('''
            UPDATE users 
            SET is_vip = 0, vip_until = NULL 
            WHERE user_id = ?
        ''', (user_id,))
        
        print(f"VIP статус истек для пользователя {username} (ID: {user_id})")
    
    conn.commit()
    conn.close()
    
    return len(expired_users)

def get_user_vip_info(user_id):
    """(is_vip:int, vip_until:datetime|None)"""
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT is_vip, vip_until FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return 0, None
    is_vip, vip_until = row
    vip_dt = datetime.fromisoformat(vip_until) if vip_until else None
    return is_vip, vip_dt


def get_vip_time_left(user_id):
    """timedelta до конца VIP или None"""
    is_vip, vip_until = get_user_vip_info(user_id)
    if is_vip and vip_until:
        return vip_until - datetime.now()
    return None


def format_time_left(delta: timedelta) -> str:
    """Читаемое «сколько осталось»"""
    total = int(delta.total_seconds())
    if total <= 0:
        return "истекла"
    days = total // 86400
    hours = (total % 86400) // 3600
    minutes = (total % 3600) // 60
    if days > 0:
        return f"{days} д. {hours} ч."
    if hours > 0:
        return f"{hours} ч. {minutes} мин."
    return f"{minutes} мин."


def extend_user_vip(user_id, days=30):
    """
    Продлевает VIP на N дней от большего из (vip_until; now).
    Если записи нет — создаёт.
    """
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    # гарантируем, что запись есть
    c.execute("INSERT OR IGNORE INTO users (user_id, is_vip, vip_until) VALUES (?, 0, NULL)", (user_id,))
    # продление (добавляем к текущему vip_until, если он в будущем)
    c.execute(f"""
        UPDATE users
        SET is_vip = 1,
            vip_until = datetime(
                CASE
                    WHEN vip_until IS NOT NULL AND vip_until > datetime('now') THEN vip_until
                    ELSE datetime('now')
                END,
                '+{days} days'
            )
        WHERE user_id = ?
    """, (user_id,))
    conn.commit()
    conn.close()

# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username)
    
    # Проверяем параметры команды start
    if context.args and len(context.args) > 0:
        start_param = context.args[0]
        
        if start_param.startswith('success_'):
            # Пользователь вернулся после успешной оплаты
            user_id = start_param.split('_')[1]
            if int(user_id) == user.id:
                await update.message.reply_text(
                    "🎉 Добро пожаловать обратно!\n\n"
                    "✅ Ваша оплата прошла успешно!\n"
                    "💎 Вам предоставлен VIP доступ на 30 дней.\n"
                    "⚡ Теперь вы будете получать все сообщения мгновенно!\n\n"
                    f"💎 Присоединяйтесь к VIP каналу:\n{VIP_CHANNEL_LINK}"
                )
                return
        elif start_param == 'fail':
            # Пользователь вернулся после неуспешной оплаты
            await update.message.reply_text(
                "❌ Оплата не прошла.\n\n"
                "Попробуйте еще раз или обратитесь в поддержку.\n"
                "Используйте команду /start для повторной попытки."
            )
            return
        elif start_param == 'buy_vip':
            # Пользователь пришел из группы для покупки VIP
            if is_user_vip(user.id):
                is_vip, vip_until = get_user_vip_info(user.id)
                left = get_vip_time_left(user.id)
                left_str = format_time_left(left) if left else "—"

                keyboard = [
                    [InlineKeyboardButton("💎 VIP канал", url=VIP_CHANNEL_LINK)],
                    [InlineKeyboardButton("♻️ Продлить на 30 дней", callback_data='buy_vip')],
                    [InlineKeyboardButton("📊 Статус", callback_data='status')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.message.reply_text(
                    f"Привет, {user.first_name}! 👋\n\n"
                    "🎉 У вас активен VIP!\n\n"
                    f"📅 Действует до: {vip_until.strftime('%d.%m.%Y %H:%M')}\n"
                    f"⏳ Осталось: {left_str}\n\n"
                    "⚡ Сообщения приходят мгновенно.",
                    reply_markup=reply_markup
                )
                return
            else:
                # Показываем меню покупки VIP
                keyboard = [
                    [InlineKeyboardButton("💳 Купить VIP доступ", callback_data='buy_vip')],
                    [InlineKeyboardButton("ℹ️ О боте", callback_data='about')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"Привет, {user.first_name}! 👋\n\n"
                    "💎 VIP доступ к эксклюзивному контенту\n\n"
                    "🆓 В бесплатной группе сообщения появляются с задержкой\n"
                    "⚡ В VIP группе - мгновенно!\n\n"
                    f"💰 Стоимость: {VIP_PRICE}₽ на 30 дней\n\n"
                    "Выберите действие:",
                    reply_markup=reply_markup
                )
                return
    
    # Проверяем VIP статус
    if is_user_vip(user.id):
                is_vip, vip_until = get_user_vip_info(user.id)
                left = get_vip_time_left(user.id)
                left_str = format_time_left(left) if left else "—"

                keyboard = [
                    [InlineKeyboardButton("💎 VIP канал", url=VIP_CHANNEL_LINK)],
                    [InlineKeyboardButton("♻️ Продлить на 30 дней", callback_data='buy_vip')],
                    [InlineKeyboardButton("📊 Статус", callback_data='status')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.message.reply_text(
                    f"Привет, {user.first_name}! 👋\n\n"
                    "🎉 У вас активен VIP!\n\n"
                    f"📅 Действует до: {vip_until.strftime('%d.%m.%Y %H:%M')}\n"
                    f"⏳ Осталось: {left_str}\n\n"
                    "⚡ Сообщения приходят мгновенно.",
                    reply_markup=reply_markup
                )
                
    else:
        keyboard = [
            [InlineKeyboardButton("💎 Купить VIP доступ", callback_data='buy_vip')],
            [InlineKeyboardButton("ℹ️ О боте", callback_data='about')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Привет, {user.first_name}! 👋\n\n"
            "Я бот для доступа к эксклюзивному контенту.\n\n"
            "🆓 В бесплатной группе сообщения появляются с задержкой 5 секунд\n"
            "💎 В VIP группе - мгновенно!\n\n"
            "Выберите действие:",
            reply_markup=reply_markup
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'buy_vip':
        payment = TinkoffPayment()
        order_id = f"ORDER_{query.from_user.id}_{int(time.time())}"
        
        # Инициализируем платеж
        result = await payment.init_payment(
            amount=VIP_PRICE,
            order_id=order_id,
            user_id=query.from_user.id,
            description="VIP доступ к Telegram каналу на 30 дней"
        )
        
        if result.get('Success'):
            payment_id = result.get('PaymentId')
            payment_url = result.get('PaymentURL')
            
            # Сохраняем платеж в БД
            add_payment(payment_id, query.from_user.id, VIP_PRICE)
            
            # Сохраняем payment_id в context.user_data для последующей проверки
            context.user_data['pending_payment_id'] = payment_id
            
            keyboard = [
                [InlineKeyboardButton("💳 Оплатить", url=payment_url)],
                [InlineKeyboardButton("✅ Я оплатил", callback_data=f'check_payment_{payment_id}')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"💎 VIP доступ на 30 дней\n"
                f"💰 Стоимость: {VIP_PRICE}₽\n\n"
                f"1️⃣ Нажмите 'Оплатить' и произведите оплату\n"
                f"2️⃣ После оплаты вернитесь сюда и нажмите 'Я оплатил'\n\n"
                f"⚠️ Проверка оплаты может занять несколько минут",
                reply_markup=reply_markup
            )
        else:
            await query.edit_message_text("❌ Ошибка создания платежа. Попробуйте позже.")
    
    elif query.data.startswith('check_payment_'):
        # Обработка кнопки "Я оплатил"
        payment_id = query.data.replace('check_payment_', '')
        
        # Показываем сообщение о проверке
        await query.edit_message_text(
            "🔄 Проверяем вашу оплату...\n\n"
            "Пожалуйста, подождите несколько секунд.",
            reply_markup=None
        )
        
        # Проверяем статус платежа
        payment = TinkoffPayment()
        result = await payment.check_payment_status(payment_id)
        
        if result.get('Success'):
            status = result.get('Status')
            
            if status == 'CONFIRMED':
                update_payment_status(payment_id, 'CONFIRMED')
                extend_user_vip(query.from_user.id, 30)

                _, vip_until = get_user_vip_info(query.from_user.id)
                left_str = format_time_left(vip_until - datetime.now()) if vip_until else "30 д."

                keyboard = [
                    [InlineKeyboardButton("💎 VIP канал", url=VIP_CHANNEL_LINK)],
                    [InlineKeyboardButton("♻️ Продлить ещё на 30 дней", callback_data='buy_vip')],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    "🎉 Поздравляем!\n\n"
                    "✅ Оплата подтверждена!\n"
                    f"📅 Новый срок до: {vip_until.strftime('%d-%м-%Y')}\n"
                    f"⏳ Осталось: {left_str}\n\n"
                    "Спасибо за продление ✨",
                    reply_markup=reply_markup
                )
                
            elif status in ['NEW', 'FORM_SHOWED', 'DEADLINE_EXPIRED', 'CANCELED']:
                # Платеж еще не оплачен или отменен
                keyboard = [
                    [InlineKeyboardButton("💳 Перейти к оплате", url=result.get('PaymentURL', ''))] if result.get('PaymentURL') else [],
                    [InlineKeyboardButton("✅ Я оплатил", callback_data=f'check_payment_{payment_id}')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='buy_vip')]
                ]
                reply_markup = InlineKeyboardMarkup([btn for btn in keyboard if btn])  # Убираем пустые списки
                
                status_messages = {
                    'NEW': 'еще не начата',
                    'FORM_SHOWED': 'в процессе',
                    'DEADLINE_EXPIRED': 'истекла',
                    'CANCELED': 'отменена'
                }
                
                await query.edit_message_text(
                    f"❌ Оплата {status_messages.get(status, 'не завершена')}\n\n"
                    f"Пожалуйста, завершите оплату и нажмите 'Я оплатил' снова.\n\n"
                    f"Если возникли проблемы, попробуйте создать новый платеж.",
                    reply_markup=reply_markup
                )
                
            elif status in ['REJECTED', 'REFUNDED']:
                # Платеж отклонен или возвращен
                update_payment_status(payment_id, status)
                
                keyboard = [
                    [InlineKeyboardButton("🔄 Попробовать снова", callback_data='buy_vip')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='buy_vip')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"❌ Платеж отклонен\n\n"
                    f"Попробуйте создать новый платеж или свяжитесь с поддержкой.",
                    reply_markup=reply_markup
                )
                
            else:
                # Неизвестный статус
                keyboard = [
                    [InlineKeyboardButton("✅ Проверить снова", callback_data=f'check_payment_{payment_id}')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='buy_vip')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"⚠️ Статус платежа: {status}\n\n"
                    f"Проверка не завершена. Попробуйте еще раз через минуту.",
                    reply_markup=reply_markup
                )
        else:
            # Ошибка при проверке платежа
            keyboard = [
                [InlineKeyboardButton("✅ Проверить снова", callback_data=f'check_payment_{payment_id}')],
                [InlineKeyboardButton("🔙 Назад", callback_data='buy_vip')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "❌ Ошибка при проверке платежа\n\n"
                "Попробуйте проверить снова через минуту или создайте новый платеж.",
                reply_markup=reply_markup
            )
    
    elif query.data == 'about':
        await query.edit_message_text(
            "ℹ️ О боте\n\n"
            "Этот бот предоставляет доступ к эксклюзивному контенту.\n\n"
            "В VIP группе вы получаете:\n"
            "✅ Мгновенный доступ к новым сообщениям\n"
            "✅ Эксклюзивный контент\n"
            "✅ Приоритетную поддержку\n\n"
            "Стоимость: 299₽/месяц"
        )
    
    elif query.data == 'status':
        is_vip, vip_until = get_user_vip_info(query.from_user.id)
        if is_vip and vip_until:
            left = vip_until - datetime.now()
            text = (
                "💎 Ваш статус VIP\n\n"
                f"📅 Действует до: {vip_until.strftime('%d.%m.%Y %H:%M')}\n"
                f"⏳ Осталось: {format_time_left(left)}"
            )
            keyboard = [
                [InlineKeyboardButton("♻️ Продлить на 30 дней", callback_data='buy_vip')],
                [InlineKeyboardButton("💎 VIP канал", url=VIP_CHANNEL_LINK)]
            ]
        else:
            text = "У вас нет активной VIP-подписки."
            keyboard = [[InlineKeyboardButton("💳 Купить VIP доступ", callback_data='buy_vip')]]



async def check_expired_vip_job(context: ContextTypes.DEFAULT_TYPE):
    """Задача для проверки истекших VIP статусов"""
    try:
        expired_count = remove_expired_vip_users()
        if expired_count > 0:
            print(f"🕐 Удалено {expired_count} пользователей с истекшим VIP статусом")
        else:
            print("🕐 Проверка VIP статусов: истекших пользователей не найдено")
    except Exception as e:
        print(f"❌ Ошибка при проверке VIP статусов: {e}")

async def sync_group_members_job(context: ContextTypes.DEFAULT_TYPE):
    """Задача для синхронизации участников группы с базой данных"""
    try:
        # Получаем количество участников в группе
        member_count = await context.bot.get_chat_member_count(FREE_GROUP_ID)
        print(f"📊 Количество участников в группе: {member_count}")
        
        # Пока что просто логируем количество участников
        # В будущем можно добавить реальную синхронизацию через webhook
        print(f"🔄 Синхронизация: в группе {member_count} участников")
        print("ℹ️ Для полной синхронизации пользователей используйте webhook или ручную синхронизацию через админ панель")
            
    except Exception as e:
        print(f"❌ Ошибка при синхронизации участников группы: {e}")

async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений из каналов и групп"""
    # Проверяем, что сообщение из VIP группы
    if update.channel_post and update.channel_post.chat.id == VIP_GROUP_ID:
        message = update.channel_post
        print(f"Новое сообщение в VIP группе от {message.from_user.username if message.from_user else 'канала'}")
        print(f"Текст: {message.text if message.text else 'медиа-контент'}")
        
        # Автоматически добавляем отправителя в базу данных (если есть)
        if message.from_user:
            user_id = message.from_user.id
            username = message.from_user.username
            
            # Проверяем, есть ли пользователь в базе
            conn = sqlite3.connect('bot.db')
            c = conn.cursor()
            c.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
            exists = c.fetchone()
            
            if not exists:
                # Добавляем пользователя в базу
                c.execute('''
                    INSERT INTO users (user_id, username, is_vip, created_at) 
                    VALUES (?, ?, 0, datetime('now'))
                ''', (user_id, username))
                conn.commit()
                print(f"➕ Автоматически добавлен новый пользователь: {username} (ID: {user_id})")
            
            conn.close()
        
        # Планируем отправку в бесплатную группу через MESSAGE_DELAY секунд
        context.job_queue.run_once(
            send_to_free_group,
            MESSAGE_DELAY,
            data={'message': message},
            name=f"delayed_message_{message.message_id}"
        )
        print(f"Запланирована отправка через {MESSAGE_DELAY} секунд")

async def handle_regular_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка обычных сообщений из групп"""
    # Проверяем, что сообщение из VIP группы
    if update.message and update.message.chat.id == VIP_GROUP_ID:
        message = update.message
        print(f"Новое сообщение в VIP группе от {message.from_user.username if message.from_user else 'неизвестного'}")
        print(f"Текст: {message.text if message.text else 'медиа-контент'}")
        
        # Автоматически добавляем отправителя в базу данных
        if message.from_user:
            user_id = message.from_user.id
            username = message.from_user.username
            
            # Проверяем, есть ли пользователь в базе
            conn = sqlite3.connect('bot.db')
            c = conn.cursor()
            c.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
            exists = c.fetchone()
            
            if not exists:
                # Добавляем пользователя в базу
                c.execute('''
                    INSERT INTO users (user_id, username, is_vip, created_at) 
                    VALUES (?, ?, 0, datetime('now'))
                ''', (user_id, username))
                conn.commit()
                print(f"➕ Автоматически добавлен новый пользователь: {username} (ID: {user_id})")
            
            conn.close()
        
        # Обрабатываем сообщение через AI для извлечения данных такси
        if message.text:
            try:
                processor = DeepSeekProcessor()
                order_data = await processor.process_taxi_message(message.text)
                
                if order_data and order_data.get('is_valid'):
                    # Собираем информацию об отправителе
                    sender_info = None
                    if message.from_user:
                        sender_info = {
                            'id': message.from_user.id,
                            'username': message.from_user.username,
                            'first_name': message.from_user.first_name,
                            'last_name': message.from_user.last_name
                        }
                    
                    add_taxi_order(order_data, sender_info)
                    print(f"Заказ такси сохранен: {order_data.get('route')} от {sender_info.get('username') if sender_info else 'Unknown'}")
            except Exception as e:
                print(f"Ошибка обработки AI: {e}")
        
        # Планируем отправку в бесплатную группу через MESSAGE_DELAY секунд
        context.job_queue.run_once(
            send_to_free_group,
            MESSAGE_DELAY,
            data={'message': message},
            name=f"delayed_message_{message.message_id}"
        )
        print(f"Запланирована отправка через {MESSAGE_DELAY} секунд")

async def daily_subscription_check_job(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневная задача для проверки подписок."""
    print(f"🕐 Запускаю ежедневную проверку подписок.")
    
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()

    # Получаем всех пользователей из нашей БД, у кого есть активная или истекшая подписка
    c.execute("SELECT user_id, vip_until FROM users WHERE vip_until IS NOT NULL")
    all_vip_users = c.fetchall()
    
    now = datetime.now()

    for user_id, vip_until_str in all_vip_users:
        try:
            user_vip_until = datetime.fromisoformat(vip_until_str)
            time_left = user_vip_until - now
            #уведы перед истчечением
            if time_left.days >= 0:
                if 2 <= time_left.days < 3:
                    await context.bot.send_message(user_id, "⏰ Напоминание: Ваша VIP-подписка истекает через 3 дня. Используйте /start для продления.")
                    print(f"Отправлено уведомление за 3 дня пользователю {user_id}")

                elif 1 <= time_left.days < 2:
                    await context.bot.send_message(user_id, "⏰ Напоминание: Ваша VIP-подписка истекает через 2 дня. Используйте /start для продления.")
                    print(f"Отправлено уведомление за 2 дня пользователю {user_id}")

                elif 0 <= time_left.days < 1:
                    await context.bot.send_message(user_id, "‼️ Внимание: Ваша VIP-подписка истекает через 24 часа! Используйте /start, чтобы продлить ее и не потерять доступ к VIP.")
                    print(f"Отправлено уведомление за 1 день пользователю {user_id}")
            
            # Обработка истекших подписок 
            else:
                days_since_expired = -time_left.days

                # Если прошло менее 7 дней - это льготный период.
                if 0 <= days_since_expired < 7:
                    days_left_grace = 7 - days_since_expired
                    await context.bot.send_message(
                        user_id,
                        f"❗️ Ваша VIP-подписка истекла. Мы вас удалим из группы через {days_left_grace} дней.\n\n"
                        "Используйте /start, чтобы оплатить и остаться в группе."
                    )
                    print(f"Пользователь {user_id} в льготном периоде. Осталось дней: {days_left_grace}")

                # Если прошло 7 или более дней - удаляем.
                elif days_since_expired >= 7:
                    print(f"Льготный период для {user_id} истек. Попытка удаления...")
                    try:
                        # Проверяем, состоит ли пользователь еще в группе, перед удалением
                        chat_member = await context.bot.get_chat_member(chat_id=VIP_GROUP_ID, user_id=user_id)
                        if chat_member.status not in ['left', 'kicked']:
                            await context.bot.ban_chat_member(chat_id=VIP_GROUP_ID, user_id=user_id)
                            await context.bot.unban_chat_member(chat_id=VIP_GROUP_ID, user_id=user_id)
                            
                            await context.bot.send_message(
                                user_id,
                                "⌛️ Ваш льготный период закончился, и вы были удалены из VIP-группы.\n\n"
                                "Вы всегда можете вернуться, использовав команду /start и оплатив подписку."
                            )
                            print(f"✅ Пользователь {user_id} успешно удален из VIP-группы.")
                        else:
                            print(f"Пользователь {user_id} уже покинул группу.")

                        # Сбрасываем VIP-статус в БД в любом случае
                        c.execute("UPDATE users SET is_vip = 0, vip_until = NULL WHERE user_id = ?", (user_id,))
                        
                    except Exception as e:
                        print(f"❌ Не удалось удалить пользователя {user_id}: {e}. Возможно, он уже вышел или бот не админ.")
                        # Все равно сбрасываем статус, чтобы не пытаться удалить его снова
                        c.execute("UPDATE users SET is_vip = 0, vip_until = NULL WHERE user_id = ?", (user_id,))

        except Exception as e:
            print(f"Ошибка при обработке пользователя {user_id}: {e}")

    conn.commit()
    conn.close()
    print("✅ Ежедневная проверка подписок завершена.") 




async def send_to_free_group(context: ContextTypes.DEFAULT_TYPE):
    """Отправка сообщения в бесплатную группу"""
    message = context.job.data['message']
    
    # Автоматически добавляем отправителя в базу данных
    if message.from_user:
        user_id = message.from_user.id
        username = message.from_user.username
        
        # Проверяем, есть ли пользователь в базе
        conn = sqlite3.connect('bot.db')
        c = conn.cursor()
        c.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
        exists = c.fetchone()
        
        if not exists:
            # Добавляем пользователя в базу
            c.execute('''
                INSERT INTO users (user_id, username, is_vip, created_at) 
                VALUES (?, ?, 0, datetime('now'))
            ''', (user_id, username))
            conn.commit()
            print(f"➕ Автоматически добавлен новый пользователь: {username} (ID: {user_id})")
        
        conn.close()
    
    try:
        # Фильтр: пересылать только сообщения, где текст/подпись длиннее 20 символов
        content_text = None
        if getattr(message, 'text', None):
            content_text = message.text
        elif getattr(message, 'caption', None):
            content_text = message.caption

        if not content_text or len(content_text.strip()) <= 20:
            print("Пропуск пересылки: сообщение короче или равно 20 символам")
            return

        # Определяем тип контента и отправляем соответствующим образом
        if message.text:
            # Текстовое сообщение
            await context.bot.send_message(
                chat_id=FREE_GROUP_ID,
                text=message.text,
                entities=message.entities,
                disable_web_page_preview=not message.link_preview_options if hasattr(message, 'link_preview_options') else True
            )
        elif message.photo:
            # Фото
            await context.bot.send_photo(
                chat_id=FREE_GROUP_ID,
                photo=message.photo[-1].file_id,
                caption=message.caption,
                caption_entities=message.caption_entities
            )
        elif message.video:
            # Видео
            await context.bot.send_video(
                chat_id=FREE_GROUP_ID,
                video=message.video.file_id,
                caption=message.caption,
                caption_entities=message.caption_entities
            )
        elif message.document:
            # Документ
            await context.bot.send_document(
                chat_id=FREE_GROUP_ID,
                document=message.document.file_id,
                caption=message.caption,
                caption_entities=message.caption_entities
            )
        elif message.audio:
            # Аудио
            await context.bot.send_audio(
                chat_id=FREE_GROUP_ID,
                audio=message.audio.file_id,
                caption=message.caption,
                                caption_entities=message.caption_entities
            )
        elif message.voice:
            # Голосовое сообщение
            await context.bot.send_voice(
                chat_id=FREE_GROUP_ID,
                voice=message.voice.file_id,
                caption=message.caption,
                caption_entities=message.caption_entities
            )
        elif message.video_note:
            # Видео-кружок
            await context.bot.send_video_note(
                chat_id=FREE_GROUP_ID,
                video_note=message.video_note.file_id
            )
        elif message.sticker:
            # Стикер
            await context.bot.send_sticker(
                chat_id=FREE_GROUP_ID,
                sticker=message.sticker.file_id
            )
        elif message.animation:
            # GIF/анимация
            await context.bot.send_animation(
                chat_id=FREE_GROUP_ID,
                animation=message.animation.file_id,
                caption=message.caption,
                caption_entities=message.caption_entities
            )
        elif message.poll:
            # Опрос
            await context.bot.forward_message(
                chat_id=FREE_GROUP_ID,
                from_chat_id=VIP_GROUP_ID,
                message_id=message.message_id
            )
        else:
            # Для остальных типов просто пересылаем
            await context.bot.forward_message(
                chat_id=FREE_GROUP_ID,
                from_chat_id=VIP_GROUP_ID,
                message_id=message.message_id
            )
        
        print(f"Сообщение успешно отправлено в бесплатную группу")
        
        # Добавляем уведомление с кнопкой перехода в бота
        keyboard = [[InlineKeyboardButton("💎 Получить VIP доступ", url=f"https://t.me/{context.bot.username}?start=buy_vip")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=FREE_GROUP_ID,
            text=f"⏰ Это сообщение было опубликовано {MESSAGE_DELAY} секунд назад в VIP группе.\n\n"
                "💎 Хотите получать сообщения мгновенно?\n"
                f"{VIP_CHANNEL_LINK}\n"
                "👆 Нажмите кнопку выше, чтобы перейти в бота для оформления VIP доступа",
            reply_markup=reply_markup,
            disable_notification=True
        )
        
    except Exception as e:
        print(f"Ошибка при отправке в бесплатную группу: {e}")



async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    print(f"Произошла ошибка: {context.error}")
    print(f"Update: {update}")

def main():
    # Инициализируем БД
    init_db()
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем периодическую задачу для проверки истекших VIP статусов (каждый час)
    if application.job_queue:
        application.job_queue.run_repeating(
            check_expired_vip_job,
            interval=timedelta(hours=1),
            first=timedelta(minutes=5)  # Первый запуск через 5 минут
        )
        print("🕐 Задача проверки истекших VIP статусов добавлена (каждый час)")
        
        # Добавляем задачу для синхронизации участников группы (каждые 6 часов)
        application.job_queue.run_repeating(
            sync_group_members_job,
            interval=timedelta(hours=6),
            first=timedelta(minutes=10)  # Первый запуск через 10 минут
        )
        print("🔄 Задача синхронизации участников группы добавлена (каждые 6 часов)")   
        application.job_queue.run_repeating(
            daily_subscription_check_job,  
            interval=timedelta(days=1),    
            first=timedelta(seconds=120)    
        )
        print("🕐 Ежедневная задача по управлению подписками добавлена")

        

        #application.job_queue.run_repeating(purge_expired_vip_users_job, interval=timedelta(days=1), first=timedelta(minutes=1))
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback))

    
    # Обработчик для сообщений из каналов (channel_post)
    application.add_handler(MessageHandler(
        filters.Chat(VIP_GROUP_ID) & filters.UpdateType.CHANNEL_POST,
        handle_channel_post
    ))
    
    # Обработчик для обычных сообщений из групп
    application.add_handler(MessageHandler(
        filters.Chat(VIP_GROUP_ID) & ~filters.COMMAND,
        handle_regular_message
    ))
    
    # Обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запускаем бота
    print("🚀 Бот запущен!")
    print(f"VIP Group ID: {VIP_GROUP_ID}")
    print(f"Free Group ID: {FREE_GROUP_ID}")
    print(f"Message Delay: {MESSAGE_DELAY} seconds")
    print("Ожидаем сообщения...")
    
    # Запускаем с поддержкой всех типов обновлений
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
