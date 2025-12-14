# 🚀 Быстрый запуск VPN Bot

## 1. Настройка

Отредактируйте `.env` файл:

```bash
# ОБЯЗАТЕЛЬНО! Укажите токен вашего бота
BOT_TOKEN="1234567890:AAAA-your-bot-token-here"

# ОБЯЗАТЕЛЬНО! ID администраторов (ваш Telegram ID)
ADMIN_IDS="123456789,987654321"

# Остальные параметры можете оставить как есть для тестирования
```

## 2. Запуск

```bash
# Дайте права на выполнение скрипта
chmod +x start.sh

# Запустите бота
./start.sh
```

## 3. Проверка

После запуска:
- Откройте вашего бота в Telegram
- Отправьте `/start`
- Отправьте `/admin` (если вы админ)

## 4. Мониторинг

```bash
# Просмотр логов в реальном времени
docker-compose logs -f bot

# Статус сервисов
docker-compose ps

# Остановка
docker-compose down
```

## 🔧 Настройка платежей и VPN

Для полной работы настройте в `.env`:

1. **YooKassa** (для приема платежей):
   - `YOOKASSA_SHOP_ID`
   - `YOOKASSA_SECRET_KEY`

2. **Remnawave** (для VPN):
   - `REMNAWAVE_PANEL_URL`
   - `REMNAWAVE_API_TOKEN`
   - `REMNAWAVE_SQUAD_UUID`

3. **Домен** (для webhook):
   - `SERVER_BASE_URL`

---

**Готово!** Бот работает с PostgreSQL и полноценной админкой 🎉
