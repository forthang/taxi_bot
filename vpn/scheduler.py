# /bot/scheduler.py

import asyncio
import logging
from datetime import datetime, timezone
from telegram import Bot
from telegram.error import Forbidden, BadRequest
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import os

from database import (
    get_all_active_users_for_sync, sync_subscription_date,
    get_subscriptions_to_pre_notify, mark_pre_notification_as_sent,
    get_subscriptions_to_notify, mark_subscription_as_expired
)
from api import RemnaAsyncManager, RemnaAPIError

logger = logging.getLogger(__name__)

PRE_EXPIRATION_TEXT = (
    "⏳ Ваша подписка на Granat VPN истекает в течение 24 часов.\n\n"
    "Чтобы не терять доступ к быстрому и безопасному интернету, "
    "рекомендуем продлить ее прямо сейчас."
)

EXPIRATION_TEXT = (
    "🚫 Ваша подписка на Granat VPN истекла.\n\n"
    "Доступ к серверам приостановлен. Чтобы продолжить пользоваться VPN, "
    "пожалуйста, оформите новую подписку в разделе «💎 Подписка»."
)

async def run_notifications(bot: Bot):
    """
    Задача планировщика:
    1. Синхронизирует даты подписок с панелью Remnawave.
    2. Отправляет уведомления об окончании подписки.
    """
    logger.info("SCHEDULER: Запуск периодической задачи.")
    
    # Получаем переменные окружения
    remnawave_panel_url = os.getenv("REMNAWAVE_PANEL_URL")
    remnawave_api_token = os.getenv("REMNAWAVE_API_TOKEN")

    if not all([remnawave_panel_url, remnawave_api_token]):
        logger.warning("SCHEDULER: Пропуск выполнения, так как переменные Remnawave не настроены.")
        return

    current_time = datetime.now(timezone.utc)

    # --- ШАГ 1: Синхронизация дат ---
    logger.info("SCHEDULER: Начало синхронизации дат подписок с панелью.")
    try:
        # ДОБАВЛЕН AWAIT
        active_users_in_db = await get_all_active_users_for_sync()
        logger.info(f"SCHEDULER_SYNC: Найдено {len(active_users_in_db)} активных пользователей в локальной БД для проверки.")
        
        if active_users_in_db:
            async with RemnaAsyncManager(remnawave_panel_url, remnawave_api_token) as mgr:
                for (user_id,) in active_users_in_db:
                    username = f"tg_{user_id}"
                    try:
                        user_data = await mgr.find_user_by_username(username)
                        if user_data and user_data.get("expireAt"):
                            expire_str = user_data["expireAt"]
                            # Обработка даты
                            try:
                                panel_date = datetime.fromisoformat(expire_str.replace("Z", "+00:00"))
                            except ValueError:
                                # Fallback если формат другой
                                panel_date = datetime.strptime(expire_str.split('.')[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)

                            # ДОБАВЛЕН AWAIT
                            await sync_subscription_date(user_id, panel_date, current_time)
                        else:
                            logger.warning(f"SCHEDULER_SYNC: Пользователь {username} не найден в панели, но активен в БД.")
                    except RemnaAPIError as e:
                        logger.error(f"SCHEDULER_SYNC: Ошибка API при получении данных для {username}: {e}")
                    
                    await asyncio.sleep(0.1) # Пауза, чтобы не перегружать API
    except Exception as e:
        logger.error(f"SCHEDULER_SYNC: Критическая ошибка на этапе синхронизации: {e}", exc_info=True)
    logger.info("SCHEDULER_SYNC: Этап синхронизации завершен.")

    # --- ШАГ 2: Отправка уведомлений ---
    logger.info("SCHEDULER: Начало отправки уведомлений.")
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Продлить подписку", callback_data="go_to_subscription")]])

    # Уведомления за 24 часа
    try:
        # ДОБАВЛЕН AWAIT
        users_to_pre_notify = await get_subscriptions_to_pre_notify()
        logger.info(f"SCHEDULER_NOTIFY: Найдено {len(users_to_pre_notify)} пользователей для предварительного уведомления.")
        for (user_id,) in users_to_pre_notify:
            try:
                await bot.send_message(chat_id=user_id, text=PRE_EXPIRATION_TEXT, reply_markup=keyboard)
                # ДОБАВЛЕН AWAIT
                await mark_pre_notification_as_sent(user_id)
                logger.info(f"SCHEDULER_NOTIFY: Отправлено предварительное уведомление пользователю {user_id}.")
            except (Forbidden, BadRequest) as e:
                logger.warning(f"SCHEDULER_NOTIFY: Не удалось отправить уведомление user_id {user_id}: {e}")
            await asyncio.sleep(0.1)
    except Exception as e:
        logger.error(f"SCHEDULER_NOTIFY: Критическая ошибка при отправке предварительных уведомлений: {e}", exc_info=True)

    # Уведомления об истечении
    try:
        # ДОБАВЛЕН AWAIT
        users_to_notify = await get_subscriptions_to_notify()
        logger.info(f"SCHEDULER_NOTIFY: Найдено {len(users_to_notify)} пользователей для уведомления об истечении подписки.")
        for (user_id,) in users_to_notify:
            try:
                await bot.send_message(chat_id=user_id, text=EXPIRATION_TEXT, reply_markup=keyboard)
                # ДОБАВЛЕН AWAIT
                await mark_subscription_as_expired(user_id)
                logger.info(f"SCHEDULER_NOTIFY: Отправлено уведомление об истечении подписки пользователю {user_id}.")
            except (Forbidden, BadRequest) as e:
                logger.warning(f"SCHEDULER_NOTIFY: Не удалось отправить уведомление об истечении подписки user_id {user_id}: {e}")
            await asyncio.sleep(0.1)
    except Exception as e:
        logger.error(f"SCHEDULER_NOTIFY: Критическая ошибка при отправке уведомлений об истечении: {e}", exc_info=True)
    
    logger.info("SCHEDULER: Периодическая задача завершена.")