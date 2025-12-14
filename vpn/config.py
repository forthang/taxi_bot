import os
from typing import List, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    # Bot
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: List[int] = None
    
    # Support
    SUPPORT_USERNAME: str = os.getenv("SUPPORT_USERNAME", "support")
    TERMS_URL: str = os.getenv("TERMS_URL", "")
    SET_URL: str = os.getenv("SET_URL", "")
    
    # Remnawave
    REMNAWAVE_PANEL_URL: str = os.getenv("REMNAWAVE_PANEL_URL", "")
    REMNAWAVE_API_TOKEN: str = os.getenv("REMNAWAVE_API_TOKEN", "")
    REMNAWAVE_SQUAD_UUID: str = os.getenv("REMNAWAVE_SQUAD_UUID", "")
    
    # YooKassa
    YOOKASSA_SHOP_ID: str = os.getenv("YOOKASSA_SHOP_ID", "")
    YOOKASSA_SECRET_KEY: str = os.getenv("YOOKASSA_SECRET_KEY", "")
    
    # Server
    SERVER_BASE_URL: str = os.getenv("SERVER_BASE_URL", "")
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8080"))
    
    # Directories
    DATA_DIR: str = os.getenv("DATA_DIR", "data")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    
    def __post_init__(self):
        admin_ids_str = os.getenv("ADMIN_IDS", "")
        self.ADMIN_IDS = []
        if admin_ids_str:
            try:
                self.ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(',') if x.strip()]
            except ValueError:
                pass
    
    @property
    def remnawave_enabled(self) -> bool:
        return all([self.REMNAWAVE_PANEL_URL, self.REMNAWAVE_API_TOKEN, self.REMNAWAVE_SQUAD_UUID])
    
    @property
    def yookassa_enabled(self) -> bool:
        return all([self.YOOKASSA_SHOP_ID, self.YOOKASSA_SECRET_KEY, self.SERVER_BASE_URL])

# Тарифы
TARIFFS = {
    "buy_30": {"price": 299.00, "days": 30, "description": "🗓️ Подписка на 1 месяц"},
    "buy_90": {"price": 799.00, "days": 90, "description": "🌱 Подписка на 3 месяца"}
}

config = Config()
