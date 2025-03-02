# ytd_bot
Этот телеграм бот позволяет скачивать видео с видеосервисов. Устанавливается на сервер Ubuntu 24+ или Debian 12+
Доступ к боту есть только у владельца (и у тех, чьи ID добавлены в код бота)

# УСТАНОВКА
В данной инструкции будем считать что вся работа делается из-под пользователя root.

* Создаем нужные папки
  
`/root/ytd` - корневая папка бота

`/root/ytd/cookies` - папка для куки

`/download` папка для скачивания файлов


* Скачиваем ytd_bot.py в папку /root/ytd

# НАСТРОЙКА
* Открываем на редактирование наш файл бота и правим конфигурацию
BOT_TOKEN = - токен телеграм бота, делаем бота через BotFather, инструкции есть в интернете
ALLOWED_USERS = ваш телеграм ID. Как его получить, инструкции тоже есть
DOWNLOAD_PATH = "/download" - папка для скачиваний файлов. Находется в корне корневой системы
COOKIES_PATH = "/root/ytd/cookies" - папка для куки файлов. Оставьте как есть
DOWNLOAD_BASE_URL = "https://ВАШДОМЕН.ru/1234567yourrandom" - здесь пишите свой домен и уникальный рандомный путь для скачивания. Сделайте его длинным, символов в 30 (рандомные буквы и цифры). Этот же путь мы будем указывать в настройках nginx.

* Настраиваем nginx (он уже долежн быть установлен, работать на 443 порту. Если порт другой - требуется перенастройка бота)
Открываем редактирование сайта в nginx (если у вас также в default настройки)  
`nano /etc/nginx/sites-available/default `

Добавляем в код секцию для скачивания перед последней закрывающей скобкой

```bash
    # Локация для скачивания файлов
    location /1234567yourrandom/ {
        alias /download/;  # Указываем путь к папке на сервере
        autoindex on;  # Включаем отображение списка файлов
        autoindex_exact_size off;  # Показываем размер файлов в удобном формате
        autoindex_localtime on;  # Показываем время файлов по локальному времени
        charset utf-8;  # Устанавливаем кодировку UTF-8
        # Если файл существует, отдаем его с оригинальным именем
        if (-f $request_filename) {
            add_header Content-Disposition "attachment; filename=$arg_filename";
        }
```
* Проверяем конфиг nginx и перезапускаем
`nginx -t`
`systemctl restart nginx`

* Настраиваем виртуальное окружение Python. Каждую строчку кода запускать отдельно
```bash
python3 -m venv mybotenv
source mybotenv/bin/activate
pip install aiogram yt-dlp aiohttp
deactivate
```

* Добавляем в Crontab автоудаление скачанных более чем 60 минут назад файлов
 `crontab -e`
```bash
0 * * * * find /download -type f -mmin +60 -exec rm -f {} \;
```

* Создаем сервис, добавляем в автозагрузку, запускаем бота.
`nano /etc/systemd/system/ytd_bot.service`
```bash
[Unit]
Description=Telegram Bot Service
After=network.target

[Service]
User=root
WorkingDirectory=/root/ytd
ExecStart=/root/mybotenv/bin/python3 /root/ytd/ytd_bot.py
Restart=always
RestartSec=5
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
```

Включаем автозагрузку: `systemctl enable ytd_bot.service`
Запускаем бот: `systemctl start ytd_bot.service`

# ИСПОЛЬЗОВАНИЕ
Для работы бота требуется плагин. Устанавливаем в браузер: https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc
Переходим на наш сайт, откуда будем скачивать видео, и с помощью плагина сохраняем куки файл в формате Netscape

Запускаем бот.
Загружаем куки файл в бот.
Скачиваем видео...

Для другого сайта/сервиса, потребуется соответствующий этому сайту куки файл.

Почему куки? Некоторые сервисы запрещают скачивать видео, если видят IP адрес хостинга.

Рекомендация: не используйте это в промышленных масштабах (платный бот для скачивания), иначе можно получить бан на IP адрес сервера. Бот подходит для частного использования исключительно в ознакомительных целях!
При работе с ботом требуется соблюдать законодательство страны проживания и не скачивать видео, запрещенные к скачиванию или запрещенные в вашей стране проживания! (а также в стране, где расположен сервер).

Код бота размещен исключительно в образовательных целях, не предназначен для коммерческого использования. Вся ответственность за использование кода бота на своем сервере, а также за соблюдение законодательства вашей страны (в том числе соблюдение правил скачивания видео) лежит исключительно на вас!
