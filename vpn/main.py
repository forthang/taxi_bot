# /bot/main.py

import logging
import os
import uuid
import asyncio
import io
import qrcode
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler
from typing import List, Optional, Union
import traceback
import html
import json

from telegram import (
    Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, ContextTypes, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, AIORateLimiter, ConversationHandler
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden

from yookassa import Configuration, Payment
from aiohttp import web
from dotenv import load_dotenv

# --- Локальные импорты ---
from database import (
    initialize_db, add_user, get_active_subscription, get_any_subscription,
    update_or_create_subscription, has_used_trial, mark_trial_as_used,
    log_referral_purchase, get_referral_program_stats, get_user_source,
    get_user_referrer, has_agreed_to_terms, mark_terms_as_agreed,
    add_payment, update_payment_status, get_pending_payments, get_stats, get_all_user_ids,
    get_payment_info  # НОВАЯ ФУНКЦИЯ
)
from api import RemnaAsyncManager, RemnaAPIError
from scheduler import run_notifications

load_dotenv()

# --- Настройка логирования ---
LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_FILE_PATH = os.path.join(LOG_DIR, 'bot.log')
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(LOG_FILE_PATH, maxBytes=10485760, backupCount=5),
        logging.StreamHandler()
    ]
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Основные переменные ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "telegram")
TERMS_URL = os.getenv("TERMS_URL")
SET_URL = os.getenv("SET_URL")

# --- Поддержка нескольких администраторов ---
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = []
if ADMIN_IDS_STR:
    try:
        ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()]
        logger.info(f"Загружены ID администраторов: {ADMIN_IDS}")
    except ValueError:
        logger.error("Ошибка при чтении ADMIN_IDS. Убедитесь, что это числа, разделенные запятыми.")

# --- Конфигурация Remnawave ---
REMNAWAVE_PANEL_URL = os.getenv("REMNAWAVE_PANEL_URL")
REMNAWAVE_API_TOKEN = os.getenv("REMNAWAVE_API_TOKEN")
REMNAWAVE_SQUAD_UUID = os.getenv("REMNAWAVE_SQUAD_UUID")
REMNAWAVE_ENABLED = all([REMNAWAVE_PANEL_URL, REMNAWAVE_API_TOKEN, REMNAWAVE_SQUAD_UUID])

if not REMNAWAVE_ENABLED:
    logger.warning("Переменные для Remnawave настроены не полностью! Функционал VPN будет недоступен.")

# --- Конфигурация ЮKassa ---
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))
YOOKASSA_ENABLED = all([YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, SERVER_BASE_URL])

if YOOKASSA_ENABLED:
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_KEY
    logger.info("Конфигурация ЮKassa загружена.")
else:
    logger.warning("Переменные для ЮKassa не найдены! Оплата будет недоступна.")

# --- Тарифы ---
TARIFFS = {
    "buy_30": {"price": 1.00, "days": 30, "description": "🗓️ Подписка на 1 месяц"},
    "buy_90": {"price": 799.00, "days": 90, "description": "🌱 Подписка на 3 месяца"}
}

# --- Клавиатуры ---
main_keyboard = ReplyKeyboardMarkup([
    ["🔐 Мой VPN", "💎 Подписка"],
    ["🎁 Пригласить друга", "💬 Помощь"]
], resize_keyboard=True)

admin_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
    [InlineKeyboardButton("📄 Посмотреть логи (файл)", callback_data="admin_view_logs")],
    [InlineKeyboardButton("💬 Рассылка", callback_data="admin_broadcast")]
])

# --- Состояния для ConversationHandler (Рассылка) ---
BROADCAST_MESSAGE, BROADCAST_CONFIRM = range(2)


# --- ХЕЛПЕРЫ ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f"🔥 <b>Произошла ошибка в боте!</b>\n\n"
        f"<pre>Update: {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}</pre>\n\n"
        f"<pre>{html.escape(tb_string[-3000:])}</pre>" 
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=message, parse_mode=ParseMode.HTML)
        except:
            pass

def safe_parse_datetime(date_obj: Union[str, datetime, None]) -> datetime:
    if not date_obj:
        return datetime.now(timezone.utc)
    
    if isinstance(date_obj, datetime):
        return date_obj if date_obj.tzinfo else date_obj.replace(tzinfo=timezone.utc)

    try:
        clean_str = str(date_obj).split('+')[0].replace('T', ' ').split('.')[0].strip()
        dt = datetime.strptime(clean_str, '%Y-%m-%d %H:%M:%S')
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, IndexError, AttributeError) as e:
        logger.error(f"Date parse error for value '{date_obj}': {e}")
        return datetime.now(timezone.utc)

def format_bytes(size: float) -> str:
    if not size: 
        return "0 GB"
    power = 2**30
    n = size / power
    if n < 0.01:
        return f"{size / (2**20):.0f} MB"
    return f"{n:.2f} GB"

async def notify_admins(application: Application, message: str):
    logger.info(f"Отправка уведомления администраторам: {message[:100]}...")
    for admin_id in ADMIN_IDS:
        try:
            await application.bot.send_message(chat_id=admin_id, text=message)
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление администратору {admin_id}: {e}")

# --- ЛОГИКА ПОДПИСОК И ПЛАТЕЖЕЙ ---

async def process_payment(application: Application, payment_id: str, user_id: int, tariff: str):
    """
    Асинхронно обрабатывает успешный платеж.
    """
    logger.info(f"PROCESS_PAYMENT: Старт для {payment_id}, user={user_id}, tariff={tariff}")
    
    try:
        # 1. Проверяем, не обработан ли уже платеж (защита от дублей)
        payment_info = await get_payment_info(payment_id)
        if payment_info:
            current_status = payment_info.get("status")
            if current_status == 'completed':
                logger.info(f"PROCESS_PAYMENT: Платеж {payment_id} уже обработан (status=completed). Пропускаем.")
                return

        await update_payment_status(payment_id, 'processing')
        
        days_to_add = TARIFFS[tariff]['days']
        await grant_subscription(application, user_id, days_to_add)
        
        await update_payment_status(payment_id, 'completed')
        logger.info(f"PROCESS_PAYMENT: Успешно завершен для {payment_id}.")
        
    except Exception as e:
        logger.critical(f"PROCESS_PAYMENT: Критическая ошибка для {payment_id}: {e}", exc_info=True)
        await update_payment_status(payment_id, 'failed')
        await notify_admins(application, f"❗️ Ошибка обработки платежа `{payment_id}` (user: `{user_id}`).\nТекст: `{e}`")

async def grant_subscription(application: Application, user_id: int, days: int, is_trial: bool = False, is_manual: bool = False):
    """
    Создает или продлевает подписку в Remnawave и PostgreSQL.
    """
    logger.info(f"Выдача подписки: user_id={user_id}, days={days}, trial={is_trial}, manual={is_manual}")
    
    if not REMNAWAVE_ENABLED:
        msg = "Интеграция с Remnawave отключена, подписка не может быть выдана."
        logger.error(msg)
        if is_manual:
            await notify_admins(application, f"Ошибка: {msg}")
        # Если это автоматический платеж, мы должны выбросить ошибку, чтобы process_payment поймал её
        if not is_manual:
            raise Exception(msg)
        return

    try:
        # Шаг 1: Работа с API Remnawave
        username_in_panel = f"tg_{user_id}"
        old_sub_data = await get_any_subscription(user_id) 
        
        start_from = datetime.now(timezone.utc)
        
        if old_sub_data and old_sub_data[1]:
            current_end_date = safe_parse_datetime(old_sub_data[1])
            if current_end_date > start_from:
                start_from = current_end_date
        
        new_expire_dt = start_from + timedelta(days=days)

        async with RemnaAsyncManager(REMNAWAVE_PANEL_URL, REMNAWAVE_API_TOKEN) as mgr:
            user_in_panel = await mgr.find_user_by_username(username_in_panel)
            if user_in_panel:
                await mgr.update_user(username=username_in_panel, updates={"expireAt": new_expire_dt.isoformat().replace('+00:00', 'Z')})
            else:
                await mgr.create_user(username=username_in_panel, squad_uuid=REMNAWAVE_SQUAD_UUID, expire_at=new_expire_dt)
        
        # Шаг 2: Обновление в БД
        vless_uuid_for_db = old_sub_data[0] if old_sub_data else str(uuid.uuid4())
        await update_or_create_subscription(user_id=user_id, vless_uuid=vless_uuid_for_db, duration_days=days)
        
        if is_trial:
            await mark_trial_as_used(user_id)

        # Шаг 3: Реферальный бонус
        if not is_trial and not is_manual:
            referrer_id = await log_referral_purchase(user_id)
            if referrer_id:
                logger.info(f"Начисляем реферальный бонус 30 дней для user_id={referrer_id}")
                await grant_subscription(application, referrer_id, 30, is_manual=True)
                try:
                    await application.bot.send_message(
                        chat_id=referrer_id, 
                        text="🎉 Ваш друг совершил покупку! Вам начислено *30 бонусных дней*!", 
                        parse_mode=ParseMode.MARKDOWN
                    )
                except (BadRequest, Forbidden):
                    pass

        # Шаг 4: Уведомление пользователя
        if is_manual:
            message_text = f"✅ Администратор вручную начислил вам *{days} дней* подписки."
        else:
            message_type = "Тестовый доступ" if is_trial else "Подписка"
            message_text = f"✅ *{message_type} на {days} дней активирован!*\n\nВаша подписка продлена. Приятного пользования!"
        
        await application.bot.send_message(chat_id=user_id, text=message_text, parse_mode=ParseMode.MARKDOWN)
        logger.info(f"Подписка выдана успешно для {user_id}.")

    except Exception as e:
        logger.error(f"Ошибка при grant_subscription для {user_id}: {e}", exc_info=True)
        # Пробрасываем ошибку наверх, чтобы process_payment узнал о сбое
        raise e

# --- ОБРАБОТЧИКИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Команда /start от {user.id}")
    
    payload = context.args[0] if context.args else None
    source, referrer_id = None, None
    
    if payload:
        if payload.startswith("ref_"):
            try:
                ref_id = int(payload.split('_')[1])
                if ref_id != user.id: 
                    referrer_id = ref_id
            except: pass
        else: 
            source = payload
            
    await add_user(user.id, user.username, user.first_name, user.last_name, source=source, referrer_id=referrer_id)
    
    text = (f"👋 Привет, {user.first_name or 'друг'}!\n"
            f"Бот **Интернет всегда** готов к работе.")
    await update.message.reply_text(text, reply_markup=main_keyboard, parse_mode=ParseMode.MARKDOWN)

async def my_vpn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id if query else update.effective_user.id
    chat_id = query.message.chat_id if query else update.effective_chat.id
    message_to_edit = query.message if query else None

    if query: await query.answer()

    subscription = await get_active_subscription(user_id)
    
    if not subscription:
        text = "❌ **Подписка неактивна**\n\nОформите подписку или возьмите тест."
        buttons = []
        if not await has_used_trial(user_id):
            buttons.append([InlineKeyboardButton("🚀 Тест 3 дня", callback_data="get_trial")])
        buttons.append([InlineKeyboardButton("💎 Купить подписку", callback_data="go_to_subscription")])
        
        if message_to_edit:
            await message_to_edit.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)
        else:
            await context.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)
        return

    _, end_date_raw = subscription
    end_date_formatted = safe_parse_datetime(end_date_raw).strftime('%d.%m.%Y')

    try:
        username_in_panel = f"tg_{user_id}"
        traffic_info = ""
        async with RemnaAsyncManager(REMNAWAVE_PANEL_URL, REMNAWAVE_API_TOKEN) as mgr:
            user_data = await mgr.find_user_by_username(username_in_panel)
            if not user_data or not user_data.get("subscriptionUrl"):
                # Пытаемся создать, если потерялся
                raise RemnaAPIError("Пользователь есть в БД, но не в панели")
            
            sub_url = user_data.get("subscriptionUrl")
            used = user_data.get('trafficUsed', 0)
            limit = user_data.get('trafficLimit') or user_data.get('dataLimit') or 0
            traffic_info = f"📊 Трафик: {format_bytes(used)} / {(format_bytes(limit) if limit else '∞')}"

        text = (f"✅ **Подписка до {end_date_formatted}**\n{traffic_info}\n\n"
                f"Ваша ссылка:\n`{sub_url}`")
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📲 QR-код", callback_data="show_qr_remna")],
            [InlineKeyboardButton("📖 Инструкция", callback_data="show_instructions")]
        ])
    except Exception as e:
        logger.error(f"Ошибка получения данных VPN: {e}")
        text = "❗️ Ошибка связи с сервером VPN. Попробуйте позже."
        markup = None

    if message_to_edit:
        await message_to_edit.edit_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await context.bot.send_message(chat_id, text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

async def subscription_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: await query.answer()
    
    chat_id = query.message.chat_id if query else update.effective_chat.id
    user_id = query.from_user.id if query else update.effective_user.id

    buttons = []
    if not await has_used_trial(user_id):
        buttons.append([InlineKeyboardButton("🚀 Тест 3 дня", callback_data="get_trial")])

    for key, tariff in TARIFFS.items():
        buttons.append([InlineKeyboardButton(f"{tariff['description']} — {tariff['price']:.0f}₽", callback_data=key)])

    await context.bot.send_message(chat_id, "💎 **Выберите тариф:**", reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)

async def referral_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    invited, purchased = await get_referral_program_stats(user_id)
    
    text = (f"🎁 **Реферальная программа**\n\nПриглашено: {invited}\nКупили: {purchased}\n"
            f"Ссылка:\n`{link}`")
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("👨‍💻 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}")]])
    await update.message.reply_text("💬 Если возникли вопросы:", reply_markup=markup)

# --- АДМИН ---
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in ADMIN_IDS:
        await update.message.reply_text("Админка:", reply_markup=admin_keyboard)

async def grant_days_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        _, uid, days = update.message.text.split()
        await grant_subscription(context.application, int(uid), int(days), is_manual=True)
        await update.message.reply_text("✅ Выдано.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# --- Рассылка ---
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Пришлите текст рассылки:")
    return BROADCAST_MESSAGE

async def broadcast_get_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['msg'] = update.message
    await update.message.reply_text("Разослать?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Да", callback_data="broadcast_yes"), InlineKeyboardButton("Нет", callback_data="broadcast_no")]
    ]))
    return BROADCAST_CONFIRM

async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "broadcast_yes":
        await query.edit_message_text("Рассылка запущена...")
        ids = await get_all_user_ids()
        msg = context.user_data['msg']
        for uid in ids:
            try:
                await msg.copy(chat_id=uid)
                await asyncio.sleep(0.05)
            except: pass
        await context.bot.send_message(query.from_user.id, "Рассылка завершена.")
    else:
        await query.edit_message_text("Отменено.")
    context.user_data.clear()
    return ConversationHandler.END

async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    return ConversationHandler.END

# --- BUTTON HANDLER ---

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if user_id in ADMIN_IDS:
        if data == 'admin_stats':
            stats = await get_stats()
            await query.edit_message_text(f"Пользователей: {stats['total_users']}\nПодписок: {stats['active_subscriptions']}")
            return
        if data == 'admin_view_logs':
            if os.path.exists(LOG_FILE_PATH):
                await query.message.reply_document(open(LOG_FILE_PATH, 'rb'), filename='log.txt')
            else: await query.answer("Нет логов")
            return

    if data == "get_trial":
        if await has_used_trial(user_id):
            await query.answer("Уже брали тест!", show_alert=True)
        else:
            await query.edit_message_text("Активация...")
            await grant_subscription(context.application, user_id, 3, is_trial=True)
        return

    if data in TARIFFS:
        if not YOOKASSA_ENABLED:
            await query.answer("Оплата недоступна", show_alert=True)
            return
        
        tariff = TARIFFS[data]
        # ВАЖНО: user_id передаем как строку, иначе ЮКасса может отбросить метаданные
        payment_data = {
            "amount": {"value": f"{tariff['price']:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": f"https://t.me/{(await context.bot.get_me()).username}"},
            "capture": True,
            "description": f"VPN {tariff['days']} дн. (ID: {user_id})",
            "metadata": {'user_id': str(user_id), 'tariff_callback': data},
            "receipt": {
                "customer": {"email": f"user{user_id}@granatvpn.bot"},
                "items": [{
                    "description": tariff['description'],
                    "quantity": "1.00",
                    "amount": {"value": f"{tariff['price']:.2f}", "currency": "RUB"},
                    "vat_code": 1,
                    "payment_mode": "full_payment",
                    "payment_subject": "service"
                }]
            }
        }
        try:
            payment = Payment.create(payment_data, uuid.uuid4())
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Оплатить", url=payment.confirmation.confirmation_url)]])
            await query.edit_message_text(f"К оплате: {tariff['price']}₽", reply_markup=markup)
        except Exception as e:
            logger.error(f"Ошибка создания платежа: {e}")
            await query.answer("Ошибка создания ссылки", show_alert=True)
        return

    if data == "show_qr_remna":
        await query.answer("QR...")
        try:
            async with RemnaAsyncManager(REMNAWAVE_PANEL_URL, REMNAWAVE_API_TOKEN) as mgr:
                ud = await mgr.find_user_by_username(f"tg_{user_id}")
                url = ud.get("subscriptionUrl")
            qr = qrcode.make(url)
            buf = io.BytesIO()
            qr.save(buf, 'PNG')
            buf.seek(0)
            await query.message.reply_photo(buf, caption="QR для подключения")
        except: await query.answer("Ошибка")
        return
        
    if data == "go_to_subscription":
        await subscription_handler(update, context)
        return

    if data == "show_instructions":
        await query.edit_message_text(f"Инструкция: {SET_URL}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_vpn")]]))
        return

    if data == "back_to_vpn":
        await my_vpn_handler(update, context)
        return

    await query.answer()

# --- ВЕБХУК ---

async def yookassa_webhook_handler(request: web.Request):
    application = request.app['bot_app']
    
    # 1. Читаем сырое тело запроса для отладки
    try:
        body_bytes = await request.read()
        body_str = body_bytes.decode('utf-8')
        logger.info(f"WEBHOOK RAW BODY: {body_str}")
        
        if not body_str:
            return web.Response(status=400, text="Empty body")
            
        data = json.loads(body_str)
    except Exception as e:
        logger.error(f"WEBHOOK: Ошибка чтения JSON: {e}")
        return web.Response(status=400)

    try:
        event = data.get('event')
        if event == 'payment.succeeded':
            obj = data.get('object', {})
            payment_id = obj.get('id')
            metadata = obj.get('metadata', {})
            
            # Извлекаем данные
            user_id = metadata.get('user_id')
            tariff = metadata.get('tariff_callback')
            amount = obj.get('amount', {}).get('value')
            
            logger.info(f"WEBHOOK: Parsed - id={payment_id}, user={user_id}, tariff={tariff}")

            if not all([payment_id, user_id, tariff]):
                logger.error("WEBHOOK: Отсутствуют обязательные поля в метаданных!")
                # Возвращаем 200, чтобы ЮКасса не долбила нас повторами ошибочного платежа
                return web.Response(status=200)

            # 2. Сохраняем/Обновляем платеж в БД
            try:
                # Преобразуем user_id в int, amount в float
                await add_payment(payment_id, int(user_id), float(amount), tariff)
            except Exception as e:
                logger.warning(f"WEBHOOK: Ошибка при записи в БД (возможно дубль): {e}")

            # 3. Запускаем выдачу в фоне
            asyncio.create_task(process_payment(application, payment_id, int(user_id), tariff))
            
    except Exception as e:
        logger.critical(f"WEBHOOK: Внутренняя ошибка обработчика: {e}", exc_info=True)
        return web.Response(status=500)
        
    return web.Response(status=200)

async def scheduler_wrapper(application: Application):
    await asyncio.sleep(10) # Даем боту запуститься
    while True:
        try:
            await run_notifications(application.bot)
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        await asyncio.sleep(3600)

async def main():
    if not BOT_TOKEN:
        print("NO BOT TOKEN")
        return

    await initialize_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers
    bh = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_start, pattern='^admin_broadcast$')],
        states={
            BROADCAST_MESSAGE: [MessageHandler(filters.TEXT, broadcast_get_message)],
            BROADCAST_CONFIRM: [CallbackQueryHandler(broadcast_confirm, pattern='^broadcast_')]
        },
        fallbacks=[CommandHandler('cancel', broadcast_cancel)]
    )
    app.add_handler(bh)
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('grant', grant_days_command))
    app.add_handler(CommandHandler('admin', admin_command))
    app.add_handler(MessageHandler(filters.Regex('^🔐'), my_vpn_handler))
    app.add_handler(MessageHandler(filters.Regex('^💎'), subscription_handler))
    app.add_handler(MessageHandler(filters.Regex('^🎁'), referral_handler))
    app.add_handler(MessageHandler(filters.Regex('^💬'), help_handler))
    app.add_handler(CallbackQueryHandler(button_callback_handler))
    app.add_error_handler(error_handler)

    # Webhook server
    wh_app = web.Application()
    wh_app['bot_app'] = app
    wh_app.router.add_post("/yookassa_webhook", yookassa_webhook_handler)
    runner = web.AppRunner(wh_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT)
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await site.start()
    
    asyncio.create_task(scheduler_wrapper(app))
    
    logger.info("BOT STARTED")
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except: pass