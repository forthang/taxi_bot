#!/usr/bin/env python3
"""
Скрипт миграции для обновления trafficLimitBytes и trafficLimitStrategy
для существующих пользователей в Remnawave панели.

Запуск: python migrate_users.py
"""

import asyncio
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 500 GB в байтах
TRAFFIC_LIMIT_BYTES = 500 * 1024 * 1024 * 1024

async def migrate_users():
    from api import RemnaAsyncManager, RemnaAPIError
    
    panel_url = os.getenv("REMNAWAVE_PANEL_URL")
    api_token = os.getenv("REMNAWAVE_API_TOKEN")
    
    if not panel_url or not api_token:
        logger.error("REMNAWAVE_PANEL_URL и REMNAWAVE_API_TOKEN должны быть установлены")
        return
    
    logger.info("Начало миграции пользователей...")
    
    async with RemnaAsyncManager(panel_url, api_token) as mgr:
        # Получаем всех пользователей
        users = await mgr.get_all_users(size=1000)
        logger.info(f"Найдено {len(users)} пользователей")
        
        updated = 0
        errors = 0
        
        for user in users:
            username = user.get("username")
            if not username or not username.startswith("tg_"):
                continue
            
            try:
                await mgr.update_user(
                    username=username,
                    updates={
                        "trafficLimitBytes": TRAFFIC_LIMIT_BYTES,
                        "trafficLimitStrategy": "MONTH"
                    }
                )
                updated += 1
                logger.info(f"Обновлен: {username}")
                await asyncio.sleep(0.1)  # Пауза чтобы не перегружать API
            except RemnaAPIError as e:
                errors += 1
                logger.error(f"Ошибка обновления {username}: {e}")
            except Exception as e:
                errors += 1
                logger.error(f"Неожиданная ошибка для {username}: {e}")
        
        logger.info(f"Миграция завершена. Обновлено: {updated}, Ошибок: {errors}")

if __name__ == "__main__":
    asyncio.run(migrate_users())
