import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from telegram.ext import Application
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden

from database import (
    get_any_subscription, update_or_create_subscription, 
    mark_trial_as_used, log_referral_purchase,
    add_payment, update_payment_status, get_payment_info,
    ensure_user_exists
)
from api import RemnaAsyncManager, RemnaAPIError
from config import config, TARIFFS

logger = logging.getLogger(__name__)

# 500 GB в байтах
TRAFFIC_LIMIT_BYTES = 500 * 1024 * 1024 * 1024  # 536870912000

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

async def notify_admins(application: Application, message: str):
    """Отправляет уведомление всем администраторам"""
    logger.info(f"Уведомление админам: {message[:100]}...")
    for admin_id in config.ADMIN_IDS:
        try:
            await application.bot.send_message(chat_id=admin_id, text=message, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

async def grant_subscription(application: Application, user_id: int, days: int, is_trial: bool = False, is_manual: bool = False):
    """Создает или продлевает подписку"""
    logger.info(f"Выдача подписки: user_id={user_id}, days={days}, trial={is_trial}, manual={is_manual}")
    
    if not config.remnawave_enabled:
        msg = "❌ Интеграция с Remnawave отключена"
        logger.error(msg)
        if is_manual:
            await notify_admins(application, msg)
        if not is_manual:
            raise Exception(msg)
        return

    try:
        # Гарантируем что пользователь существует в БД (исправление foreign key constraint)
        await ensure_user_exists(user_id)
        
        # Работа с API Remnawave
        username_in_panel = f"tg_{user_id}"
        old_sub_data = await get_any_subscription(user_id) 
        
        start_from = datetime.now(timezone.utc)
        
        if old_sub_data and old_sub_data[1]:
            current_end_date = safe_parse_datetime(old_sub_data[1])
            if current_end_date > start_from:
                start_from = current_end_date
        
        new_expire_dt = start_from + timedelta(days=days)

        async with RemnaAsyncManager(config.REMNAWAVE_PANEL_URL, config.REMNAWAVE_API_TOKEN) as mgr:
            user_in_panel = await mgr.find_user_by_username(username_in_panel)
            if user_in_panel:
                # Обновляем существующего пользователя
                await mgr.update_user(
                    username=username_in_panel, 
                    updates={
                        "expireAt": new_expire_dt.isoformat().replace('+00:00', 'Z'),
                        "trafficLimitBytes": TRAFFIC_LIMIT_BYTES,
                        "trafficLimitStrategy": "MONTH"
                    }
                )
            else:
                # Создаем нового пользователя с лимитом трафика
                await mgr.create_user(
                    username=username_in_panel, 
                    squad_uuid=config.REMNAWAVE_SQUAD_UUID, 
                    expire_at=new_expire_dt,
                    trafficLimitBytes=TRAFFIC_LIMIT_BYTES,
                    trafficLimitStrategy="MONTH"
                )
        
        # Обновление в БД
        vless_uuid_for_db = old_sub_data[0] if old_sub_data else str(uuid.uuid4())
        await update_or_create_subscription(user_id=user_id, vless_uuid=vless_uuid_for_db, duration_days=days)
        
        if is_trial:
            await mark_trial_as_used(user_id)

        # Реферальный бонус
        if not is_trial and not is_manual:
            referrer_id = await log_referral_purchase(user_id)
            if referrer_id:
                logger.info(f"Начисляем реферальный бонус 30 дней для user_id={referrer_id}")
                await grant_subscription(application, referrer_id, 30, is_manual=True)
                try:
                    await application.bot.send_message(
                        chat_id=referrer_id, 
                        text="🎉 Ваш друг совершил покупку! Вам начислено **30 бонусных дней**!", 
                        parse_mode=ParseMode.MARKDOWN
                    )
                except (BadRequest, Forbidden):
                    pass

        # Уведомление пользователя
        if is_manual:
            message_text = f"✅ Администратор вручную начислил вам **{days} дней** подписки."
        else:
            message_type = "Тестовый доступ" if is_trial else "Подписка"
            message_text = f"✅ **{message_type} на {days} дней активирован!**\n\nВаша подписка продлена. Приятного пользования!"
        
        await application.bot.send_message(
            chat_id=user_id, 
            text=message_text, 
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"Подписка выдана успешно для {user_id}")

    except Exception as e:
        logger.error(f"Ошибка при grant_subscription для {user_id}: {e}", exc_info=True)
        raise e

async def process_payment(application: Application, payment_id: str, user_id: int, tariff: str):
    """Асинхронно обрабатывает успешный платеж"""
    logger.info(f"PROCESS_PAYMENT: Старт для {payment_id}, user={user_id}, tariff={tariff}")
    
    try:
        # Проверяем, не обработан ли уже платеж
        payment_info = await get_payment_info(payment_id)
        if payment_info and payment_info.get("status") == 'completed':
            logger.info(f"PROCESS_PAYMENT: Платеж {payment_id} уже обработан")
            return

        await update_payment_status(payment_id, 'processing')
        
        days_to_add = TARIFFS[tariff]['days']
        await grant_subscription(application, user_id, days_to_add)
        
        await update_payment_status(payment_id, 'completed')
        logger.info(f"PROCESS_PAYMENT: Успешно завершен для {payment_id}")
        
    except Exception as e:
        logger.critical(f"PROCESS_PAYMENT: Критическая ошибка для {payment_id}: {e}", exc_info=True)
        await update_payment_status(payment_id, 'failed')
        await notify_admins(application, f"❗️ Ошибка обработки платежа `{payment_id}` (user: `{user_id}`).\nТекст: `{e}`")
