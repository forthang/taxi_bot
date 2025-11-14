#!/bin/bash

# Быстрый установщик Telegram VIP Bot
# Для развертывания на новом сервере
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
    echo -e "${BLUE}  Быстрая установка Telegram VIP Bot${NC}"
    echo -e "${BLUE}================================${NC}"
}

# Проверка системы
check_system() {
    print_message "Проверка системы..."
    
    # Проверка ОС
    if [[ "$OSTYPE" != "linux-gnu"* ]]; then
        print_warning "Рекомендуется использовать Linux"
    fi
    
    # Проверка Python
    if ! command -v python3 &> /dev/null; then
        print_error "Python3 не найден. Установите Python 3.8+"
        print_message "Ubuntu/Debian: sudo apt update && sudo apt install python3 python3-pip python3-venv"
        print_message "CentOS/RHEL: sudo yum install python3 python3-pip"
        exit 1
    fi
    
    # Проверка pip
    if ! command -v pip3 &> /dev/null; then
        print_error "pip3 не найден. Установите pip3"
        exit 1
    fi
    
    # Проверка Node.js для PM2
    if ! command -v node &> /dev/null; then
        print_warning "Node.js не найден. PM2 не будет установлен."
        print_message "Для установки Node.js: curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt-get install -y nodejs"
        PM2_AVAILABLE=false
    else
        PM2_AVAILABLE=true
    fi
    
    print_message "Система готова к установке"
}

# Установка системных зависимостей
install_system_deps() {
    print_message "Установка системных зависимостей..."
    
    # Определяем дистрибутив
    if command -v apt-get &> /dev/null; then
        # Ubuntu/Debian
        sudo apt-get update
        sudo apt-get install -y python3-venv python3-pip curl wget git
    elif command -v yum &> /dev/null; then
        # CentOS/RHEL
        sudo yum update -y
        sudo yum install -y python3 python3-pip python3-venv curl wget git
    elif command -v dnf &> /dev/null; then
        # Fedora
        sudo dnf update -y
        sudo dnf install -y python3 python3-pip python3-venv curl wget git
    else
        print_warning "Неизвестный дистрибутив. Установите зависимости вручную."
    fi
    
    print_message "Системные зависимости установлены"
}

# Создание виртуального окружения
create_venv() {
    print_message "Создание виртуального окружения..."
    
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

# Установка Python зависимостей
install_python_deps() {
    print_message "Установка Python зависимостей..."
    
    source venv/bin/activate
    
    # Устанавливаем зависимости
    pip install python-telegram-bot==20.7
    pip install python-dotenv==1.0.0
    pip install aiohttp==3.9.1
    pip install flask==2.3.3
    pip install flask-login==0.6.3
    pip install werkzeug==2.3.7
    
    print_message "Python зависимости установлены"
}

# Установка PM2
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

# Настройка файла .env
setup_env() {
    print_message "Настройка переменных окружения..."
    
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            cp .env.example .env
            print_warning "Файл .env создан из .env.example"
            print_warning "ВАЖНО: Отредактируйте .env файл с вашими настройками!"
        else
            print_error "Файл .env.example не найден"
            exit 1
        fi
    else
        print_message "Файл .env уже существует"
    fi
}

# Обновление путей в конфигурации
update_configs() {
    print_message "Обновление конфигурации..."
    
    CURRENT_DIR=$(pwd)
    PYTHON_PATH="$CURRENT_DIR/venv/bin/python3"
    
    # Обновляем ecosystem.config.js
    if [ -f "ecosystem.config.js" ]; then
        sed -i "s|/opt/dmitriy/telegram-vip-bot|$CURRENT_DIR|g" ecosystem.config.js
        sed -i "s|/opt/dmitriy/telegram-vip-bot/venv/bin/python3|$PYTHON_PATH|g" ecosystem.config.js
        print_message "Конфигурация PM2 обновлена"
    fi
    
    # Обновляем systemd сервисы
    if [ -f "telegram-bot.service" ]; then
        USER=$(whoami)
        sed -i "s|User=.*|User=$USER|g" telegram-bot.service
        sed -i "s|WorkingDirectory=.*|WorkingDirectory=$CURRENT_DIR|g" telegram-bot.service
        sed -i "s|ExecStart=.*|ExecStart=$PYTHON_PATH bot.py|g" telegram-bot.service
        print_message "Systemd сервисы обновлены"
    fi
}

# Создание директорий
create_directories() {
    print_message "Создание необходимых директорий..."
    
    mkdir -p logs
    mkdir -p __pycache__
    
    print_message "Директории созданы"
}

# Установка прав доступа
set_permissions() {
    print_message "Установка прав доступа..."
    
    chmod +x bot.py admin_panel.py install.sh quick_install.sh
    
    print_message "Права доступа установлены"
}

# Тестовая проверка
test_installation() {
    print_message "Проверка установки..."
    
    source venv/bin/activate
    
    # Проверяем импорт основных модулей
    python3 -c "import telegram; import flask; import dotenv; print('Все модули импортированы успешно')"
    
    print_message "Установка проверена"
}

# Показ финальной информации
show_final_info() {
    print_message "Установка завершена!"
    echo ""
    echo -e "${BLUE}Следующие шаги:${NC}"
    echo "1. Отредактируйте файл .env с вашими настройками:"
    echo "   nano .env"
    echo ""
    echo "2. Запустите бота одним из способов:"
    echo ""
    if [ "$PM2_AVAILABLE" = true ]; then
        echo "   PM2 (рекомендуется):"
        echo "   pm2 start ecosystem.config.js"
        echo "   pm2 save"
        echo "   pm2 startup"
        echo ""
    fi
    echo "   Systemd:"
    echo "   sudo cp telegram-bot.service /etc/systemd/system/"
    echo "   sudo systemctl daemon-reload"
    echo "   sudo systemctl enable telegram-bot"
    echo "   sudo systemctl start telegram-bot"
    echo ""
    echo "   Вручную:"
    echo "   source venv/bin/activate"
    echo "   python bot.py"
    echo ""
    echo -e "${BLUE}Полезные команды:${NC}"
    if [ "$PM2_AVAILABLE" = true ]; then
        echo "- pm2 status - статус процессов"
        echo "- pm2 logs - просмотр логов"
        echo "- pm2 restart all - перезапуск"
    fi
    echo "- sudo systemctl status telegram-bot - статус systemd"
    echo "- tail -f logs/bot.log - просмотр логов бота"
    echo ""
    echo -e "${BLUE}Админ-панель:${NC}"
    echo "- URL: http://your-server:5000"
    echo "- Логин/пароль настраиваются в .env"
    echo ""
    echo -e "${YELLOW}ВАЖНО: Не забудьте настроить .env файл!${NC}"
}

# Основная функция
main() {
    print_header
    check_system
    install_system_deps
    create_venv
    install_python_deps
    install_pm2
    setup_env
    update_configs
    create_directories
    set_permissions
    test_installation
    show_final_info
}

# Запуск
main "$@" 