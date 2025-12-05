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
    add_payment, update_payment_status, get_pending_payments, get_stats, get_all_user_ids
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
    "buy_30": {"price": 129.00, "days": 30, "description": "🗓️ Подписка на 1 месяц"},
    "buy_90": {"price": 359.00, "days": 90, "description": "🌱 Подписка на 3 месяца"}
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
# Добавьте эту функцию
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    # Формируем текст ошибки
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f"🔥 <b>Произошла ошибка в боте!</b>\n\n"
        f"<pre>Update: {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}</pre>\n\n"
        f"<pre>{html.escape(tb_string[-3000:])}</pre>" # Ограничиваем длину
    )

    # Отправляем всем админам
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=message, parse_mode=ParseMode.HTML)
        except:
            pass



def safe_parse_datetime(date_obj: Union[str, datetime, None]) -> datetime:
    """
    Безопасный парсинг даты. 
    PostgreSQL возвращает datetime, SQLite возвращал str.
    """
    if date_obj is None:
        return datetime.now(timezone.utc)
    
    if isinstance(date_obj, datetime):
        # Если база (asyncpg) уже вернула datetime, просто убедимся, что есть timezone
        if date_obj.tzinfo is None:
            return date_obj.replace(tzinfo=timezone.utc)
        return date_obj

    # Если вдруг пришла строка (старые данные или SQLite)
    try:
        clean_date = str(date_obj).split('.')[0].split('+')[0].split('Z')[0].strip()
        return datetime.strptime(clean_date, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    except (ValueError, IndexError, AttributeError) as e:
        logger.error(f"Не удалось распарсить дату '{date_obj}': {e}")
        return datetime.now(timezone.utc)

def format_bytes(size: float) -> str:
    """Форматирует байты в читаемый вид (GB, MB)."""
    if not size: 
        return "0 GB"
    power = 2**30 # 1024**3
    n = size / power
    if n < 0.01: # Если меньше 10 МБ, покажем в МБ
        return f"{size / (2**20):.0f} MB"
    return f"{n:.2f} GB"

async def notify_admins(application: Application, message: str):
    """Отправляет сообщение всем администраторам."""
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
    logger.info(f"Начало обработки платежа {payment_id} для user_id={user_id}.")
    try:
        await update_payment_status(payment_id, 'processing') # AWAIT
        
        days_to_add = TARIFFS[tariff]['days']
        await grant_subscription(application, user_id, days_to_add) # AWAIT
        
        await update_payment_status(payment_id, 'completed') # AWAIT
        logger.info(f"Платеж {payment_id} успешно обработан и завершен.")
        
    except Exception as e:
        logger.critical(f"Критическая ошибка при обработке платежа {payment_id} для user_id={user_id}: {e}", exc_info=True)
        await update_payment_status(payment_id, 'failed') # AWAIT
        await notify_admins(application, f"❗️ Критическая ошибка при обработке платежа `{payment_id}` для `user_id={user_id}`.\n\nОшибка: `{e}`\n\nТребуется ручное вмешательство!")

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
        return

    try:
        # Шаг 1: Работа с API Remnawave
        username_in_panel = f"tg_{user_id}"
        old_sub_data = await get_any_subscription(user_id) # AWAIT
        start_from = datetime.now(timezone.utc)
        
        # Если есть активная или будущая подписка, продлеваем от её конца
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
        await update_or_create_subscription(user_id=user_id, vless_uuid=vless_uuid_for_db, duration_days=days) # AWAIT
        
        if is_trial:
            await mark_trial_as_used(user_id) # AWAIT

        # Шаг 3: Реферальный бонус (только для реальных покупок)
        if not is_trial and not is_manual:
            referrer_id = await log_referral_purchase(user_id) # AWAIT
            if referrer_id:
                logger.info(f"Начисляем реферальный бонус 30 дней для user_id={referrer_id}")
                # Рекурсивный вызов для начисления бонуса
                await grant_subscription(application, referrer_id, 30, is_manual=True)
                try:
                    await application.bot.send_message(
                        chat_id=referrer_id, 
                        text="🎉 Поздравляем! Ваш друг совершил покупку, и мы начислили вам *30 бонусных дней* к подписке!", 
                        parse_mode=ParseMode.MARKDOWN
                    )
                except (BadRequest, Forbidden) as e:
                    logger.warning(f"Не удалось уведомить реферера {referrer_id} о бонусе: {e}")

        # Шаг 4: Уведомление пользователя
        if is_manual:
            message_text = f"✅ Администратор вручную начислил вам *{days} дней* подписки."
        else:
            message_type = "Тестовый доступ" if is_trial else "Подписка"
            message_text = f"✅ *{message_type} на {days} дней активирован!*\n\nТеперь в разделе «🔐 Мой VPN» вы найдете вашу единую ссылку для подключения."
        
        await application.bot.send_message(chat_id=user_id, text=message_text, parse_mode=ParseMode.MARKDOWN)
        logger.info(f"Процесс выдачи подписки для user_id={user_id} завершен успешно.")

    except Exception as e:
        logger.error(f"Ошибка при grant_subscription для {user_id}: {e}", exc_info=True)
        if is_manual:
             raise e

# --- ОБРАБОТЧИКИ (HANDLERS) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Команда /start от user: {user.id} ({user.username or 'N/A'}), args: {context.args}")
    
    payload = context.args[0] if context.args else None
    source, referrer_id = None, None
    
    if payload:
        if payload.startswith("ref_"):
            try:
                ref_id = int(payload.split('_')[1])
                if ref_id != user.id: 
                    referrer_id = ref_id
                    logger.info(f"Пользователь {user.id} пришел по реферальной ссылке от {referrer_id}")
            except (ValueError, IndexError): 
                logger.warning(f"Некорректный реферальный код: {payload}")
        else: 
            source = payload
            logger.info(f"Пользователь {user.id} пришел с источником: {source}")
            
    # Добавляем в БД с await
    await add_user(user.id, user.username, user.first_name, user.last_name, source=source, referrer_id=referrer_id) # AWAIT
    
    text = (f"👋 Привет, {user.first_name or 'пользователь'}!\n\n"
            f"Это бот **Интернет всегда** — ваш надежный и быстрый доступ к любым сервисам.\n\n"
            f"Выберите действие в меню.")
    await update.message.reply_text(text, reply_markup=main_keyboard, parse_mode=ParseMode.MARKDOWN)

async def my_vpn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображает статус подписки, трафик, ссылку и QR-код."""
    query = update.callback_query
    user_id = query.from_user.id if query else update.effective_user.id
    chat_id = query.message.chat_id if query else update.effective_chat.id
    message_to_edit = query.message if query else None

    if query:
        await query.answer()

    subscription = await get_active_subscription(user_id) # AWAIT
    
    if not subscription:
        text = "❌ **Подписка неактивна**\n\nЧтобы получить доступ к VPN, оформите подписку или воспользуйтесь бесплатным тестовым периодом."
        buttons = []
        if not await has_used_trial(user_id): # AWAIT
            buttons.append([InlineKeyboardButton("🚀 Попробовать 3 дня бесплатно", callback_data="get_trial")])
        buttons.append([InlineKeyboardButton("💎 Выбрать тариф", callback_data="go_to_subscription")])
        markup = InlineKeyboardMarkup(buttons)
        
        if message_to_edit:
            await message_to_edit.edit_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await context.bot.send_message(chat_id, text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        return

    # Если подписка активна
    _, end_date_raw = subscription
    end_date_obj = safe_parse_datetime(end_date_raw)
    end_date_formatted = end_date_obj.strftime('%d.%m.%Y')

    try:
        username_in_panel = f"tg_{user_id}"
        traffic_info = ""
        
        async with RemnaAsyncManager(REMNAWAVE_PANEL_URL, REMNAWAVE_API_TOKEN) as mgr:
            user_data = await mgr.find_user_by_username(username_in_panel)
            if not user_data or not user_data.get("subscriptionUrl"):
                raise RemnaAPIError(f"Пользователь {username_in_panel} найден, но ссылка отсутствует.")
            
            sub_url = user_data.get("subscriptionUrl")
            
            # --- УЛУЧШЕНИЕ: Получение статистики трафика ---
            used = user_data.get('trafficUsed', 0)
            # В Remnawave поле лимита может называться по-разному, обычно trafficLimit или dataLimit
            limit = user_data.get('trafficLimit') or user_data.get('dataLimit') or 0
            
            usage_str = format_bytes(used)
            limit_str = format_bytes(limit) if limit else "∞"
            traffic_info = f"📊 Трафик: {usage_str} / {limit_str}"
            # -----------------------------------------------

        text = (f"✅ **Подписка активна до {end_date_formatted}**\n"
                f"{traffic_info}\n\n"
                f"Это ваша единая ссылка для всех локаций. Добавьте ее в приложение, и все серверы появятся автоматически.\n\n"
                f"👇 Нажмите на ссылку, чтобы скопировать:\n"
                f"`{sub_url}`")
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📲 QR-код", callback_data="show_qr_remna")],
            [InlineKeyboardButton("📖 Инструкция по установке", callback_data="show_instructions")]
        ])

    except RemnaAPIError as e:
        logger.error(f"Не удалось получить данные из Remnawave для user_id {user_id}: {e}")
        text = "❗️ Не удалось получить вашу VPN-подписку. Пожалуйста, попробуйте через несколько минут. Если ошибка повторится, обратитесь в поддержку."
        markup = None

    try:
        if message_to_edit:
            await message_to_edit.edit_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await context.bot.send_message(chat_id, text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"Ошибка при обновлении меню 'Мой VPN': {e}")

async def subscription_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбора тарифов."""
    query = update.callback_query
    if query:
        await query.answer()
        user_id = query.from_user.id
        chat_id = query.message.chat_id
    else:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

    subscription = await get_active_subscription(user_id) # AWAIT
    text = "💎 **Выберите тариф**\n\nОплатите подписку, чтобы получить неограниченный доступ к быстрому и безопасному VPN."

    if subscription:
        _, end_date_raw = subscription
        end_date_obj = safe_parse_datetime(end_date_raw)
        text = f"✅ Ваша подписка активна до **{end_date_obj.strftime('%d.%m.%Y')}**.\n\nВы можете продлить ее, выбрав один из тарифов ниже. Новые дни добавятся к текущему сроку."

    buttons = []
    if not await has_used_trial(user_id): # AWAIT
        buttons.append([InlineKeyboardButton("🚀 Попробовать 3 дня бесплатно", callback_data="get_trial")])

    for key, tariff in TARIFFS.items():
        buttons.append([InlineKeyboardButton(f"{tariff['description']} — {tariff['price']:.0f}₽", callback_data=key)])

    await context.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)

async def referral_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Реферальная программа."""
    user_id = update.effective_user.id
    
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    
    invited_count, purchased_count = await get_referral_program_stats(user_id) # AWAIT
    bonus_days = purchased_count * 30
    
    text = (
        f"🎁 **Пригласите друга и получите 30 дней VPN бесплатно!**\n\n"
        f"Отправьте другу свою персональную ссылку. Как только он оплатит любую подписку, мы автоматически добавим 30 дней к вашей.\n\n"
        f"🔗 **Ваша ссылка:**\n`{referral_link}`\n\n"
        f"📈 **Статистика:**\n"
        f"- Приглашено: *{invited_count}*\n"
        f"- Совершили покупку: *{purchased_count}*\n"
        f"- Получено бонусов: *{bonus_days} дней*"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Поделиться с другом", url=f"https://t.me/share/url?url={referral_link}&text=Привет! Попробуй этот быстрый и удобный VPN-сервис.")]])
    await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню помощи."""
    text = "💬 **Центр помощи**\n\nЗдесь вы можете найти инструкции по установке или связаться с нашей поддержкой."
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Инструкции по установке", callback_data="show_instructions")],
        [InlineKeyboardButton("👨‍💻 Написать в поддержку", url=f"https://t.me/{SUPPORT_USERNAME}")]
    ])
    await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

# --- АДМИН-ПАНЕЛЬ ---

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    await update.message.reply_text("Панель администратора:", reply_markup=admin_keyboard)

async def grant_days_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS: return
    
    try:
        # Формат: /grant user_id days
        _, user_id_str, days_str = update.message.text.split()
        target_user_id = int(user_id_str)
        days_to_add = int(days_str)
        
        logger.info(f"Администратор {user.id} инициировал ручное начисление {days_to_add} дней для user_id={target_user_id}.")
        await update.message.reply_text(f"Начинаю начисление {days_to_add} дней для пользователя {target_user_id}...")
        
        # Функция внутри уже имеет нужные await
        await grant_subscription(context.application, target_user_id, days_to_add, is_manual=True)
        
        await update.message.reply_text(f"✅ Успешно начислено {days_to_add} дней пользователю {target_user_id}.")

    except ValueError:
        await update.message.reply_text("Неверный формат. Используйте: `/grant <user_id> <days>`")
    except Exception as e:
        logger.error(f"Ошибка при ручном начислении дней: {e}", exc_info=True)
        await update.message.reply_text(f"❗️ Произошла ошибка: {e}")

# --- РАССЫЛКА (ConversationHandler) ---

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало диалога о рассылке."""
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Пришлите сообщение, которое нужно разослать всем пользователям. Вы можете использовать Markdown-разметку.")
    return BROADCAST_MESSAGE

async def broadcast_get_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение сообщения для рассылки."""
    context.user_data['broadcast_message'] = update.message
    # Получаем общее количество пользователей для статистики
    all_users = await get_all_user_ids() # AWAIT
    user_count = len(all_users)
    
    keyboard = [[
        InlineKeyboardButton("✅ Начать рассылку", callback_data="broadcast_confirm_yes"),
        InlineKeyboardButton("❌ Отмена", callback_data="broadcast_confirm_no")
    ]]
    
    await update.message.reply_text(
        f"Вы собираетесь отправить это сообщение. Всего пользователей: {user_count}.\n\nНачать рассылку?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BROADCAST_CONFIRM

async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение и запуск рассылки."""
    query = update.callback_query
    await query.answer()

    if query.data == "broadcast_confirm_no":
        await query.edit_message_text("Рассылка отменена.")
        context.user_data.clear()
        return ConversationHandler.END

    await query.edit_message_text("⏳ Начинаю рассылку... Это может занять время.")
    
    message_to_send = context.user_data['broadcast_message']
    user_ids = await get_all_user_ids() # AWAIT
    
    success_count = 0
    fail_count = 0
    
    for user_id in user_ids:
        try:
            await message_to_send.copy(chat_id=user_id)
            success_count += 1
        except (Forbidden, BadRequest):
            fail_count += 1
        await asyncio.sleep(0.05) # Небольшая задержка, чтобы не словить флуд-контроль

    summary_text = f"✅ Рассылка завершена!\n\n- Успешно отправлено: {success_count}\n- Не удалось доставить (блок/удален): {fail_count}"
    await context.bot.send_message(chat_id=query.from_user.id, text=summary_text)
    
    context.user_data.clear()
    return ConversationHandler.END

async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена диалога рассылки."""
    await update.message.reply_text("Действие отменено.")
    context.user_data.clear()
    return ConversationHandler.END

# --- ОБРАБОТЧИК КНОПОК ---

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    # --- Обработка Админских кнопок ---
    if user_id in ADMIN_IDS:
        if data == 'admin_stats':
            await query.answer()
            stats = await get_stats() # AWAIT
            await query.edit_message_text(
                f"📊 **Статистика бота**\n\n"
                f"- Всего пользователей: `{stats['total_users']}`\n"
                f"- Активных подписок: `{stats['active_subscriptions']}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="admin_back")]])
            )
            return

        if data == 'admin_view_logs':
            await query.answer()
            if os.path.exists(LOG_FILE_PATH):
                await query.message.reply_document(document=open(LOG_FILE_PATH, 'rb'), filename='bot.log')
            else:
                await query.message.reply_text("Файл логов не найден.")
            return

        if data == 'admin_back':
            await query.edit_message_text("Панель администратора:", reply_markup=admin_keyboard)
            return
            
        # 'admin_broadcast' обрабатывается в ConversationHandler

    # --- Хелпер для выполнения действия после соглашения с правилами ---
    async def proceed_with_action(action: str):
        if action == "get_trial":
            if await has_used_trial(user_id): # AWAIT
                await query.answer("Вы уже использовали тестовый период.", show_alert=True)
                return

            await query.edit_message_text("⏳ Активируем ваш тестовый доступ, пожалуйста, подождите...")
            await grant_subscription(context.application, user_id, 3, is_trial=True)
            # grant_subscription сам отправит сообщение

        elif action in TARIFFS:
            if not YOOKASSA_ENABLED:
                await query.answer("🚧 Система оплаты временно недоступна.", show_alert=True)
                return
            
            tariff_info = TARIFFS[action]
            description = f"{tariff_info['description']} (ID: {user_id})"
            
            # Создаем платеж (без обращения к БД, т.к. Yookassa SDK сам по себе)
            payment = Payment.create({
                "amount": {"value": f"{tariff_info['price']:.2f}", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": f"https://t.me/{(await context.bot.get_me()).username}"},
                "capture": True,
                "description": description,
                "metadata": {'user_id': user_id, 'tariff_callback': action}
            }, uuid.uuid4())
            
            payment_markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Оплатить", url=payment.confirmation.confirmation_url)]])
            
            await query.edit_message_text(
                f"Вы выбрали: *{tariff_info['description']}*.\n"
                f"Сумма к оплате: *{tariff_info['price']} ₽*.\n\n"
                f"Нажмите кнопку ниже для перехода к оплате. Доступ активируется автоматически после успешного платежа.",
                reply_markup=payment_markup,
                parse_mode=ParseMode.MARKDOWN
            )

    # --- Обработка Пользовательских кнопок ---
    
    # 1. Проверка на согласие с правилами для действий покупки/триала
    actions_requiring_agreement = ["get_trial"] + list(TARIFFS.keys())
    
    if data in actions_requiring_agreement:
        if TERMS_URL and not await has_agreed_to_terms(user_id): # AWAIT
            text = "Пожалуйста, ознакомьтесь с условиями использования сервиса и подтвердите свое согласие."
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("📖 Ознакомиться с условиями", url=TERMS_URL)],
                [InlineKeyboardButton("✅ Я согласен и продолжаю", callback_data=f"agree_terms:{data}")]
            ])
            await query.edit_message_text(text, reply_markup=markup)
        else:
            await query.answer()
            await proceed_with_action(data)
        return

    # 2. Обработка нажатия "Я согласен"
    if data.startswith("agree_terms:"):
        original_action = data.split(":", 1)[1]
        await mark_terms_as_agreed(user_id) # AWAIT
        await query.answer("Согласие принято!")
        await proceed_with_action(original_action)
        return

    # 3. Навигация
    if data == "go_to_subscription":
        await query.message.delete()
        await subscription_handler(update, context)
        return

    if data == "show_instructions":
        text = "📖 **Инструкция по установке**\n\nДля подключения мы рекомендуем использовать приложение Happ. Инструкция по настройке доступна по кнопке ниже."
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Открыть инструкцию", url=SET_URL)],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_vpn")]
        ])
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        return

    if data == "back_to_vpn" or data == "back_to_vpn_from_qr":
        # Если сообщение с картинкой, удаляем его и шлем новое меню, иначе редактируем
        if data == "back_to_vpn_from_qr":
            await query.message.delete()
            await my_vpn_handler(update, context)
        else:
            await my_vpn_handler(update, context)
        return

    # 4. Показ QR-кода
    if data == "show_qr_remna":
        await query.answer("Генерирую QR-код...")
        try:
            username_in_panel = f"tg_{user_id}"
            async with RemnaAsyncManager(REMNAWAVE_PANEL_URL, REMNAWAVE_API_TOKEN) as mgr:
                user_data = await mgr.find_user_by_username(username_in_panel)
                if not user_data or not user_data.get("subscriptionUrl"):
                    await query.answer("Ошибка: не удалось найти вашу подписку.", show_alert=True)
                    return
                sub_url = user_data.get("subscriptionUrl")

            qr = qrcode.QRCode(border=1)
            qr.add_data(sub_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            buffer = io.BytesIO()
            img.save(buffer, 'PNG')
            buffer.seek(0)
            
            await query.message.reply_photo(
                photo=buffer,
                caption="📲 Отсканируйте этот QR-код в вашем VPN-приложении для быстрой настройки.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_vpn_from_qr")]])
            )
            # Удаляем старое текстовое сообщение меню, чтобы не засорять чат
            await query.message.delete()
            
        except Exception as e:
            logger.error(f"Ошибка при генерации QR-кода для {user_id}: {e}")
            await query.answer("Произошла ошибка при создании QR-кода.", show_alert=True)
        return

    # Если ничего не подошло
    await query.answer("Неизвестная команда")


# --- ВЕБХУК ЮKASSA ---

async def yookassa_webhook_handler(request: web.Request):
    application = request.app['bot_app']
    try:
        data = await request.json()
        event = data.get('event')
        logger.info(f"Получен вебхук от ЮKassa: {event}")
        
        if event == 'payment.succeeded':
            payment_object = data.get('object', {})
            payment_id = payment_object.get('id')
            metadata = payment_object.get('metadata', {})
            user_id = metadata.get('user_id')
            tariff_callback = metadata.get('tariff_callback')
            amount = payment_object.get('amount', {}).get('value')
            
            if not all([payment_id, user_id, tariff_callback, tariff_callback in TARIFFS]):
                logger.error(f"Некорректные метаданные в вебхуке: {metadata}")
                return web.Response(status=400)
            
            logger.info(f"Успешная оплата: payment_id={payment_id}, user_id={user_id}, tariff='{tariff_callback}', amount={amount}")
            
            # 1. Сохраняем платеж в БД (чтобы избежать дублей)
            try:
                await add_payment(payment_id, int(user_id), float(amount), tariff_callback) # AWAIT
            except Exception as e:
                logger.warning(f"Ошибка сохранения платежа (возможно дубль): {e}")

            # 2. Запускаем обработку (выдачу)
            asyncio.create_task(process_payment(application, payment_id, int(user_id), tariff_callback))
            
    except Exception as e:
        error_message = f"❗️ Ошибка в обработчике вебхука ЮKassa: {e}"
        logger.critical(error_message, exc_info=True)
        return web.Response(status=500)
        
    return web.Response(status=200)

async def scheduler_wrapper(application: Application):
    """Обертка для запуска планировщика уведомлений."""
    logger.info("SCHEDULER: Служба уведомлений запущена.")
    while True:
        try:
            await run_notifications(application.bot)
        except Exception as e:
            logger.error(f"SCHEDULER: Ошибка в цикле планировщика: {e}")
        await asyncio.sleep(3600) # Проверка раз в час

# --- ЗАПУСК БОТА ---

async def main():
    if not BOT_TOKEN:
        logger.critical("Критическая ошибка: не установлен BOT_TOKEN!")
        return

    # Инициализация БД
    await initialize_db() # AWAIT
    
    # Инициализация бота
    rate_limiter = AIORateLimiter()
    application = Application.builder().token(BOT_TOKEN).rate_limiter(rate_limiter).build()

    # Восстановление незавершенных платежей
    pending_payments = await get_pending_payments() # AWAIT
    if pending_payments:
        logger.info(f"Обнаружено {len(pending_payments)} незавершенных платежей. Запуск обработки...")
        for payment_id, user_id, tariff in pending_payments:
            asyncio.create_task(process_payment(application, payment_id, user_id, tariff))

    # --- Настройка Хендлеров ---
    
    # 1. ConversationHandler для рассылки
    broadcast_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_start, pattern='^admin_broadcast$')],
        states={
            BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_get_message)],
            BROADCAST_CONFIRM: [CallbackQueryHandler(broadcast_confirm, pattern='^broadcast_confirm_.*$')]
        },
        fallbacks=[CommandHandler('cancel', broadcast_cancel)],
        per_message=False
    )
    application.add_handler(broadcast_handler)

    # 2. Команды
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('admin', admin_command))
    application.add_handler(CommandHandler('grant', grant_days_command))

    # 3. Текстовое меню
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🔐 Мой VPN$'), my_vpn_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^💎 Подписка$'), subscription_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^🎁 Пригласить друга$'), referral_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex('^💬 Помощь$'), help_handler))

    # 4. Колбэки
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    # В функции main() добавьте:
    application.add_error_handler(error_handler)

    # --- Настройка Веб-сервера (Webhooks) ---
    webhook_app = web.Application()
    webhook_app['bot_app'] = application
    webhook_app.router.add_post("/yookassa_webhook", yookassa_webhook_handler)
    
    runner = web.AppRunner(webhook_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT)

    try:
        await application.initialize()
        await application.start()
        
        # Запускаем планировщик
        asyncio.create_task(scheduler_wrapper(application))
        
        # Запускаем Polling
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("BOT: Polling запущен...")

        if YOOKASSA_ENABLED:
            await site.start()
            logger.info(f"WEBHOOK: Сервер запущен на порту {WEBHOOK_PORT}...")

        await asyncio.Event().wait()

    finally:
        logger.info("Остановка сервисов...")
        if application.updater and application.updater.running:
            await application.updater.stop()
        if application.running:
            await application.stop()
        await application.shutdown()
        await runner.cleanup()
        logger.info("Все сервисы успешно остановлены.")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")