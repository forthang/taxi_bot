#!/bin/bash

echo "🚀 Запуск VPN Bot с PostgreSQL..."

# Проверяем наличие .env
if [ ! -f .env ]; then
    echo "❌ Файл .env не найден!"
    echo "Настройте параметры в .env файле"
    exit 1
fi

# Проверяем наличие BOT_TOKEN
if ! grep -q "BOT_TOKEN=" .env || grep -q "BOT_TOKEN=\"YOUR_BOT_TOKEN_HERE\"" .env; then
    echo "❌ BOT_TOKEN не настроен в .env файле!"
    echo "Укажите токен бота в переменной BOT_TOKEN"
    exit 1
fi

# Создаем директории
mkdir -p logs data

echo "🛑 Остановка старых контейнеров..."
docker-compose down

echo "📦 Сборка и запуск контейнеров..."
docker-compose up --build -d

echo "⏳ Ожидание запуска PostgreSQL..."
sleep 15

echo "📊 Статус сервисов:"
docker-compose ps

echo ""
echo "📄 Последние логи бота:"
docker-compose logs --tail=30 bot

echo ""
echo "✅ Бот запущен!"
echo ""
echo "📋 Полезные команды:"
echo "  📊 Мониторинг логов:    docker-compose logs -f bot"
echo "  🔍 Статус сервисов:    docker-compose ps"
echo "  🔄 Перезапуск бота:     docker-compose restart bot"
echo "  🛑 Остановка всего:     docker-compose down"
echo "  💾 Бэкап БД:           docker-compose exec db pg_dump -U postgres vpn_bot_db > backup.sql"
