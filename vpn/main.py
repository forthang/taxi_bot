#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ConversationHandler
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from aiohttp import web
from yookassa import Configuration, Payment

# Локальные импорты
from config import config, TARIFFS, load_tariffs_from_db
from database import initialize_db, has_used_trial, add_payment
from handlers import (
    start_handler, my_vpn_handler, subscription_handler, 
    referral_handler, help_handler, show_qr_handler, show_instructions_handler
)
from services import grant_subscription, process_payment
from admin import (
    AdminPanel, broadcast_start, broadcast_get_message, broadcast_confirm,
    grant_subscription_start, grant_subscription_get_user, grant_subscription_get_days,
    find_user_start, find_user_get_info, conversation_cancel,
    edit_tariff_start, edit_tariff_set_price,
    BROADCAST_MESSAGE, BROADCAST_CONFIRM, GRANT_USER_ID, GRANT_DAYS, USER_INFO_ID, SET_PRICE_VALUE
)
from scheduler import run_notifications, send_logs_to_admins

# Настройка логирования
os.makedirs(config.LOG_DIR, exist_ok=True)
log_file = os.path.join(config.LOG_DIR, 'bot.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(log_file, maxBytes=10485760, backupCount=5),
        logging.StreamHandler()
    ]
)

# Отключаем лишние логи
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Конфигурация YooKassa
if config.yookassa_enabled:
    Configuration.account_id = config.YOOKASSA_SHOP_ID
    Configuration.secret_key = config.YOOKASSA_SECRET_KEY
    logger.info("YooKassa настроена")
else:
    logger.warning("YooKassa не настроена")

async def error_handler(update: object, context):
    """Глобальный обработчик ошибок"""
    logger.error("Ошибка в боте:", exc_info=context.error)
    
    if config.ADMIN_IDS and isinstance(update, Update):
        try:
            error_msg = f"🔥 **Ошибка в боте**\n\n`{str(context.error)[:500]}`"
            for admin_id in config.ADMIN_IDS:
                try:
                    await context.bot.send_message(admin_id, error_msg, parse_mode=ParseMode.MARKDOWN)
                except:
                    pass
        except:
            pass

async def button_callback_handler(update: Update, context):
    """Обработчик всех callback кнопок"""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    # Админские команды
    if AdminPanel.is_admin(user_id):
        if data == "admin_main":
            await query.edit_message_text("🔧 **Панель администратора**", 
                                        reply_markup=AdminPanel.get_main_keyboard(), 
                                        parse_mode=ParseMode.MARKDOWN)
            return
        elif data == "admin_stats":
            await AdminPanel.show_stats(update, context)
            return
        elif data == "admin_users":
            await query.edit_message_text("👥 **Управление пользователями**", 
                                        reply_markup=AdminPanel.get_users_keyboard(), 
                                        parse_mode=ParseMode.MARKDOWN)
            return
        elif data == "admin_payments":
            await query.edit_message_text("💰 **Управление платежами**", 
                                        reply_markup=AdminPanel.get_payments_keyboard(), 
                                        parse_mode=ParseMode.MARKDOWN)
            return
        elif data == "admin_system":
            await query.edit_message_text("⚙️ **Системные функции**", 
                                        reply_markup=AdminPanel.get_system_keyboard(), 
                                        parse_mode=ParseMode.MARKDOWN)
            return
        elif data == "admin_logs":
            await AdminPanel.show_logs(update, context)
            return
        elif data == "admin_pending_payments":
            await AdminPanel.show_pending_payments(update, context)
            return
        elif data == "admin_completed_payments":
            await AdminPanel.show_completed_payments(update, context)
            return
        elif data == "admin_payment_stats":
            await AdminPanel.show_payment_stats(update, context)
            return
        elif data == "admin_tariffs":
            await AdminPanel.show_tariffs(update, context)
            return

    # Пользовательские команды
    if data == "get_trial":
        if await has_used_trial(user_id):
            await query.answer("Вы уже использовали тестовый период!", show_alert=True)
        else:
            await query.edit_message_text("⏳ Активация тестового периода...")
            await grant_subscription(context.application, user_id, 3, is_trial=True)
        return

    elif data in TARIFFS:
        if not config.yookassa_enabled:
            await query.answer("Оплата временно недоступна", show_alert=True)
            return
        
        tariff = TARIFFS[data]
        payment_data = {
            "amount": {"value": f"{tariff['price']:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": f"https://t.me/{(await context.bot.get_me()).username}"},
            "capture": True,
            "description": f"VPN {tariff['days']} дн. (ID: {user_id})",
            "metadata": {'user_id': str(user_id), 'tariff_callback': data},
            "receipt": {
                "customer": {"email": f"user{user_id}@vpnbot.local"},
                "items": [{
                    "description": tariff['description'],
                    "quantity": "1.00",
                    "amount": {"value": f"{tariff['price']:.2f}", "currency": "RUB"},
                    "vat_code": 4,
                    "payment_mode": "full_payment",
                    "payment_subject": "service"
                }]
            }
        }
        
        try:
            payment = Payment.create(payment_data, uuid.uuid4())
            await add_payment(payment.id, user_id, tariff['price'], data)
            
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("💳 Оплатить", url=payment.confirmation.confirmation_url)
            ]])
            await query.edit_message_text(
                f"💳 **К оплате: {tariff['price']}₽**\n\n{tariff['description']}", 
                reply_markup=markup, 
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Ошибка создания платежа: {e}")
            await query.answer("Ошибка создания платежа", show_alert=True)
        return

    elif data == "show_qr_remna":
        await show_qr_handler(update, context)
        return
    elif data == "show_instructions":
        await show_instructions_handler(update, context)
        return
    elif data == "go_to_subscription":
        await subscription_handler(update, context)
        return
    elif data == "back_to_vpn":
        await my_vpn_handler(update, context)
        return

    await query.answer()

async def admin_command(update: Update, context):
    """Команда /admin"""
    if AdminPanel.is_admin(update.effective_user.id):
        await update.message.reply_text(
            "🔧 **Панель администратора**", 
            reply_markup=AdminPanel.get_main_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("❌ Доступ запрещен")

async def grant_command(update: Update, context):
    """Команда /grant user_id days"""
    if not AdminPanel.is_admin(update.effective_user.id):
        return
    
    try:
        _, user_id, days = update.message.text.split()
        await grant_subscription(context.application, int(user_id), int(days), is_manual=True)
        await update.message.reply_text("✅ Подписка выдана")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# Webhook для YooKassa
async def yookassa_webhook_handler(request: web.Request):
    """Обработчик webhook от YooKassa"""
    application = request.app['bot_app']
    
    try:
        body = await request.read()
        data = json.loads(body.decode('utf-8'))
        logger.info(f"WEBHOOK: {data.get('event', 'unknown')}")
        
        if data.get('event') == 'payment.succeeded':
            obj = data.get('object', {})
            payment_id = obj.get('id')
            metadata = obj.get('metadata', {})
            
            user_id = metadata.get('user_id')
            tariff = metadata.get('tariff_callback')
            
            if payment_id and user_id and tariff:
                asyncio.create_task(process_payment(application, payment_id, int(user_id), tariff))
            else:
                logger.error("WEBHOOK: Неполные данные в платеже")
                
    except Exception as e:
        logger.error(f"WEBHOOK: Ошибка обработки: {e}")
        return web.Response(status=500)
        
    return web.Response(status=200)

async def health_check_handler(request: web.Request):
    """Health check endpoint"""
    return web.Response(text="OK", status=200)

async def scheduler_task(application: Application):
    """Фоновая задача планировщика"""
    await asyncio.sleep(10)  # Ждем запуска бота
    while True:
        try:
            await run_notifications(application.bot)
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        await asyncio.sleep(3600)  # Каждый час

async def daily_logs_task(application: Application):
    """Ежедневная отправка логов админам"""
    await asyncio.sleep(60)  # Ждем запуска бота
    while True:
        try:
            now = datetime.now()
            # Отправляем в 00:00
            next_run = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run = next_run.replace(day=now.day + 1)
            wait_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            await send_logs_to_admins(application.bot)
        except Exception as e:
            logger.error(f"Daily logs task error: {e}")
            await asyncio.sleep(3600)  # При ошибке ждем час

async def main():
    """Главная функция"""
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN не найден!")
        return

    # Инициализация БД
    await initialize_db()
    
    # Загрузка тарифов из БД
    await load_tariffs_from_db()
    
    # Создание приложения
    app = Application.builder().token(config.BOT_TOKEN).build()
    
    # Conversation handlers для админки
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_start, pattern='^admin_broadcast$')],
        states={
            BROADCAST_MESSAGE: [MessageHandler(filters.TEXT, broadcast_get_message)],
            BROADCAST_CONFIRM: [CallbackQueryHandler(broadcast_confirm, pattern='^broadcast_')]
        },
        fallbacks=[CommandHandler('cancel', conversation_cancel)]
    )
    
    grant_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(grant_subscription_start, pattern='^admin_grant_sub$')],
        states={
            GRANT_USER_ID: [MessageHandler(filters.TEXT, grant_subscription_get_user)],
            GRANT_DAYS: [MessageHandler(filters.TEXT, grant_subscription_get_days)]
        },
        fallbacks=[CommandHandler('cancel', conversation_cancel)]
    )
    
    find_user_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(find_user_start, pattern='^admin_find_user$')],
        states={
            USER_INFO_ID: [MessageHandler(filters.TEXT, find_user_get_info)]
        },
        fallbacks=[CommandHandler('cancel', conversation_cancel)]
    )
    
    tariff_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_tariff_start, pattern='^admin_edit_tariff_')],
        states={
            SET_PRICE_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_tariff_set_price)]
        },
        fallbacks=[CommandHandler('cancel', conversation_cancel)]
    )
    
    # Регистрация обработчиков
    app.add_handler(broadcast_conv)
    app.add_handler(grant_conv)
    app.add_handler(find_user_conv)
    app.add_handler(tariff_conv)
    app.add_handler(CommandHandler('start', start_handler))
    app.add_handler(CommandHandler('admin', admin_command))
    app.add_handler(CommandHandler('grant', grant_command))
    app.add_handler(MessageHandler(filters.Regex('^🔐'), my_vpn_handler))
    app.add_handler(MessageHandler(filters.Regex('^💎'), subscription_handler))
    app.add_handler(MessageHandler(filters.Regex('^🎁'), referral_handler))
    app.add_handler(MessageHandler(filters.Regex('^💬'), help_handler))
    app.add_handler(CallbackQueryHandler(button_callback_handler))
    app.add_error_handler(error_handler)

    # Webhook сервер
    webhook_app = web.Application()
    webhook_app['bot_app'] = app
    webhook_app.router.add_post("/yookassa_webhook", yookassa_webhook_handler)
    webhook_app.router.add_get("/health", health_check_handler)
    
    runner = web.AppRunner(webhook_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', config.WEBHOOK_PORT)
    
    # Запуск
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await site.start()
    
    # Запуск планировщика
    asyncio.create_task(scheduler_task(app))
    asyncio.create_task(daily_logs_task(app))
    
    logger.info(f"🚀 Бот запущен! Webhook порт: {config.WEBHOOK_PORT}")
    logger.info(f"📊 Админов: {len(config.ADMIN_IDS)}")
    logger.info(f"🔧 Remnawave: {'✅' if config.remnawave_enabled else '❌'}")
    logger.info(f"💳 YooKassa: {'✅' if config.yookassa_enabled else '❌'}")
    
    # Ожидание
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
