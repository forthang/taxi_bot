import uuid
import io
import qrcode
import logging
from datetime import datetime, timezone, timedelta

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden

from database import (
    add_user, get_active_subscription, has_used_trial, 
    get_referral_program_stats, get_any_subscription,
    update_or_create_subscription, mark_trial_as_used,
    log_referral_purchase, ensure_user_exists
)
from api import RemnaAsyncManager, RemnaAPIError
from config import config, TARIFFS

logger = logging.getLogger(__name__)

# Клавиатуры
main_keyboard = ReplyKeyboardMarkup([
    ["🔐 Мой VPN", "💎 Подписка"],
    ["🎁 Пригласить друга", "💬 Помощь"]
], resize_keyboard=True)

def safe_parse_datetime(date_obj):
    if not date_obj:
        return datetime.now(timezone.utc)
    
    if isinstance(date_obj, datetime):
        return date_obj if date_obj.tzinfo else date_obj.replace(tzinfo=timezone.utc)

    try:
        clean_str = str(date_obj).split('+')[0].replace('T', ' ').split('.')[0].strip()
        dt = datetime.strptime(clean_str, '%Y-%m-%d %H:%M:%S')
        return dt.replace(tzinfo=timezone.utc)
    except Exception as e:
        logger.error(f"Date parse error: {e}")
        return datetime.now(timezone.utc)

def format_bytes(size: float) -> str:
    if not size: 
        return "0 GB"
    power = 2**30
    n = size / power
    if n < 0.01:
        return f"{size / (2**20):.0f} MB"
    return f"{n:.2f} GB"

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            except: 
                pass
        else: 
            source = payload
            
    await add_user(user.id, user.username, user.first_name, user.last_name, source=source, referrer_id=referrer_id)
    
    text = f"👋 Привет, {user.first_name or 'друг'}!\n\nЭто бот **Интернет Всегда** — твой быстрый и надежный доступ к любым сервисам ."
    await update.message.reply_text(text, reply_markup=main_keyboard, parse_mode=ParseMode.MARKDOWN)

async def my_vpn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id if query else update.effective_user.id
    chat_id = query.message.chat_id if query else update.effective_chat.id
    message_to_edit = query.message if query else None

    if query: 
        await query.answer()

    subscription = await get_active_subscription(user_id)
    
    if not subscription:
        text = "❌ **Подписка неактивна**\n\nОформите подписку или возьмите тест."
        buttons = []
        if not await has_used_trial(user_id):
            buttons.append([InlineKeyboardButton("🚀 Тест 3 дня", callback_data="get_trial")])
        buttons.append([InlineKeyboardButton("💎 Купить подписку", callback_data="go_to_subscription")])
        
        markup = InlineKeyboardMarkup(buttons)
        if message_to_edit:
            await message_to_edit.edit_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await context.bot.send_message(chat_id, text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        return

    _, end_date_raw = subscription
    end_date_formatted = safe_parse_datetime(end_date_raw).strftime('%d.%m.%Y')

    try:
        username_in_panel = f"tg_{user_id}"
        traffic_info = ""
        
        if config.remnawave_enabled:
            async with RemnaAsyncManager(config.REMNAWAVE_PANEL_URL, config.REMNAWAVE_API_TOKEN) as mgr:
                user_data = await mgr.find_user_by_username(username_in_panel)
                if not user_data or not user_data.get("subscriptionUrl"):
                    raise RemnaAPIError("Пользователь не найден в панели")
                
                sub_url = user_data.get("subscriptionUrl")
                used = user_data.get('trafficUsed', 0)
                limit = user_data.get('trafficLimit') or user_data.get('dataLimit') or 0
                traffic_info = f"📊 Трафик: {format_bytes(used)} / {format_bytes(limit) if limit else '∞'}"

            text = f"✅ **Подписка до {end_date_formatted}**\n{traffic_info}\n\nВаша ссылка:\n`{sub_url}`\n\nОбязательно прочтите инструкцию!"
            
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("📲 QR-код", callback_data="show_qr_remna")],
                [InlineKeyboardButton("📖 Инструкция", callback_data="show_instructions")]
            ])
        else:
            text = "❗️ VPN сервис временно недоступен"
            markup = None
            
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
    if query: 
        await query.answer()
    
    chat_id = query.message.chat_id if query else update.effective_chat.id
    user_id = query.from_user.id if query else update.effective_user.id

    buttons = []
    if not await has_used_trial(user_id):
        buttons.append([InlineKeyboardButton("🚀 Тест 3 дня", callback_data="get_trial")])

    for key, tariff in TARIFFS.items():
        buttons.append([InlineKeyboardButton(f"{tariff['description']} — {tariff['price']:.0f}₽", callback_data=key)])

    await context.bot.send_message(
        chat_id, 
        "💎 **Выберите тариф:**", 
        reply_markup=InlineKeyboardMarkup(buttons), 
        parse_mode=ParseMode.MARKDOWN
    )

async def referral_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    invited, purchased = await get_referral_program_stats(user_id)
    
    text = f"""🎁 **Реферальная программа**

Приглашено: {invited}
Купили: {purchased}

Ваша ссылка:
`{link}`"""
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("👨💻 Поддержка", url=f"https://t.me/{config.SUPPORT_USERNAME}")
    ]])
    await update.message.reply_text("💬 Если возникли вопросы:", reply_markup=markup)

async def show_qr_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("Генерация QR...")
    
    try:
        if not config.remnawave_enabled:
            await query.answer("VPN сервис недоступен", show_alert=True)
            return
            
        async with RemnaAsyncManager(config.REMNAWAVE_PANEL_URL, config.REMNAWAVE_API_TOKEN) as mgr:
            user_data = await mgr.find_user_by_username(f"tg_{user_id}")
            url = user_data.get("subscriptionUrl")
            
        qr = qrcode.make(url)
        buf = io.BytesIO()
        qr.save(buf, 'PNG')
        buf.seek(0)
        await query.message.reply_photo(buf, caption="📲 QR для подключения")
    except Exception as e:
        logger.error(f"Ошибка генерации QR: {e}")
        await query.answer("Ошибка генерации QR", show_alert=True)

async def show_instructions_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    text = f"📖 **Инструкция по подключению**\n\n{config.SET_URL}"
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_vpn")]])
    
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
