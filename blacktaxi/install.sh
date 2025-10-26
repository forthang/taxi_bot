#!/bin/bash

# Telegram VIP Bot Installer
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
    echo -e "${BLUE}  Telegram VIP Bot Installer${NC}"
    echo -e "${BLUE}================================${NC}"
}

# Проверка прав администратора
check_root() {
    if [[ $EUID -eq 0 ]]; then
        print_warning "Скрипт запущен с правами root. Рекомендуется запускать от обычного пользователя."
    fi
}

# Проверка системы
check_system() {
    print_message "Проверка системы..."
    
    if ! command -v python3 &> /dev/null; then
        print_error "Python3 не найден. Установите Python 3.8+"
        exit 1
    fi
    
    if ! command -v pip3 &> /dev/null; then
        print_error "pip3 не найден. Установите pip3"
        exit 1
    fi
    
    if ! command -v node &> /dev/null; then
        print_warning "Node.js не найден. PM2 не будет установлен."
        PM2_AVAILABLE=false
    else
        PM2_AVAILABLE=true
    fi
    
    print_message "Система готова к установке"
}

# Создание виртуального окружения
create_venv() {
    print_message "Создание виртуального окружения Python..."
    
    if [ -d "venv" ]; then
        print_warning "Виртуальное окружение уже существует. Удаляем..."
        rm -rf venv
    fi
    
    python3 -m venv venv
    source venv/bin/activate
    
    print_message "Обновление pip..."
    pip install --upgrade pip
    
    print_message "Виртуальное окружение создано"
}

# Установка зависимостей Python
install_python_deps() {
    print_message "Установка зависимостей Python..."
    
    source venv/bin/activate
    
    # Удаляем проблемные зависимости из requirements.txt
    grep -v "sqlite3\|hashlib" requirements.txt > requirements_clean.txt
    
    pip install -r requirements_clean.txt
    
    # Устанавливаем недостающие зависимости
    pip install python-telegram-bot==20.7
    pip install python-dotenv==1.0.0
    pip install aiohttp==3.9.1
    pip install flask==2.3.3
    pip install flask-login==0.6.3
    pip install werkzeug==2.3.7
    
    rm requirements_clean.txt
    
    print_message "Зависимости Python установлены"
}

# Установка PM2 (если доступен)
install_pm2() {
    if [ "$PM2_AVAILABLE" = true ]; then
        print_message "Установка PM2..."
        
        if ! command -v pm2 &> /dev/null; then
            npm install -g pm2
        fi
        
        print_message "PM2 установлен"
    else
        print_warning "PM2 не установлен (Node.js не найден)"
    fi
}

# Создание необходимых директорий
create_directories() {
    print_message "Создание необходимых директорий..."
    
    mkdir -p logs
    mkdir -p __pycache__
    
    print_message "Директории созданы"
}

# Настройка файла .env
setup_env() {
    print_message "Настройка переменных окружения..."
    
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            cp .env.example .env
            print_warning "Файл .env создан из .env.example"
            print_warning "Пожалуйста, отредактируйте .env файл с вашими настройками"
        else
            print_error "Файл .env.example не найден"
            exit 1
        fi
    else
        print_message "Файл .env уже существует"
    fi
}

# Обновление путей в ecosystem.config.js
update_ecosystem_config() {
    print_message "Обновление конфигурации PM2..."
    
    CURRENT_DIR=$(pwd)
    PYTHON_PATH="$CURRENT_DIR/venv/bin/python3"
    
    # Создаем временный файл
    sed "s|/opt/dmitriy/telegram-vip-bot|$CURRENT_DIR|g" ecosystem.config.js > ecosystem.config.js.tmp
    sed "s|/opt/dmitriy/telegram-vip-bot/venv/bin/python3|$PYTHON_PATH|g" ecosystem.config.js.tmp > ecosystem.config.js
    rm ecosystem.config.js.tmp
    
    print_message "Конфигурация PM2 обновлена"
}

# Установка прав доступа
set_permissions() {
    print_message "Установка прав доступа..."
    
    chmod +x bot.py
    chmod +x admin_panel.py
    chmod +x install.sh
    
    print_message "Права доступа установлены"
}

# Создание systemd сервисов (опционально)
create_systemd_services() {
    print_message "Создание systemd сервисов..."
    
    CURRENT_DIR=$(pwd)
    PYTHON_PATH="$CURRENT_DIR/venv/bin/python3"
    USER=$(whoami)
    
    # Создаем сервис для бота
    cat > telegram-bot.service << EOF
[Unit]
Description=Telegram VIP Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$CURRENT_DIR
Environment=PATH=$CURRENT_DIR/venv/bin
ExecStart=$PYTHON_PATH bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    # Создаем сервис для админ панели
    cat > telegram-admin.service << EOF
[Unit]
Description=Telegram VIP Bot Admin Panel
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$CURRENT_DIR
Environment=PATH=$CURRENT_DIR/venv/bin
ExecStart=$PYTHON_PATH admin_panel.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    print_message "Systemd сервисы созданы"
    print_warning "Для активации сервисов выполните:"
    print_warning "sudo cp telegram-bot.service /etc/systemd/system/"
    print_warning "sudo cp telegram-admin.service /etc/systemd/system/"
    print_warning "sudo systemctl daemon-reload"
    print_warning "sudo systemctl enable telegram-bot telegram-admin"
    print_warning "sudo systemctl start telegram-bot telegram-admin"
}

# Финальная информация
show_final_info() {
    print_message "Установка завершена!"
    echo ""
    echo -e "${BLUE}Следующие шаги:${NC}"
    echo "1. Отредактируйте файл .env с вашими настройками"
    echo "2. Запустите бота одним из способов:"
    echo "   - PM2: pm2 start ecosystem.config.js"
    echo "   - Systemd: sudo systemctl start telegram-bot telegram-admin"
    echo "   - Вручную: source venv/bin/activate && python bot.py"
    echo ""
    echo -e "${BLUE}Полезные команды:${NC}"
    echo "- Просмотр логов PM2: pm2 logs"
    echo "- Остановка PM2: pm2 stop all"
    echo "- Перезапуск PM2: pm2 restart all"
    echo "- Просмотр статуса systemd: sudo systemctl status telegram-bot"
    echo ""
    echo -e "${BLUE}Файлы конфигурации:${NC}"
    echo "- .env - переменные окружения"
    echo "- ecosystem.config.js - конфигурация PM2"
    echo "- telegram-bot.service - systemd сервис бота"
    echo "- telegram-admin.service - systemd сервис админ панели"
}

# Основная функция установки
main() {
    print_header
    check_root
    check_system
    create_venv
    install_python_deps
    install_pm2
    create_directories
    setup_env
    update_ecosystem_config
    set_permissions
    create_systemd_services
    show_final_info
}

# Запуск установки
main "$@" 