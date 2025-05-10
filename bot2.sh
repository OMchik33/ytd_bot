#!/bin/bash

# ==================================================
# Скрипт управления и установки бота ytd_bot
# ==================================================

# Останавливать скрипт при любой ошибке
# set -e # Можно раскомментировать для более строгого режима, но добавим проверки после команд

# --- Переменные ---
SERVICE_NAME="ytd_bot.service"      # Название службы systemd для бота
USER_NAME="root"                    # Имя пользователя, от которого работает бот и лежит код (согласно пути /root/)

# Пути (согласно вашим уточнениям)
BASE_DIR="/root"
BOT_DIR="$BASE_DIR/ytd"                 # Директория, где лежат файлы бота и скрипт управления
BOT_FILE="$BOT_DIR/ytd_bot.py"      # Полный путь к файлу бота
COOKIES_DIR="$BOT_DIR/cookies"      # Директория для куки (нужна yt-dlp)
DOWNLOAD_DIR="/download"            # Директория для скачивания файлов
VENV_DIR="$BASE_DIR/mybotenv"           # Директория виртуального окружения
VENV_ACTIVATE="$VENV_DIR/bin/activate" # Полный путь к файлу активации виртуального окружения
NGINX_CONFIG_FILE="/etc/nginx/sites-available/default" # Полный путь к файлу конфигурации Nginx
SYSTEMD_SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME" # Путь к файлу службы systemd

# URL файла бота на GitHub (согласно вашим уточнениям)
GITHUB_BOT_URL="https://raw.githubusercontent.com/OMchik33/ytd_bot/refs/heads/main/ytd_bot.py"

# Команда cron для очистки папки загрузок
CRON_CLEANUP_COMMAND="*/10 * * * * find $DOWNLOAD_DIR -type f -mmin +10 -exec rm -f {} \\;"


# --- Вспомогательные функции ---

# Функция для проверки, запущены ли от root
check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "Ошибка: Для выполнения этой операции требуются права пользователя root."
        echo "Пожалуйста, запустите скрипт с использованием sudo или от пользователя root."
        return 1
    fi
    return 0
}

# Функция для безопасного ввода пароля/токена (не будет отображаться)
read_secret() {
    local prompt="$1"
    read -p "$prompt" -s SECRET_INPUT
    echo
    echo "$SECRET_INPUT" # Возвращаем введенное значение через stdout
}

# --- Функции управления ботом ---

# Функция для остановки бота
stop_bot() {
    echo "Остановка службы бота..."
    systemctl stop "$SERVICE_NAME"
    if [ $? -eq 0 ]; then
        echo "Бот успешно остановлен."
    else
        echo "Ошибка при остановке бота. Проверьте статус или логи."
    fi
}

# Функция для запуска бота
start_bot() {
    echo "Запуск службы бота..."
    systemctl start "$SERVICE_NAME"
    if [ $? -eq 0 ]; then
        echo "Бот успешно запущен."
    else
        echo "Ошибка при запуске бота. Проверьте статус или логи."
    fi
}

# Функция для получения полного статуса бота
status_bot() {
    echo "Получение статуса службы бота '$SERVICE_NAME':"
    systemctl status "$SERVICE_NAME"
    # Добавляем явную паузу после вывода статуса
    read -p "Нажмите любую клавишу для продолжения..." -n 1 -s
    echo # Добавляем новую строку после скрытого ввода
}

# Функция для отображения логов бота за последние сутки
log_bot() {
    echo "Последние 20 строк лога службы бота за последние 24 часа:"
    journalctl -u "$SERVICE_NAME" --since "1 day ago" -n 20
    # Добавляем явную паузу после вывода лога (если journalctl не использовал пейджер)
    read -p "Нажмите любую клавишу для продолжения..." -n 1 -s
    echo # Добавляем новую строку после скрытого ввода
}

# Функция для редактирования кода бота
edit_bot_code() {
    echo "Открытие файла кода бота для редактирования: $BOT_FILE"
    # Проверяем наличие nano, если нет - используем vi
    if command -v nano &> /dev/null; then
        nano "$BOT_FILE"
    elif command -v vi &> /dev/null; then
        vi "$BOT_FILE"
    else
        echo "Ошибка: Редакторы nano или vi не найдены. Невозможно редактировать файл."
        read -p "Нажмите любую клавишу для продолжения..." -n 1 -s
        echo
        return 1 # Возвращаем код ошибки
    fi

    echo "Редактирование завершено."
    read -p "Нажмите любую клавишу для продолжения..." -n 1 -s
    echo # Добавляем новую строку после скрытого ввода
}

# Функция для обновления компонентов
update_components() {
    echo "--- Обновление компонентов бота ---"
    echo "Рекомендуется остановить бота перед обновлением компонентов."
    read -p "Остановить бота сейчас? (y/n): " stop_choice
    if [[ "$stop_choice" =~ ^[Yy]$ ]]; then
        stop_bot
        sleep 2 # Даем время на остановку
    fi

    while true; do
        clear
        echo "--- Обновление компонентов бота ---"
        echo "Выберите компонент(ы) для обновления:"
        echo "1. yt-dlp"
        echo "2. aiogram"
        echo "3. ffmpeg (через apt)"
        echo "4. Обновить все (yt-dlp, aiogram, ffmpeg)"
        echo "5. Назад в главное меню"
        echo "------------------------------------"
        read -p "Введите номер: " update_choice

        case $update_choice in
            1) # Обновить yt-dlp
                echo "Обновление yt-dlp..."
                if [ -f "$VENV_ACTIVATE" ]; then
                    source "$VENV_ACTIVATE"
                    pip install --upgrade yt-dlp
                    deactivate
                    echo "Обновление yt-dlp завершено." || echo "Ошибка обновления yt-dlp."
                else
                    echo "Ошибка: Файл активации виртуального окружения не найден: $VENV_ACTIVATE"
                    echo "Невозможно обновить yt-dlp через pip."
                fi
                ;;
            2) # Обновить aiogram
                echo "Обновление aiogram..."
                if [ -f "$VENV_ACTIVATE" ]; then
                    source "$VENV_ACTIVATE"
                    pip install --upgrade aiogram
                    deactivate
                    echo "Обновление aiogram завершено." || echo "Ошибка обновления aiogram."
                else
                    echo "Ошибка: Файл активации виртуального окружения не найден: $VENV_ACTIVATE"
                    echo "Невозможно обновить aiogram через pip."
                fi
                ;;
            3) # Обновить ffmpeg
                echo "Обновление ffmpeg..."
                if ! check_root; then continue; fi # Проверка root внутри функции update_components
                apt update && apt install --only-upgrade ffmpeg
                echo "Обновление ffmpeg завершено." || echo "Ошибка обновления ffmpeg."
                ;;
            4) # Обновить все
                echo "Обновление всех компонентов..."
                 if ! check_root; then
                    echo "Пропущено обновление ffmpeg: Требуются права root."
                 fi
                # Обновление ffmpeg (требует root)
                if [ "$(id -u)" -eq 0 ]; then
                    echo "Обновление ffmpeg..."
                    apt update && apt install --only-upgrade ffmpeg
                    echo "ffmpeg обновлен." || echo "Ошибка обновления ffmpeg."
                else
                     echo "Пропущено обновление ffmpeg: Требуются права root."
                fi

                # Обновление yt-dlp и aiogram (через venv)
                if [ -f "$VENV_ACTIVATE" ]; then
                    echo "Обновление yt-dlp и aiogram через виртуальное окружение..."
                    source "$VENV_ACTIVATE"
                    pip install --upgrade yt-dlp aiogram
                    deactivate
                    echo "yt-dlp и aiogram обновлены." || echo "Ошибка обновления yt-dlp/aiogram."
                else
                    echo "Ошибка: Файл активации виртуального окружения не найден: $VENV_ACTIVATE"
                    echo "Пропущено обновление yt-dlp и aiogram."
                fi
                echo "Обновление всех компонентов завершено."
                ;;
            5) # Назад
                echo "Возврат в главное меню."
                break # Выход из внутреннего цикла update_components
                ;;
            *)
                echo "Неверный выбор! Попробуйте снова."
                ;;
        esac
        # Пауза после каждого действия обновления (кроме "Назад")
        if [ "$update_choice" != "5" ]; then
             read -p "Нажмите любую клавишу для продолжения..." -n 1 -s
             echo # Добавляем новую строку после скрытого ввода
        fi
    done

    # Предлагаем запустить бота, если он был остановлен
    read -p "Запустить бота после обновления? (y/n): " start_choice_after_update
    if [[ "$start_choice_after_update" =~ ^[Yy]$ ]]; then
        start_bot
    fi
}

# Функция для редактирования настроек Nginx
edit_nginx_config() {
    echo "Открытие файла конфигурации Nginx для редактирования: $NGINX_CONFIG_FILE"

    # Проверяем наличие nano, если нет - используем vi
    if command -v nano &> /dev/null; then
        nano "$NGINX_CONFIG_FILE"
    elif command -v vi &> /dev/null; then
        vi "$NGINX_CONFIG_FILE"
    else
        echo "Ошибка: Редакторы nano или vi не найдены. Невозможно редактировать файл."
        read -p "Нажмите любую клавишу для продолжения..." -n 1 -s
        echo
        return 1 # Возвращаем код ошибки
    fi

    echo "Редактирование завершено."

    read -p "Проверить конфигурацию Nginx и перезагрузить службу? (y/n): " check_reload_choice
    if [[ "$check_reload_choice" =~ ^[Yy]$ ]]; then
        echo "Проверка синтаксиса конфигурации Nginx..."
        nginx -t
        if [ $? -eq 0 ]; then
            echo "Синтаксис конфигурации Nginx в порядке."
            echo "Перезагрузка службы Nginx..."
            systemctl reload nginx
            if [ $? -eq 0 ]; then
                echo "Служба Nginx успешно перезагружена."
            else
                echo "Ошибка: Не удалось перезагрузить службу Nginx. Проверьте логи."
            fi
        else
            echo "Ошибка: Синтаксис конфигурации Nginx содержит ошибки. Служба не будет перезагружена."
        fi
    else
        echo "Проверка и перезагрузка Nginx пропущены."
        echo "Не забудьте проверить синтаксис (nginx -t) и перезагрузить службу (systemctl reload nginx) вручную, если вы внесли изменения."
    fi

    read -p "Нажмите любую клавишу для продолжения..." -n 1 -s
    echo # Добавляем новую строку после скрытого ввода
}

# --- Функция установки бота с нуля ---
install_bot() {
    clear
    echo "--- Установка бота ytd_bot ---"
    echo "Внимание! Для установки требуются права root и подключение к интернету."

    if ! check_root; then
        read -p "Нажмите любую клавишу для возврата в меню..." -n 1 -s
        echo
        return
    fi

    read -p "Начать установку бота? (y/n): " start_install
    if [[ ! "$start_install" =~ ^[Yy]$ ]]; then
        echo "Установка отменена."
        read -p "Нажмите любую клавишу для возврата в меню..." -n 1 -s
        echo
        return
    fi

    # --- Шаг 1: Создание директорий ---
    echo -e "\n--- Создание необходимых директорий ---"
    mkdir -p "$BOT_DIR" "$COOKIES_DIR" "$DOWNLOAD_DIR"
    if [ $? -ne 0 ]; then echo "Ошибка при создании директорий."; read -p "" -n 1 -s; echo; return; fi
    echo "Директории созданы: $BOT_DIR, $COOKIES_DIR, $DOWNLOAD_DIR"

    # --- Шаг 2: Скачивание файла бота ---
    echo -e "\n--- Скачивание файла бота с GitHub ---"
    # Проверяем наличие curl или wget
    if ! command -v curl &> /dev/null && ! command -v wget &> /dev/null; then
        echo "Ошибка: Не найдены утилиты curl или wget. Невозможно скачать файл бота."
        read -p "" -n 1 -s; echo; return;
    fi

    DOWNLOAD_CMD=""
    if command -v curl &> /dev/null; then
        DOWNLOAD_CMD="curl -o $BOT_FILE $GITHUB_BOT_URL"
    elif command -v wget &> /dev/null; then
        DOWNLOAD_CMD="wget -O $BOT_FILE $GITHUB_BOT_URL"
    fi

    eval "$DOWNLOAD_CMD"
    if [ $? -ne 0 ]; then echo "Ошибка при скачивании файла бота."; read -p "" -n 1 -s; echo; return; fi
    echo "Файл бота скачан: $BOT_FILE"
    chmod +x "$BOT_FILE" # Даем права на выполнение

    # --- Шаг 3: Настройка переменных в файле бота (первично) ---
    echo -e "\n--- Настройка переменных бота ---"
    BOT_TOKEN=$(read_secret "Введите BOT_TOKEN вашего Telegram бота: ")
    # Удаляем BOM, если он есть, чтобы sed работал корректно
    # Проверяем, существует ли файл перед sed
    if [ -f "$BOT_FILE" ]; then
        sed -i '1s/^\xEF\xBB\xBF//' "$BOT_FILE" # Удалить BOM
        # Заменяем BOT_TOKEN
        sed -i "s/BOT_TOKEN = \".*\"/BOT_TOKEN = \"$BOT_TOKEN\"/" "$BOT_FILE"
        if [ $? -ne 0 ]; then echo "Ошибка: Не удалось записать BOT_TOKEN в файл бота."; read -p "" -n 1 -s; echo; fi

        read -p "Введите ваш Telegram ID (число) или список ID через запятую (без пробелов): " ALLOWED_USERS_INPUT
        # Заменяем ALLOWED_USERS
        sed -i "s/ALLOWED_USERS = \[.*\]/ALLOWED_USERS = \[$ALLOWED_USERS_INPUT\]/" "$BOT_FILE"
        if [ $? -ne 0 ]; then echo "Ошибка: Не удалось записать ALLOWED_USERS в файл бота."; read -p "" -n 1 -s; echo; fi

        # DOWNLOAD_BASE_URL будет настроен позже после конфигурирования Nginx
        sed -i "s|DOWNLOAD_BASE_URL = \".*\"|DOWNLOAD_BASE_URL = \"\"|" "$BOT_FILE" # Сначала устанавливаем пустую строку
         if [ $? -ne 0 ]; then echo "Ошибка: Не удалось сбросить DOWNLOAD_BASE_URL в файле бота."; read -p "" -n 1 -s; echo; fi

        echo "Переменные BOT_TOKEN и ALLOWED_USERS записаны в файл бота."
    else
        echo "Ошибка: Файл бота ($BOT_FILE) не найден после скачивания."
        read -p "" -n 1 -s; echo; return;
    fi


    # --- Шаг 4: Установка Python, виртуальной среды и компонентов ---
    echo -e "\n--- Установка Python, виртуальной среды и компонентов ---"
    apt update && apt install -y python3 python3-venv ffmpeg
     if [ $? -ne 0 ]; then echo "Ошибка при установке пакетов (python3, python3-venv, ffmpeg) через apt."; read -p "" -n 1 -s; echo; return; fi
    echo "Python, python3-venv и ffmpeg установлены."

    echo "Создание виртуальной среды..."
    python3 -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then echo "Ошибка при создании виртуальной среды."; read -p "" -n 1 -s; echo; return; fi
    echo "Виртуальная среда создана: $VENV_DIR"

    echo "Установка компонентов бота (yt-dlp, aiogram) в виртуальную среду..."
    if [ -f "$VENV_ACTIVATE" ]; then
        source "$VENV_ACTIVATE"
        pip install --upgrade pip # Обновляем pip на всякий случай
        pip install yt-dlp aiogram
        deactivate
        if [ $? -ne 0 ]; then echo "Ошибка при установке пакетов pip (yt-dlp, aiogram)."; read -p "" -n 1 -s; echo; fi
        echo "Компоненты yt-dlp и aiogram установлены."
    else
        echo "Ошибка: Файл активации виртуального окружения ($VENV_ACTIVATE) не найден."
         read -p "" -n 1 -s; echo; return;
    fi

    # --- Шаг 5: Настройка Nginx ---
    echo -e "\n--- Настройка Nginx ---"
    if ! command -v nginx &> /dev/null; then
        echo "Nginx не найден. Установка Nginx..."
        apt update && apt install -y nginx
         if [ $? -ne 0 ]; then echo "Ошибка при установке Nginx."; read -p "" -n 1 -s; echo; return; fi
        echo "Nginx установлен."
    else
        echo "Nginx уже установлен."
    fi

    # --- Шаг 5a: Определение домена/IP и протокола ---
    DETECTED_DOMAIN=""
    USE_HTTPS="false"
    PROTOCOL="http"

    echo "Попытка определения домена из файла $NGINX_CONFIG_FILE..."
    # Ищем первую строку server_name в блоке server { ... }
    DETECTED_DOMAIN=$(awk '/^\s*server\s*{/,/^\s*}/{ /^\s*server_name\s+/ {print $2; exit} }' "$NGINX_CONFIG_FILE" | sed 's/;//')

    if [ -z "$DETECTED_DOMAIN" ] || [ "$DETECTED_DOMAIN" = "_" ]; then
        echo "Домен не найден в $NGINX_CONFIG_FILE или установлен как '_'. Попытка определить публичный IP..."
        # Используем ifconfig.me для получения публичного IP
        DETECTED_DOMAIN=$(curl -s ifconfig.me)
        if [ $? -ne 0 ] || [ -z "$DETECTED_DOMAIN" ]; then
            echo "Ошибка: Не удалось определить публичный IP (curl не установлен или сервис недоступен)."
            echo "Вам потребуется вручную настроить DOWNLOAD_BASE_URL в файле бота: $BOT_FILE"
            DETECTED_DOMAIN="YOUR_SERVER_IP_OR_DOMAIN" # Заглушка
        else
             echo "Определен публичный IP: $DETECTED_DOMAIN"
        fi
    else
        echo "Определен домен: $DETECTED_DOMAIN"
    fi

    # Проверяем, используется ли HTTPS в блоке server, где нашли server_name
    if awk '/^\s*server\s*{/,/^\s*}/{ /^\s*server_name\s+/ {found_server=1} /^\s*listen\s+443/ && found_server {found_https=1} /^\s*}/ && found_server {exit} END {exit !found_https}' "$NGINX_CONFIG_FILE"; then
         USE_HTTPS="true"
         PROTOCOL="https"
         echo "Определено использование HTTPS."
    else
         echo "HTTPS не определен для данного домена."
    fi

    DOWNLOAD_BASE_URL="${PROTOCOL}://${DETECTED_DOMAIN}/media"
    echo "Предполагаемый DOWNLOAD_BASE_URL для бота: $DOWNLOAD_BASE_URL"

    # --- Шаг 5b: Добавление location /media/ в конфиг Nginx ---
    echo -e "\n--- Добавление location /media/ в конфиг Nginx ---"
    LOCATION_BLOCK='
    location /media/ {
        alias /download/;  # Указываем путь к папке на сервере
        autoindex off;  # Отключаем отображение списка файлов

    # Проверяем, существует ли файл
    if (-f $request_filename) {
        # Если файл существует, отдаем его с оригинальным именем
        add_header Content-Disposition "attachment; filename=$arg_filename";
    }
}
'
    # Проверяем, существует ли файл конфига Nginx
    if [ -f "$NGINX_CONFIG_FILE" ]; then
        # Проверяем, нет ли уже такого location блока
        if grep -q "location /media/" "$NGINX_CONFIG_FILE"; then
            echo "Блок 'location /media/' уже существует в конфиге Nginx. Пропускаем добавление."
        else
            echo "Добавление блока 'location /media/' перед закрывающей скобкой '}' блока 'server'..."
            # Используем sed для вставки блока перед последней '}' в первом server {} блоке
            # Этот sed-скрипт ищет начало server {} блока, затем собирает строки до его конца '}'
            # и заменяет только эту последнюю '}' блока на новый текст location блока и саму '}'.
            # Это более устойчиво, чем вставлять перед любой последней '}'.
            sed -i '/^[[:space:]]*server[[:space:]]*{/ { :a; N; /^[[:space:]]*}/!ba; s/^[[:space:]]*}/'"$LOCATION_BLOCK"'\n}/' "$NGINX_CONFIG_FILE"
            if [ $? -ne 0 ]; then echo "Ошибка при добавлении блока location в конфиг Nginx."; read -p "" -n 1 -s; echo; fi
            echo "Блок 'location /media/' добавлен."
        fi
    else
        echo "Ошибка: Файл конфигурации Nginx ($NGINX_CONFIG_FILE) не найден."
        echo "Пожалуйста, настройте Nginx вручную."
         read -p "" -n 1 -s; echo;
    fi


    # --- Шаг 5c: Тест и перезагрузка Nginx ---
    echo -e "\n--- Тест и перезагрузка Nginx ---"
    nginx -t
    if [ $? -eq 0 ]; then
        echo "Синтаксис конфигурации Nginx в порядке. Перезагрузка службы..."
        systemctl reload nginx
        if [ $? -eq 0 ]; then
            echo "Служба Nginx успешно перезагружена."
        else
            echo "Ошибка: Не удалось перезагрузить службу Nginx. Проверьте логи Nginx."
            read -p "" -n 1 -s; echo;
        fi
    else
        echo "Ошибка: Синтаксис конфигурации Nginx содержит ошибки. Служба не будет перезагружена."
        echo "Пожалуйста, исправьте ошибки в $NGINX_CONFIG_FILE вручную."
        read -p "" -n 1 -s; echo; return;
    fi

    # --- Шаг 5d: Запись DOWNLOAD_BASE_URL в файл бота ---
    echo -e "\n--- Запись DOWNLOAD_BASE_URL в файл бота ---"
     if [ -f "$BOT_FILE" ]; then
        # Используем другой разделитель (|) для sed, так как URL содержит /
        sed -i "s|DOWNLOAD_BASE_URL = \".*\"|DOWNLOAD_BASE_URL = \"${DOWNLOAD_BASE_URL}\"|" "$BOT_FILE"
        if [ $? -ne 0 ]; then echo "Ошибка при записи DOWNLOAD_BASE_URL в файл бота."; read -p "" -n 1 -s; echo; fi
        echo "DOWNLOAD_BASE_URL записан в файл бота: $DOWNLOAD_BASE_URL"
    else
        echo "Ошибка: Файл бота ($BOT_FILE) не найден. Не удалось записать DOWNLOAD_BASE_URL."
         read -p "" -n 1 -s; echo;
    fi


    # --- Шаг 6: Настройка Cron ---
    echo -e "\n--- Настройка Cron для очистки папки загрузок ---"
    (crontab -l 2>/dev/null | grep -v -F "$CRON_CLEANUP_COMMAND"; echo "$CRON_CLEANUP_COMMAND") | crontab -
    if [ $? -ne 0 ]; then echo "Ошибка при добавлении/обновлении задачи Cron."; read -p "" -n 1 -s; echo; fi
    echo "Задача Cron для очистки $DOWNLOAD_DIR добавлена/обновлена."
    echo "Текущие задачи Cron пользователя root:"
    crontab -l 2>/dev/null || echo "Нет задач Cron."

    # --- Шаг 7: Настройка службы Systemd ---
    echo -e "\n--- Настройка службы Systemd ---"
    cat <<EOF > "$SYSTEMD_SERVICE_FILE"
[Unit]
Description=Telegram Bot Service
After=network.target

[Service]
User=$USER_NAME
WorkingDirectory=$BOT_DIR
ExecStart=$VENV_DIR/bin/python3 $BOT_FILE
Restart=always
RestartSec=5
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF
    if [ $? -ne 0 ]; then echo "Ошибка при создании файла службы Systemd."; read -p "" -n 1 -s; echo; return; fi
    echo "Файл службы Systemd создан: $SYSTEMD_SERVICE_FILE"

    echo "Перезагрузка демона Systemd, включение и запуск службы..."
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl start "$SERVICE_NAME"
     if [ $? -ne 0 ]; then echo "Ошибка при включении или запуске службы Systemd. Проверьте статус: systemctl status $SERVICE_NAME"; read -p "" -n 1 -s; echo; fi
    echo "Служба Systemd '$SERVICE_NAME' настроена, включена и запущена."

    # --- Шаг 8: Завершение установки и информация для пользователя ---
    echo -e "\n--- Установка завершена! ---"
    echo "Бот установлен и запущен как служба: $SERVICE_NAME"
    echo "Папка загрузок: $DOWNLOAD_DIR"
    echo "Папка бота: $BOT_DIR"
    echo "Виртуальная среда: $VENV_DIR"
    echo "DOWNLOAD_BASE_URL настроен на: $DOWNLOAD_BASE_URL"

    echo -e "\nЧтобы запустить бота в Telegram:"
    echo "1. Получите имя пользователя вашего бота через @BotFather."
    echo "2. Получите секретный код (secret_code) из переменной SECRET_CODE в файле бота ($BOT_FILE)."
    echo "3. Ссылка для запуска будет иметь вид:"
    echo "   https://t.me/<ИМЯ_ПОЛЬЗОВАТЕЛЯ_БОТА>?start=<секретный_код>"
    echo "   Например: https://t.me/MyYtdBot?start=abcdef123456"

    read -p "Нажмите любую клавишу для возврата в меню..." -n 1 -s
    echo
}


# --- Функция-заглушка для редактирования nginx (теперь не заглушка)
# Она уже реализована выше

# --- Главное меню ---
while true; do
    clear # Очищаем экран перед каждым отображением меню
    echo "--- Меню управления ботом ytd_bot ---"
    echo "Выберите действие:"
    echo "1. Остановить бот"
    echo "2. Запустить бот"
    echo "3. Статус бота"
    echo "4. Лог работы бота"
    echo "5. Редактировать код бота"
    echo "6. Обновить компоненты"
    echo "7. Редактировать настройки Nginx"
    echo "8. Установить бот (с нуля)" # Новый пункт
    echo "9. Выход" # Исправлен номер
    echo "------------------------------------"
    read -p "Введите номер: " choice

    case $choice in
        1) stop_bot ;;
        2) start_bot ;;
        3) status_bot ;; # status_bot теперь сам ждет ввода
        4) log_bot ;;   # log_bot (journalctl) сам ждет Q
        5) edit_bot_code ;; # edit_bot_code теперь сам ждет ввода
        6) update_components ;; # Вызов функции обновления
        7) edit_nginx_config ;; # Вызов функции редактирования Nginx
        8) install_bot ;; # Вызов новой функции установки
        9) echo "Выход из скрипта. До свидания!"; exit 0 ;; # Выход
        *) echo "Неверный выбор '$choice'! Пожалуйста, введите номер от 1 до 9." ;;
    esac

    # Пауза после выполнения большинства команд, кроме тех, что паузуются сами
    case $choice in
        3|4|5|6|7|8|9)
            # Эти функции либо паузуются сами, либо имеют внутренние паузы/циклы, либо выходят
            ;;
        *)
            read -p "Нажмите любую клавишу для продолжения..." -n 1 -s
            echo # Добавляем новую строку после скрытого ввода
            ;;
    esac

done
