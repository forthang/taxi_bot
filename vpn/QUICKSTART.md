# VPN Bot - Production Deployment

## Быстрый старт

### 1. Настройка окружения

Скопируйте `.env.example` в `.env` и заполните все переменные:

```bash
cp .env.example .env
nano .env
```

### 2. Запуск

```bash
docker-compose up -d --build
```

### 3. Проверка статуса

```bash
docker-compose ps
docker-compose logs -f bot
```

## Миграция существующих пользователей

Если у вас уже есть пользователи в Remnawave панели, запустите миграцию для установки лимита трафика:

```bash
docker-compose exec bot python migrate_users.py
```

Это установит:
- trafficLimitBytes: 500 GB
- trafficLimitStrategy: MONTH (сброс каждый месяц)

## Управление

### Перезапуск
```bash
docker-compose restart bot
```

### Просмотр логов
```bash
docker-compose logs -f bot
```

### Остановка
```bash
docker-compose down
```

### Бэкап БД
```bash
docker-compose exec db pg_dump -U postgres vpn_bot_db > backup_$(date +%Y%m%d).sql
```

### Восстановление БД
```bash
cat backup.sql | docker-compose exec -T db psql -U postgres vpn_bot_db
```

## Админ-панель

Команды для администраторов (ID должен быть в ADMIN_IDS):

- `/admin` - открыть панель администратора
- `/grant <user_id> <days>` - выдать подписку пользователю

### Функции админ-панели:
- 📊 Статистика - общая статистика бота
- 👥 Управление пользователями - поиск и выдача подписок
- 💰 Платежи - просмотр ожидающих платежей
- 💵 Тарифы - изменение цен на подписки
- 📄 Логи - скачать файл логов
- 📢 Рассылка - отправка сообщений всем пользователям
- ⚙️ Система - системные функции

## Структура данных

### Docker volumes
- `postgres_data` - данные PostgreSQL (сохраняются при перезапуске)
- `./logs` - логи бота
- `./data` - дополнительные данные

### Таблицы БД
- `users` - пользователи бота
- `subscriptions` - подписки
- `payments` - платежи
- `referral_sources` - источники рефералов
- `settings` - настройки (включая цены тарифов)

## Troubleshooting

### Ошибка foreign key constraint
Исправлена в текущей версии. Бот автоматически создает запись пользователя перед созданием подписки.

### Бот не отвечает
1. Проверьте логи: `docker-compose logs bot`
2. Проверьте health check: `curl http://localhost:8005/health`
3. Перезапустите: `docker-compose restart bot`

### Проблемы с БД
1. Проверьте статус: `docker-compose exec db pg_isready`
2. Проверьте логи: `docker-compose logs db`
