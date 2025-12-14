# /bot/database.py

import asyncpg
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Any, Optional

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

async def get_connection():
    """Получение соединения с базой данных"""
    return await asyncpg.connect(DATABASE_URL)

async def initialize_db():
    """Инициализация базы данных"""
    conn = await get_connection()
    try:
        # Создание таблиц
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL UNIQUE,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                had_trial INTEGER DEFAULT 0,
                source TEXT,
                referrer_id BIGINT,
                agreed_to_terms INTEGER DEFAULT 0
            )''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                vless_uuid TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                start_date TIMESTAMP NOT NULL,
                end_date TIMESTAMP NOT NULL,
                notification_sent INTEGER DEFAULT 0,
                pre_expiration_notification_sent INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS referral_sources (
                id SERIAL PRIMARY KEY,
                source_name TEXT NOT NULL UNIQUE,
                start_count INTEGER DEFAULT 0,
                purchase_count INTEGER DEFAULT 0
            )''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                payment_id TEXT NOT NULL UNIQUE,
                user_id BIGINT NOT NULL,
                amount REAL NOT NULL,
                tariff TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
        
        # Создание индексов
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_user_id ON subscriptions(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_status ON subscriptions(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_end_date ON subscriptions(end_date)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_pay_pid ON payments(payment_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_pay_status ON payments(status)")
        
        logger.info("DB: Инициализация завершена (PostgreSQL)")
    finally:
        await conn.close()

async def add_user(user_id: int, username: str, first_name: str, last_name: str, source: str = None, referrer_id: int = None):
    conn = await get_connection()
    try:
        await conn.execute(
            "INSERT INTO users (user_id, username, first_name, last_name, source, referrer_id) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (user_id) DO NOTHING",
            user_id, username, first_name, last_name, source, referrer_id
        )
        if source:
            await conn.execute("INSERT INTO referral_sources (source_name) VALUES ($1) ON CONFLICT (source_name) DO NOTHING", source)
            await conn.execute("UPDATE referral_sources SET start_count = start_count + 1 WHERE source_name = $1", source)
    finally:
        await conn.close()

# --- Подписки ---

async def get_active_subscription(user_id: int) -> Optional[Tuple[str, str]]:
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT vless_uuid, end_date FROM subscriptions WHERE user_id = $1 AND status = 'active' AND end_date > CURRENT_TIMESTAMP", 
            user_id
        )
        return (row['vless_uuid'], row['end_date']) if row else None
    finally:
        await conn.close()

async def get_any_subscription(user_id: int) -> Optional[Tuple[str, str]]:
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT vless_uuid, end_date FROM subscriptions WHERE user_id = $1 ORDER BY id DESC LIMIT 1", 
            user_id
        )
        return (row['vless_uuid'], row['end_date']) if row else None
    finally:
        await conn.close()

async def update_or_create_subscription(user_id: int, vless_uuid: str, duration_days: int):
    conn = await get_connection()
    try:
        # Получаем текущую подписку
        existing_sub = await conn.fetchrow(
            "SELECT end_date FROM subscriptions WHERE user_id = $1 AND status = 'active' ORDER BY end_date DESC LIMIT 1", 
            user_id
        )

        start_from = datetime.now(timezone.utc)
        if existing_sub and existing_sub['end_date']:
            current_end_date = existing_sub['end_date']
            if isinstance(current_end_date, str):
                try:
                    current_end_date = datetime.fromisoformat(current_end_date.replace('Z', '+00:00'))
                except:
                    current_end_date = datetime.now(timezone.utc)
            
            if current_end_date > start_from:
                start_from = current_end_date

        new_end_date = start_from + timedelta(days=duration_days)
        
        await conn.execute("""
            INSERT INTO subscriptions (user_id, vless_uuid, status, start_date, end_date, notification_sent, pre_expiration_notification_sent) 
            VALUES ($1, $2, 'active', $3, $4, 0, 0)
            ON CONFLICT(vless_uuid) DO UPDATE SET
            end_date = EXCLUDED.end_date, status = 'active', notification_sent = 0, pre_expiration_notification_sent = 0
        """, user_id, vless_uuid, start_from, new_end_date)
    finally:
        await conn.close()

# --- Платежи ---

async def add_payment(payment_id: str, user_id: int, amount: float, tariff: str):
    conn = await get_connection()
    try:
        await conn.execute(
            "INSERT INTO payments (payment_id, user_id, amount, tariff, status) VALUES ($1, $2, $3, $4, 'pending') ON CONFLICT (payment_id) DO NOTHING",
            payment_id, user_id, amount, tariff
        )
    finally:
        await conn.close()

async def update_payment_status(payment_id: str, status: str):
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE payments SET status = $1, updated_at = CURRENT_TIMESTAMP WHERE payment_id = $2", 
            status, payment_id
        )
    finally:
        await conn.close()

async def get_payment_info(payment_id: str) -> Optional[dict]:
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT * FROM payments WHERE payment_id = $1", payment_id)
        return dict(row) if row else None
    finally:
        await conn.close()

async def get_pending_payments() -> List[Tuple[Any, ...]]:
    conn = await get_connection()
    try:
        rows = await conn.fetch("SELECT payment_id, user_id, tariff FROM payments WHERE status IN ('pending', 'processing')")
        return [(row['payment_id'], row['user_id'], row['tariff']) for row in rows]
    finally:
        await conn.close()

# --- Прочее ---

async def has_used_trial(user_id: int) -> bool:
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT had_trial FROM users WHERE user_id = $1", user_id)
        return row and row['had_trial'] == 1
    finally:
        await conn.close()

async def mark_trial_as_used(user_id: int):
    conn = await get_connection()
    try:
        await conn.execute("UPDATE users SET had_trial = 1 WHERE user_id = $1", user_id)
    finally:
        await conn.close()

async def has_agreed_to_terms(user_id: int) -> bool:
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT agreed_to_terms FROM users WHERE user_id = $1", user_id)
        return row and row['agreed_to_terms'] == 1
    finally:
        await conn.close()

async def mark_terms_as_agreed(user_id: int):
    conn = await get_connection()
    try:
        await conn.execute("UPDATE users SET agreed_to_terms = 1 WHERE user_id = $1", user_id)
    finally:
        await conn.close()

async def get_user_source(user_id: int) -> Optional[str]:
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT source FROM users WHERE user_id = $1", user_id)
        return row['source'] if row else None
    finally:
        await conn.close()

async def get_user_referrer(user_id: int) -> Optional[int]:
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT referrer_id FROM users WHERE user_id = $1", user_id)
        return row['referrer_id'] if row else None
    finally:
        await conn.close()

# --- Рефералка ---

async def log_referral_purchase(user_id: int) -> Optional[int]:
    conn = await get_connection()
    try:
        # Обновляем статистику источника
        row = await conn.fetchrow("SELECT source FROM users WHERE user_id = $1", user_id)
        if row and row['source']:
            await conn.execute("UPDATE referral_sources SET purchase_count = purchase_count + 1 WHERE source_name = $1", row['source'])
        
        # Проверяем количество подписок
        count_row = await conn.fetchrow("SELECT COUNT(*) FROM subscriptions WHERE user_id = $1", user_id)
        count = count_row['count'] if count_row else 0
        
        # Если первая покупка, возвращаем реферера
        if count <= 1:
            ref_row = await conn.fetchrow("SELECT referrer_id FROM users WHERE user_id = $1", user_id)
            if ref_row and ref_row['referrer_id']:
                return ref_row['referrer_id']
        return None
    finally:
        await conn.close()

async def get_referral_program_stats(referrer_id: int) -> Tuple[int, int]:
    conn = await get_connection()
    try:
        invited_row = await conn.fetchrow("SELECT COUNT(id) FROM users WHERE referrer_id = $1", referrer_id)
        invited = invited_row['count'] if invited_row else 0
        
        purchased_row = await conn.fetchrow(
            "SELECT COUNT(DISTINCT u.user_id) FROM users u JOIN subscriptions s ON u.user_id = s.user_id WHERE u.referrer_id = $1", 
            referrer_id
        )
        purchased = purchased_row['count'] if purchased_row else 0
        
        return invited, purchased
    finally:
        await conn.close()

# --- Статистика ---

async def get_all_user_ids() -> List[int]:
    conn = await get_connection()
    try:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [row['user_id'] for row in rows]
    finally:
        await conn.close()

async def get_stats() -> dict:
    conn = await get_connection()
    try:
        total_row = await conn.fetchrow("SELECT COUNT(id) FROM users")
        total = total_row['count'] if total_row else 0
        
        active_row = await conn.fetchrow(
            "SELECT COUNT(DISTINCT user_id) FROM subscriptions WHERE status = 'active' AND end_date > CURRENT_TIMESTAMP"
        )
        active = active_row['count'] if active_row else 0
        
        return {"total_users": total, "active_subscriptions": active}
    finally:
        await conn.close()

# --- Scheduler Helpers ---

async def get_subscriptions_to_pre_notify():
    conn = await get_connection()
    try:
        tomorrow = datetime.now() + timedelta(hours=24)
        rows = await conn.fetch(
            "SELECT user_id FROM subscriptions WHERE status = 'active' AND end_date < $1 AND end_date > CURRENT_TIMESTAMP AND pre_expiration_notification_sent = 0", 
            tomorrow
        )
        return [(row['user_id'],) for row in rows]
    finally:
        await conn.close()

async def mark_pre_notification_as_sent(user_id: int):
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE subscriptions SET pre_expiration_notification_sent = 1 WHERE user_id = $1 AND status = 'active'", 
            user_id
        )
    finally:
        await conn.close()

async def get_subscriptions_to_notify():
    conn = await get_connection()
    try:
        rows = await conn.fetch(
            "SELECT user_id FROM subscriptions WHERE status = 'active' AND end_date < CURRENT_TIMESTAMP AND notification_sent = 0"
        )
        return [(row['user_id'],) for row in rows]
    finally:
        await conn.close()

async def mark_subscription_as_expired(user_id: int):
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE subscriptions SET status = 'expired', notification_sent = 1 WHERE user_id = $1 AND status = 'active' AND end_date < CURRENT_TIMESTAMP", 
            user_id
        )
    finally:
        await conn.close()

async def get_all_active_users_for_sync():
    conn = await get_connection()
    try:
        rows = await conn.fetch("SELECT DISTINCT user_id FROM subscriptions WHERE status = 'active'")
        return [(row['user_id'],) for row in rows]
    finally:
        await conn.close()

async def sync_subscription_date(user_id: int, new_end_date: datetime, current_time: datetime):
    conn = await get_connection()
    try:
        await conn.execute("""
            UPDATE subscriptions 
            SET end_date = $1, 
                notification_sent = CASE WHEN $2 > end_date THEN 0 ELSE notification_sent END,
                pre_expiration_notification_sent = CASE WHEN $2 > end_date THEN 0 ELSE pre_expiration_notification_sent END
            WHERE user_id = $3 AND status = 'active'
        """, new_end_date, new_end_date, user_id)
    finally:
        await conn.close()