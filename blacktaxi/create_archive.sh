#!/bin/bash

# Скрипт для создания архива проекта Telegram VIP Bot
# Автор: Dmitriy
# Версия: 1.0

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Функция для вывода сообщений
print_message() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo -e "${BLUE}================================${NC}"
    echo -e "${BLUE}  Создание архива проекта${NC}"
    echo -e "${BLUE}================================${NC}"
}

# Проверка текущей директории
check_directory() {
    if [ ! -f "bot.py" ] || [ ! -f "admin_panel.py" ]; then
        print_error "Скрипт должен быть запущен из корневой папки проекта"
        exit 1
    fi
    print_message "Директория проверена"
}

# Создание временной папки
create_temp_dir() {
    print_message "Создание временной папки..."
    
    TEMP_DIR=$(mktemp -d)
    ARCHIVE_DIR="$TEMP_DIR/telegram-vip-bot"
    mkdir -p "$ARCHIVE_DIR"
    
    print_message "Временная папка создана: $TEMP_DIR"
}

# Копирование основных файлов
copy_main_files() {
    print_message "Копирование основных файлов..."
    
    # Основные Python файлы
    cp bot.py "$ARCHIVE_DIR/"
    cp admin_panel.py "$ARCHIVE_DIR/"
    cp ai_processor.py "$ARCHIVE_DIR/"
    cp test_map.py "$ARCHIVE_DIR/"
    cp get_group_ids.py "$ARCHIVE_DIR/"
    
    # Конфигурационные файлы
    cp requirements.txt "$ARCHIVE_DIR/"
    cp ecosystem.config.js "$ARCHIVE_DIR/"
    cp .env.example "$ARCHIVE_DIR/"
    
    # Установщики и документация
    cp install.sh "$ARCHIVE_DIR/"
    cp quick_install.sh "$ARCHIVE_DIR/"
    cp ARCHIVE_README.md "$ARCHIVE_DIR/"
    cp INSTALLATION_GUIDE.md "$ARCHIVE_DIR/"
    cp QUICK_START.md "$ARCHIVE_DIR/"
    cp README.md "$ARCHIVE_DIR/"
    
    # Systemd сервисы
    cp telegram-bot.service "$ARCHIVE_DIR/"
    
    print_message "Основные файлы скопированы"
}

# Копирование папки templates
copy_templates() {
    print_message "Копирование шаблонов..."
    
    if [ -d "templates" ]; then
        cp -r templates "$ARCHIVE_DIR/"
        print_message "Шаблоны скопированы"
    else
        print_warning "Папка templates не найдена"
    fi
}

# Создание папки logs
create_logs_dir() {
    print_message "Создание папки logs..."
    
    mkdir -p "$ARCHIVE_DIR/logs"
    touch "$ARCHIVE_DIR/logs/.gitkeep"
    
    print_message "Папка logs создана"
}

# Удаление ненужных файлов
cleanup_files() {
    print_message "Очистка ненужных файлов..."
    
    # Удаляем кэш Python
    find "$ARCHIVE_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    find "$ARCHIVE_DIR" -name "*.pyc" -delete 2>/dev/null || true
    find "$ARCHIVE_DIR" -name "*.pyo" -delete 2>/dev/null || true
    
    # Удаляем виртуальное окружение если есть
    if [ -d "$ARCHIVE_DIR/venv" ]; then
        rm -rf "$ARCHIVE_DIR/venv"
        print_message "Виртуальное окружение удалено из архива"
    fi
    
    # Удаляем базу данных
    if [ -f "$ARCHIVE_DIR/bot.db" ]; then
        rm "$ARCHIVE_DIR/bot.db"
        print_message "База данных удалена из архива"
    fi
    
    # Удаляем логи
    if [ -f "$ARCHIVE_DIR/bot.log" ]; then
        rm "$ARCHIVE_DIR/bot.log"
        print_message "Логи удалены из архива"
    fi
    
    print_message "Очистка завершена"
}

    # Установка прав доступа
    set_permissions() {
        print_message "Установка прав доступа..."
        
        chmod +x "$ARCHIVE_DIR/install.sh"
        chmod +x "$ARCHIVE_DIR/quick_install.sh"
        
        print_message "Права доступа установлены"
    }

# Создание архива
create_archive() {
    print_message "Создание архива..."
    
    ARCHIVE_NAME="telegram-vip-bot-$(date +%Y%m%d-%H%M%S).tar.gz"
    
    cd "$TEMP_DIR"
    tar -czf "$ARCHIVE_NAME" telegram-vip-bot/
    
    # Перемещаем архив в текущую директорию
    mv "$ARCHIVE_NAME" "/opt/dmitriy/telegram-vip-bot/"
    
    print_message "Архив создан: $ARCHIVE_NAME"
    print_message "Размер архива: $(du -h "/opt/dmitriy/telegram-vip-bot/$ARCHIVE_NAME" | cut -f1)"
}

# Очистка временных файлов
cleanup_temp() {
    print_message "Очистка временных файлов..."
    
    rm -rf "$TEMP_DIR"
    
    print_message "Временные файлы удалены"
}

# Показ информации об архиве
show_archive_info() {
    print_message "Архив успешно создан!"
    echo ""
    echo -e "${BLUE}Содержимое архива:${NC}"
    echo "- Основные файлы бота (bot.py, admin_panel.py, ai_processor.py)"
    echo "- Админ-панель с шаблонами"
    echo "- Конфигурационные файлы"
    echo "- Автоматический установщик (install.sh)"
    echo "- Документация и инструкции"
    echo "- Systemd сервисы"
    echo ""
    echo -e "${BLUE}Для установки:${NC}"
    echo "1. Распакуйте архив: tar -xzf $ARCHIVE_NAME"
    echo "2. Перейдите в папку: cd telegram-vip-bot"
    echo "3. Запустите установщик: ./install.sh"
    echo "4. Настройте .env файл"
    echo "5. Запустите бота"
}

# Основная функция
main() {
    print_header
    check_directory
    create_temp_dir
    copy_main_files
    copy_templates
    create_logs_dir
    cleanup_files
    set_permissions
    create_archive
    cleanup_temp
    show_archive_info
}

# Запуск
main "$@" 