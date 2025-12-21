# /bot/scheduler.py

import asyncio
import logging
import os
import glob
from datetime import datetime, timezone
from telegram import Bot
from telegram.error import Forbidden, BadRequest
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from database import (
    get_all_active_users_for_sync, sync_subscription_date,
    get_subscriptions_to_pre_notify, mark_pre_notification_as_sent,
    get_subscriptions_to_notify, mark_subscription_as_expired
)
from api import RemnaAsyncManager, RemnaAPIError
from config import config

logger = logging.getLogger(__name__)

PRE_EXPIRATION_TEXT = (
    "⏳ Ваша подписка на internet vseGda истекает в течение 24 часов.\n\n"
    "Чтобы не терять доступ к быстрому и безопасному интернету, "
    "рекомендуем продлить ее прямо сейчас."
)

EXPIRATION_TEXT = (
    "🚫 Ваша подписка на internet vseGda истекла.\n\n"
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
        async with RemnaAsyncManager(remnawave_panel_url, remnawave_api_token) as mgr:
            # Получаем актуальных пользователей из API вместо БД
            all_users_response = await mgr.get_all_users_v2()
            all_users = all_users_response.get("users", [])
            logger.info(f"SCHEDULER_SYNC: Получено {len(all_users)} пользователей из API Remnawave.")
            
            for user_data in all_users:
                username = user_data.get("username", "")
                if not username.startswith("tg_"):
                    continue
                    
                try:
                    user_id = int(username.replace("tg_", ""))
                except ValueError:
                    continue
                
                expire_str = user_data.get("expireAt")
                if not expire_str:
                    continue
                    
                try:
                    panel_date = datetime.fromisoformat(expire_str.replace("Z", "+00:00"))
                except ValueError:
                    try:
                        panel_date = datetime.strptime(expire_str.split('.')[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                    except:
                        continue

                await sync_subscription_date(user_id, panel_date, current_time)
                await asyncio.sleep(0.05)
                
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
        users_to_notify = await get_subscriptions_to_notify()
        logger.info(f"SCHEDULER_NOTIFY: Найдено {len(users_to_notify)} пользователей для уведомления об истечении подписки.")
        for (user_id,) in users_to_notify:
            try:
                await bot.send_message(chat_id=user_id, text=EXPIRATION_TEXT, reply_markup=keyboard)
                await mark_subscription_as_expired(user_id)
                logger.info(f"SCHEDULER_NOTIFY: Отправлено уведомление об истечении подписки пользователю {user_id}.")
            except (Forbidden, BadRequest) as e:
                logger.warning(f"SCHEDULER_NOTIFY: Не удалось отправить уведомление об истечении подписки user_id {user_id}: {e}")
            await asyncio.sleep(0.1)
    except Exception as e:
        logger.error(f"SCHEDULER_NOTIFY: Критическая ошибка при отправке уведомлений об истечении: {e}", exc_info=True)
    
    logger.info("SCHEDULER: Периодическая задача завершена.")

async def send_logs_to_admins(bot: Bot):
    """Отправляет логи админам и удаляет их"""
    log_dir = config.LOG_DIR
    if not os.path.exists(log_dir):
        return
    
    log_files = glob.glob(os.path.join(log_dir, '*.log*'))
    if not log_files:
        return
    
    for admin_id in config.ADMIN_IDS:
        for log_file in log_files:
            try:
                if os.path.getsize(log_file) > 0:
                    with open(log_file, 'rb') as f:
                        await bot.send_document(
                            chat_id=admin_id,
                            document=f,
                            filename=f"logs_{datetime.now().strftime('%Y%m%d')}_{os.path.basename(log_file)}",
                            caption=f"📄 Логи за {datetime.now().strftime('%d.%m.%Y')}"
                        )
            except (Forbidden, BadRequest) as e:
                logger.warning(f"Не удалось отправить логи админу {admin_id}: {e}")
            except Exception as e:
                logger.error(f"Ошибка отправки логов: {e}")
    
    # Удаляем отправленные логи (кроме текущего)
    main_log = os.path.join(log_dir, 'bot.log')
    for log_file in log_files:
        try:
            if log_file != main_log:
                os.remove(log_file)
            else:
                # Очищаем основной лог
                open(log_file, 'w').close()
        except Exception as e:
            logger.error(f"Ошибка удаления лога {log_file}: {e}")
    
    logger.info("SCHEDULER: Логи отправлены админам и очищены.")