# /bot/database.py

import asyncpg
import os
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Any, Optional

logger = logging.getLogger(__name__)

# Получаем URL базы данных из переменных окружения
DATABASE_URL = os.getenv("DATABASE_URL")

# Глобальная переменная для пула соединений
pool: Optional[asyncpg.Pool] = None

async def get_pool() -> asyncpg.Pool:
    """Возвращает пул соединений с повторными попытками."""
    global pool
    if pool is None:
        if not DATABASE_URL:
            raise ValueError("Переменная окружения DATABASE_URL не установлена!")
        
        retries = 10
        for i in range(retries):
            try:
                pool = await asyncpg.create_pool(dsn=DATABASE_URL)
                logger.info("DB: Пул соединений PostgreSQL создан.")
                break
            except (OSError, asyncpg.CannotConnectNowError, asyncpg.PostgresConnectionError) as e:
                if i == retries - 1:
                    logger.critical(f"DB: Не удалось подключиться к БД после {retries} попыток: {e}")
                    raise e
                logger.warning(f"DB: База данных еще не готова (попытка {i+1}/{retries}). Ждем 2 сек...")
                await asyncio.sleep(2)
                
    return pool

async def initialize_db():
    """
    Инициализирует таблицы в PostgreSQL.
    """
    p = await get_pool()
    async with p.acquire() as conn:
        # Таблица пользователей
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL UNIQUE,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                registered_at TIMESTAMPTZ DEFAULT NOW(),
                had_trial INTEGER DEFAULT 0,
                source TEXT,
                referrer_id BIGINT,
                agreed_to_terms INTEGER DEFAULT 0
            )''')

        # Таблица подписок
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                vless_uuid TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                start_date TIMESTAMPTZ NOT NULL,
                end_date TIMESTAMPTZ NOT NULL,
                notification_sent INTEGER DEFAULT 0,
                pre_expiration_notification_sent INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )''')

        # Таблица рефералов
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS referral_sources (
                id SERIAL PRIMARY KEY,
                source_name TEXT NOT NULL UNIQUE,
                start_count INTEGER DEFAULT 0,
                purchase_count INTEGER DEFAULT 0
            )''')
        
        # Таблица платежей
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                payment_id TEXT NOT NULL UNIQUE,
                user_id BIGINT NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                tariff TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )''')
        
        # Индексы
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_user_id ON subscriptions(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_status ON subscriptions(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_end_date ON subscriptions(end_date)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_payment_id ON payments(payment_id)")

        logger.info("DB: Инициализация PostgreSQL завершена.")

async def add_user(user_id: int, username: str, first_name: str, last_name: str, source: str = None, referrer_id: int = None):
    p = await get_pool()
    async with p.acquire() as conn:
        # Проверяем существование
        existing_user = await conn.fetchrow("SELECT source, referrer_id FROM users WHERE user_id = $1", user_id)

        if not existing_user:
            await conn.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name, source, referrer_id) 
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id, username, first_name, last_name, source, referrer_id
            )
            logger.info(f"DB: Новый пользователь {user_id} (source={source}).")
            
            if source:
                await conn.execute("""
                    INSERT INTO referral_sources (source_name, start_count) VALUES ($1, 1)
                    ON CONFLICT (source_name) DO UPDATE SET start_count = referral_sources.start_count + 1
                """, source)
        else:
            pass # Логика обновления при необходимости

# --- Подписки ---

async def get_active_subscription(user_id: int) -> Optional[Tuple[str, datetime]]:
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT vless_uuid, end_date FROM subscriptions WHERE user_id = $1 AND status = 'active' AND end_date > NOW()", 
            user_id
        )
        return (row['vless_uuid'], row['end_date']) if row else None

async def get_any_subscription(user_id: int) -> Optional[Tuple[str, datetime]]:
    p = await get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT vless_uuid, end_date FROM subscriptions WHERE user_id = $1 ORDER BY id DESC LIMIT 1", 
            user_id
        )
        return (row['vless_uuid'], row['end_date']) if row else None

async def update_or_create_subscription(user_id: int, vless_uuid: str, duration_days: int):
    logger.debug(f"DB: Обновление подписки user_id={user_id} на {duration_days} дней.")
    p = await get_pool()
    async with p.acquire() as conn:
        # Получаем дату окончания текущей активной подписки
        # В Postgres NOW() возвращает TIMESTAMPTZ
        existing_end_date = await conn.fetchval(
            "SELECT end_date FROM subscriptions WHERE user_id = $1 AND status = 'active' ORDER BY end_date DESC LIMIT 1",
            user_id
        )

        start_from = datetime.now(timezone.utc)
        
        # Если есть активная подписка и она заканчивается в будущем
        if existing_end_date and existing_end_date > start_from:
            start_from = existing_end_date

        new_end_date = start_from + timedelta(days=duration_days)
        
        # UPSERT в Postgres
        await conn.execute("""
            INSERT INTO subscriptions (user_id, vless_uuid, status, start_date, end_date, notification_sent, pre_expiration_notification_sent) 
            VALUES ($1, $2, 'active', $3, $4, 0, 0)
            ON CONFLICT (vless_uuid) DO UPDATE SET
                end_date = EXCLUDED.end_date,
                status = 'active',
                notification_sent = 0,
                pre_expiration_notification_sent = 0
        """, user_id, vless_uuid, start_from, new_end_date)
        
        logger.info(f"DB: Подписка user_id={user_id} обновлена до {new_end_date}.")

# --- Платежи ---

async def add_payment(payment_id: str, user_id: int, amount: float, tariff: str) -> int:
    p = await get_pool()
    async with p.acquire() as conn:
        # INSERT ... RETURNING id
        # ON CONFLICT DO NOTHING вернет None, если такой платеж есть
        row = await conn.fetchrow("""
            INSERT INTO payments (payment_id, user_id, amount, tariff, status) 
            VALUES ($1, $2, $3, $4, 'pending')
            ON CONFLICT (payment_id) DO NOTHING
            RETURNING id
        """, payment_id, user_id, amount, tariff)
        
        if row:
            return row['id']
        
        # Если дубль, ищем существующий ID
        existing_id = await conn.fetchval("SELECT id FROM payments WHERE payment_id = $1", payment_id)
        return existing_id if existing_id else 0

async def update_payment_status(payment_id: str, status: str):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute(
            "UPDATE payments SET status = $1, updated_at = NOW() WHERE payment_id = $2", 
            status, payment_id
        )

async def get_pending_payments() -> List[Tuple[Any, ...]]:
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch("SELECT payment_id, user_id, tariff FROM payments WHERE status = 'pending' OR status = 'processing'")
        return [(r['payment_id'], r['user_id'], r['tariff']) for r in rows]

# --- Прочее ---

async def has_used_trial(user_id: int) -> bool:
    p = await get_pool()
    async with p.acquire() as conn:
        val = await conn.fetchval("SELECT had_trial FROM users WHERE user_id = $1", user_id)
        return val == 1

async def mark_trial_as_used(user_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute("UPDATE users SET had_trial = 1 WHERE user_id = $1", user_id)

async def has_agreed_to_terms(user_id: int) -> bool:
    p = await get_pool()
    async with p.acquire() as conn:
        val = await conn.fetchval("SELECT agreed_to_terms FROM users WHERE user_id = $1", user_id)
        return val == 1

async def mark_terms_as_agreed(user_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute("UPDATE users SET agreed_to_terms = 1 WHERE user_id = $1", user_id)

async def get_user_source(user_id: int) -> Optional[str]:
    p = await get_pool()
    async with p.acquire() as conn:
        return await conn.fetchval("SELECT source FROM users WHERE user_id = $1", user_id)

async def get_user_referrer(user_id: int) -> Optional[int]:
    p = await get_pool()
    async with p.acquire() as conn:
        return await conn.fetchval("SELECT referrer_id FROM users WHERE user_id = $1", user_id)

# --- Реферальная система ---

async def log_referral_purchase(user_id: int) -> Optional[int]:
    p = await get_pool()
    async with p.acquire() as conn:
        # Транзакция нужна для атомарности
        async with conn.transaction():
            source_name = await conn.fetchval("SELECT source FROM users WHERE user_id = $1", user_id)
            if source_name:
                await conn.execute(
                    "UPDATE referral_sources SET purchase_count = purchase_count + 1 WHERE source_name = $1", 
                    source_name
                )
            
            sub_count = await conn.fetchval("SELECT COUNT(*) FROM subscriptions WHERE user_id = $1", user_id)
            
            # Если подписка <= 1 (текущая), возвращаем реферера
            if sub_count <= 1:
                return await conn.fetchval("SELECT referrer_id FROM users WHERE user_id = $1", user_id)
            return None

async def get_referral_program_stats(referrer_id: int) -> Tuple[int, int]:
    p = await get_pool()
    async with p.acquire() as conn:
        invited = await conn.fetchval("SELECT COUNT(id) FROM users WHERE referrer_id = $1", referrer_id)
        
        purchased = await conn.fetchval("""
            SELECT COUNT(DISTINCT u.user_id) 
            FROM users u 
            JOIN subscriptions s ON u.user_id = s.user_id 
            WHERE u.referrer_id = $1
        """, referrer_id)
        
        # fetchval может вернуть None, если 0
        return (invited or 0, purchased or 0)

# --- Статистика и Админка ---

async def get_all_user_ids() -> List[int]:
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [r['user_id'] for r in rows]

async def get_stats() -> dict:
    p = await get_pool()
    async with p.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(id) FROM users")
        active_subs = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM subscriptions WHERE status = 'active' AND end_date > NOW()")
        return {"total_users": total_users or 0, "active_subscriptions": active_subs or 0}

# --- Для Scheduler ---

async def get_subscriptions_to_pre_notify():
    p = await get_pool()
    async with p.acquire() as conn:
        tomorrow = datetime.now(timezone.utc) + timedelta(hours=24)
        rows = await conn.fetch("""
            SELECT user_id FROM subscriptions
            WHERE status = 'active'
            AND end_date < $1
            AND end_date > NOW()
            AND pre_expiration_notification_sent = 0
        """, tomorrow)
        return [(r['user_id'],) for r in rows] # Возвращаем список кортежей для совместимости

async def mark_pre_notification_as_sent(user_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute("UPDATE subscriptions SET pre_expiration_notification_sent = 1 WHERE user_id = $1 AND status = 'active'", user_id)

async def get_subscriptions_to_notify():
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id FROM subscriptions 
            WHERE status = 'active' 
            AND end_date < NOW() 
            AND notification_sent = 0
        """)
        return [(r['user_id'],) for r in rows]

async def mark_subscription_as_expired(user_id: int):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute("""
            UPDATE subscriptions SET status = 'expired', notification_sent = 1 
            WHERE user_id = $1 AND status = 'active' AND end_date < NOW()
        """, user_id)

async def get_all_active_users_for_sync():
    p = await get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT user_id FROM subscriptions WHERE status = 'active'")
        return [(r['user_id'],) for r in rows]

async def sync_subscription_date(user_id: int, new_end_date: datetime, current_time: datetime):
    p = await get_pool()
    async with p.acquire() as conn:
        await conn.execute("""
            UPDATE subscriptions 
            SET end_date = $1, 
                notification_sent = CASE WHEN $2 > end_date THEN 0 ELSE notification_sent END,
                pre_expiration_notification_sent = CASE WHEN $3 > end_date THEN 0 ELSE pre_expiration_notification_sent END
            WHERE user_id = $4 AND status = 'active'
        """, new_end_date, new_end_date, new_end_date, user_id)