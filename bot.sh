#!/bin/bash

# Переменные
SERVICE_NAME="ytd_bot.service"  # Название службы для запуска/остановки
USER_NAME="root"        # Имя пользователя
BOT_FILE="ytd_bot.py"           # Название файла бота
BOT_PATH="/$USER_NAME/ytd/$BOT_FILE"  # Полный путь к файлу бота

# Функция для остановки бота
stop_bot() {
    systemctl stop $SERVICE_NAME
    echo "Бот остановлен."
}

# Функция для запуска бота
start_bot() {
    systemctl start $SERVICE_NAME
    echo "Бот запущен."
}

# Функция для получения статуса бота
status_bot() {
    systemctl status $SERVICE_NAME | grep -i "Active"
}

# Функция для отображения логов бота за последние сутки
log_bot() {
    journalctl -u $SERVICE_NAME --since "1 day ago" -n 20
}

# Функция для редактирования кода бота
edit_bot_code() {
    nano $BOT_PATH
    echo "Редактирование завершено. Возвращаемся в главное меню."
}

# Главное меню
while true; do
    clear
    echo "Выберите действие:"
    echo "1. Остановить бот"
    echo "2. Запустить бот"
    echo "3. Статус бота"
    echo "4. Лог работы бота"
    echo "5. Редактировать код бота"
    echo "6. Выход"
    read -p "Введите номер: " choice

    case $choice in
        1) stop_bot ;;
        2) start_bot ;;
        3) status_bot ;;
        4) log_bot ;;
        5) edit_bot_code ;;
        6) exit 0 ;;
        *) echo "Неверный выбор! Попробуйте снова." ;;
    esac
    read -p "Нажмите любую клавишу для продолжения..." -n 1 -s
done
