# /bot/database.py

import aiosqlite
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Any, Optional

logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "data")
DB_PATH = os.path.join(DATA_DIR, 'database.db')

async def initialize_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        # Включаем WAL режим для лучшей конкурентности
        await db.execute("PRAGMA journal_mode=WAL;")
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                had_trial INTEGER DEFAULT 0,
                source TEXT,
                referrer_id INTEGER,
                agreed_to_terms INTEGER DEFAULT 0
            )''')

        await db.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                vless_uuid TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                start_date TIMESTAMP NOT NULL,
                end_date TIMESTAMP NOT NULL,
                notification_sent INTEGER DEFAULT 0,
                pre_expiration_notification_sent INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )''')

        await db.execute('''
            CREATE TABLE IF NOT EXISTS referral_sources (
                id INTEGER PRIMARY KEY,
                source_name TEXT NOT NULL UNIQUE,
                start_count INTEGER DEFAULT 0,
                purchase_count INTEGER DEFAULT 0
            )''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY,
                payment_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                tariff TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
        
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_subs_user_id ON subscriptions(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_pay_pid ON payments(payment_id)")
        
        await db.commit()
        logger.info("DB: Инициализация завершена (WAL enabled).")

async def add_user(user_id: int, username: str, first_name: str, last_name: str, source: str = None, referrer_id: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, source, referrer_id) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, first_name, last_name, source, referrer_id)
        )
        if source:
            await db.execute("INSERT OR IGNORE INTO referral_sources (source_name) VALUES (?)", (source,))
            await db.execute("UPDATE referral_sources SET start_count = start_count + 1 WHERE source_name = ?", (source,))
        await db.commit()

# --- Подписки ---

async def get_active_subscription(user_id: int) -> Optional[Tuple[str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT vless_uuid, end_date FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > CURRENT_TIMESTAMP", 
            (user_id,)
        ) as cursor:
            return await cursor.fetchone()

async def get_any_subscription(user_id: int) -> Optional[Tuple[str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT vless_uuid, end_date FROM subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT 1", 
            (user_id,)
        ) as cursor:
            return await cursor.fetchone()

async def update_or_create_subscription(user_id: int, vless_uuid: str, duration_days: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT end_date FROM subscriptions WHERE user_id = ? AND status = 'active' ORDER BY end_date DESC LIMIT 1", (user_id,)) as cursor:
            existing_sub = await cursor.fetchone()

        start_from = datetime.now(timezone.utc)
        if existing_sub and existing_sub[0]:
            try:
                date_string = str(existing_sub[0]).split('.')[0].replace('Z', '').replace('T', ' ')
                current_end_date = datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                if current_end_date > start_from:
                    start_from = current_end_date
            except Exception as e:
                logger.warning(f"DB date parse error: {e}")

        new_end_date = start_from + timedelta(days=duration_days)
        
        await db.execute("""
            INSERT INTO subscriptions (user_id, vless_uuid, status, start_date, end_date, notification_sent, pre_expiration_notification_sent) 
            VALUES (?, ?, 'active', ?, ?, 0, 0)
            ON CONFLICT(vless_uuid) DO UPDATE SET
            end_date = excluded.end_date, status = 'active', notification_sent = 0, pre_expiration_notification_sent = 0;
        """, (user_id, vless_uuid, start_from, new_end_date))
        await db.commit()

# --- Платежи ---

async def add_payment(payment_id: str, user_id: int, amount: float, tariff: str):
    """Добавляет платеж, если его нет. Иначе ничего не делает."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO payments (payment_id, user_id, amount, tariff, status) VALUES (?, ?, ?, ?, 'pending')",
            (payment_id, user_id, amount, tariff)
        )
        await db.commit()

async def update_payment_status(payment_id: str, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE payments SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE payment_id = ?", 
            (status, payment_id)
        )
        await db.commit()

async def get_payment_info(payment_id: str) -> Optional[dict]:
    """Получает информацию о платеже для проверки статуса."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

async def get_pending_payments() -> List[Tuple[Any, ...]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT payment_id, user_id, tariff FROM payments WHERE status = 'pending' OR status = 'processing'") as cursor:
            return await cursor.fetchall()

# --- Прочее ---

async def has_used_trial(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT had_trial FROM users WHERE user_id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
            return res and res[0] == 1

async def mark_trial_as_used(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET had_trial = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

async def has_agreed_to_terms(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT agreed_to_terms FROM users WHERE user_id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
            return res and res[0] == 1

async def mark_terms_as_agreed(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET agreed_to_terms = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_user_source(user_id: int) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT source FROM users WHERE user_id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
            return res[0] if res else None

async def get_user_referrer(user_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
            return res[0] if res else None

# --- Рефералка ---

async def log_referral_purchase(user_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT source FROM users WHERE user_id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
            if res and res[0]:
                await db.execute("UPDATE referral_sources SET purchase_count = purchase_count + 1 WHERE source_name = ?", (res[0],))
        
        async with db.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id = ?", (user_id,)) as cursor:
            cnt = (await cursor.fetchone())[0]
        
        # Если первая покупка
        if cnt <= 1:
            async with db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
                ref = await cursor.fetchone()
                if ref and ref[0]:
                    await db.commit()
                    return ref[0]
        await db.commit()
        return None

async def get_referral_program_stats(referrer_id: int) -> Tuple[int, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(id) FROM users WHERE referrer_id = ?", (referrer_id,)) as cur:
            invited = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(DISTINCT u.user_id) FROM users u JOIN subscriptions s ON u.user_id = s.user_id WHERE u.referrer_id = ?", (referrer_id,)) as cur:
            purchased = (await cur.fetchone())[0]
        return invited, purchased

# --- Статистика ---

async def get_all_user_ids() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(id) FROM users") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(DISTINCT user_id) FROM subscriptions WHERE status = 'active' AND end_date > CURRENT_TIMESTAMP") as cur:
            active = (await cur.fetchone())[0]
        return {"total_users": total, "active_subscriptions": active}

# --- Scheduler Helpers ---

async def get_subscriptions_to_pre_notify():
    async with aiosqlite.connect(DB_PATH) as db:
        tomorrow = datetime.now() + timedelta(hours=24)
        async with db.execute("SELECT user_id FROM subscriptions WHERE status = 'active' AND end_date < ? AND end_date > CURRENT_TIMESTAMP AND pre_expiration_notification_sent = 0", (tomorrow,)) as cur:
            return await cur.fetchall()

async def mark_pre_notification_as_sent(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE subscriptions SET pre_expiration_notification_sent = 1 WHERE user_id = ? AND status = 'active'", (user_id,))
        await db.commit()

async def get_subscriptions_to_notify():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM subscriptions WHERE status = 'active' AND end_date < CURRENT_TIMESTAMP AND notification_sent = 0") as cur:
            return await cur.fetchall()

async def mark_subscription_as_expired(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE subscriptions SET status = 'expired', notification_sent = 1 WHERE user_id = ? AND status = 'active' AND end_date < CURRENT_TIMESTAMP", (user_id,))
        await db.commit()

async def get_all_active_users_for_sync():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT DISTINCT user_id FROM subscriptions WHERE status = 'active'") as cur:
            return await cur.fetchall()

async def sync_subscription_date(user_id: int, new_end_date: datetime, current_time: datetime):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE subscriptions 
            SET end_date = ?, 
                notification_sent = CASE WHEN ? > end_date THEN 0 ELSE notification_sent END,
                pre_expiration_notification_sent = CASE WHEN ? > end_date THEN 0 ELSE pre_expiration_notification_sent END
            WHERE user_id = ? AND status = 'active'
        """, (new_end_date, new_end_date, new_end_date, user_id))
        await db.commit()