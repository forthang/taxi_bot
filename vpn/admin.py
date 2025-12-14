import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden

from database import (
    get_stats, get_all_user_ids, get_payment_info, get_pending_payments,
    get_active_subscription, update_or_create_subscription
)
from config import config

logger = logging.getLogger(__name__)

# Состояния для админки
BROADCAST_MESSAGE, BROADCAST_CONFIRM = range(2)
GRANT_USER_ID, GRANT_DAYS = range(2, 4)
USER_INFO_ID = 4

class AdminPanel:
    @staticmethod
    def is_admin(user_id: int) -> bool:
        return user_id in config.ADMIN_IDS

    @staticmethod
    def get_main_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 Управление пользователями", callback_data="admin_users")],
            [InlineKeyboardButton("💰 Платежи", callback_data="admin_payments")],
            [InlineKeyboardButton("📄 Логи", callback_data="admin_logs")],
            [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton("⚙️ Система", callback_data="admin_system")]
        ])

    @staticmethod
    def get_users_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Найти пользователя", callback_data="admin_find_user")],
            [InlineKeyboardButton("🎁 Выдать подписку", callback_data="admin_grant_sub")],
            [InlineKeyboardButton("📋 Список активных", callback_data="admin_active_users")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_main")]
        ])

    @staticmethod
    def get_payments_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⏳ Ожидающие платежи", callback_data="admin_pending_payments")],
            [InlineKeyboardButton("📈 Статистика платежей", callback_data="admin_payment_stats")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_main")]
        ])

    @staticmethod
    def get_system_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Перезапуск бота", callback_data="admin_restart")],
            [InlineKeyboardButton("🧹 Очистить логи", callback_data="admin_clear_logs")],
            [InlineKeyboardButton("💾 Бэкап БД", callback_data="admin_backup_db")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_main")]
        ])

    @staticmethod
    async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        try:
            stats = await get_stats()
            
            # Дополнительная статистика
            pending_payments = await get_pending_payments()
            
            text = f"""📊 **Статистика бота**

👥 Всего пользователей: `{stats['total_users']}`
✅ Активных подписок: `{stats['active_subscriptions']}`
⏳ Ожидающих платежей: `{len(pending_payments)}`

🔧 Конфигурация:
• Remnawave: {'✅' if config.remnawave_enabled else '❌'}
• YooKassa: {'✅' if config.yookassa_enabled else '❌'}
• Админов: `{len(config.ADMIN_IDS)}`

⏰ Обновлено: `{datetime.now().strftime('%H:%M:%S')}`"""
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin_main")]
            ])
            
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            await query.edit_message_text("❌ Ошибка получения статистики", 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_main")]]))

    @staticmethod
    async def show_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        log_file = os.path.join(config.LOG_DIR, 'bot.log')
        
        if os.path.exists(log_file):
            try:
                await query.message.reply_document(
                    document=open(log_file, 'rb'),
                    filename=f'bot_logs_{datetime.now().strftime("%Y%m%d_%H%M")}.txt',
                    caption="📄 Логи бота"
                )
            except Exception as e:
                await query.edit_message_text(f"❌ Ошибка отправки логов: {e}")
        else:
            await query.edit_message_text("❌ Файл логов не найден")

    @staticmethod
    async def show_pending_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        try:
            pending = await get_pending_payments()
            
            if not pending:
                text = "✅ Нет ожидающих платежей"
            else:
                text = "⏳ **Ожидающие платежи:**\n\n"
                for payment_id, user_id, tariff in pending[:10]:  # Показываем только первые 10
                    text += f"• `{payment_id[:20]}...` - User: `{user_id}` - `{tariff}`\n"
                
                if len(pending) > 10:
                    text += f"\n... и еще {len(pending) - 10} платежей"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_pending_payments")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin_payments")]
            ])
            
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Ошибка получения платежей: {e}")
            await query.edit_message_text("❌ Ошибка получения данных о платежах")

# Обработчики для ConversationHandler
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📢 **Рассылка сообщений**\n\nОтправьте текст для рассылки всем пользователям:",
        parse_mode=ParseMode.MARKDOWN
    )
    return BROADCAST_MESSAGE

async def broadcast_get_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['broadcast_message'] = update.message
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Отправить", callback_data="broadcast_confirm")],
        [InlineKeyboardButton("❌ Отменить", callback_data="broadcast_cancel")]
    ])
    
    await update.message.reply_text(
        "📢 **Подтверждение рассылки**\n\nВы уверены, что хотите разослать это сообщение всем пользователям?",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )
    return BROADCAST_CONFIRM

async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "broadcast_confirm":
        await query.edit_message_text("📤 Рассылка запущена...")
        
        message = context.user_data.get('broadcast_message')
        if not message:
            await query.edit_message_text("❌ Сообщение не найдено")
            return ConversationHandler.END
        
        user_ids = await get_all_user_ids()
        sent = 0
        failed = 0
        
        for user_id in user_ids:
            try:
                await message.copy(chat_id=user_id)
                sent += 1
                await asyncio.sleep(0.05)  # Защита от лимитов
            except (BadRequest, Forbidden):
                failed += 1
            except Exception as e:
                logger.error(f"Ошибка рассылки для {user_id}: {e}")
                failed += 1
        
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=f"✅ **Рассылка завершена**\n\n📤 Отправлено: `{sent}`\n❌ Ошибок: `{failed}`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await query.edit_message_text("❌ Рассылка отменена")
    
    context.user_data.clear()
    return ConversationHandler.END

async def grant_subscription_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🎁 **Выдача подписки**\n\nВведите ID пользователя:",
        parse_mode=ParseMode.MARKDOWN
    )
    return GRANT_USER_ID

async def grant_subscription_get_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text.strip())
        context.user_data['grant_user_id'] = user_id
        
        # Проверяем существование пользователя
        subscription = await get_active_subscription(user_id)
        status = "✅ Активна" if subscription else "❌ Неактивна"
        
        await update.message.reply_text(
            f"👤 **Пользователь:** `{user_id}`\n📋 **Подписка:** {status}\n\n🕐 Введите количество дней для выдачи:",
            parse_mode=ParseMode.MARKDOWN
        )
        return GRANT_DAYS
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Введите число:")
        return GRANT_USER_ID

async def grant_subscription_get_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text.strip())
        user_id = context.user_data.get('grant_user_id')
        
        if not user_id or days <= 0:
            raise ValueError()
        
        # Выдаем подписку
        from main import grant_subscription
        await grant_subscription(context.application, user_id, days, is_manual=True)
        
        await update.message.reply_text(
            f"✅ **Подписка выдана**\n\n👤 Пользователь: `{user_id}`\n🕐 Дней: `{days}`",
            parse_mode=ParseMode.MARKDOWN
        )
        
        context.user_data.clear()
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Неверное количество дней. Введите положительное число:")
        return GRANT_DAYS
    except Exception as e:
        logger.error(f"Ошибка выдачи подписки: {e}")
        await update.message.reply_text(f"❌ Ошибка выдачи подписки: {e}")
        context.user_data.clear()
        return ConversationHandler.END

async def find_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔍 **Поиск пользователя**\n\nВведите ID пользователя для получения информации:",
        parse_mode=ParseMode.MARKDOWN
    )
    return USER_INFO_ID

async def find_user_get_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text.strip())
        
        # Получаем информацию о пользователе
        subscription = await get_active_subscription(user_id)
        
        if subscription:
            vless_uuid, end_date = subscription
            text = f"""👤 **Информация о пользователе**

🆔 ID: `{user_id}`
✅ Статус: Активная подписка
🔑 UUID: `{vless_uuid}`
📅 До: `{end_date}`"""
        else:
            text = f"""👤 **Информация о пользователе**

🆔 ID: `{user_id}`
❌ Статус: Нет активной подписки"""
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 Выдать подписку", callback_data="admin_grant_sub")],
            [InlineKeyboardButton("🔍 Найти другого", callback_data="admin_find_user")]
        ])
        
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Введите число:")
        return USER_INFO_ID
    except Exception as e:
        logger.error(f"Ошибка поиска пользователя: {e}")
        await update.message.reply_text(f"❌ Ошибка поиска: {e}")
        return ConversationHandler.END

async def conversation_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Операция отменена")
    return ConversationHandler.END
