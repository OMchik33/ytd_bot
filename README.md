# ОБНОВЛЕНИЯ:
**05.03.2025** - добавлена 3 кнопка, теперь 1 - скачать видео в лучшем качестве (нужна для скачивания шортсов или видео с различных видеосервисов), 2 - скачать с Туюба с выбором качества для скачивания, 3 - загрузить куки файл

# Список файлов
| Файл  | Описание  |
| ------------- | --------------------------------------- |
| ytd_bot.py  | Основной файл бота  |
| bot.sh  | Скрипт для управления службой бота, используется опционально (по желанию)  |

# Возможности бота
- Скачивание видео с видеосервисов (поддерживаемых программой yt-dlp)
- Выбор качества видео от 480p и выше
- Можно скачивать сразу, можно после загрузки куки файла (если видеосервис без него блокирует скачивание). Подробнее про куки смотри FAQ
- Таймер на скачивание 1 час, после этого Crontab удалит старые файлы.
- Файлы сохраняются с уникальным случайным именем для предотвращения ошибок, при скачивании возвращается оригинальное название, за вычетом запрещенных в названии файла символов
- Доступ к боту как через жестко прописанные Telegram ID, так и по уникальной ссылке с секретным кодом. База данных не используется, поэтому бот помнит тех, кто зашел по ссылке, пока работает. После перезапуска потребуется снова заходить по ссылке.
- Пример ссылки для входа в бот: https://t.me/mytg12345first_bot?start=secretcode12345

# Установка
**Условия для установки бота:**
1) Все делается из под пользователя root (инструкция для новичков, более опытные без проблем сделают из-под другого пользователя с помощью sudo)
2) К серверу прикреплен домен (платный или бесплатный)
3) Установлен nginx `apt-get install nginx`
4) Установлены SSL сертификаты для домена, прикрепленного к серверу, и прописаны в конфигурацию сайта nginx. Если сертификатов нет, используйте обычный незащищенный http
### Создаем нужные папки на сервере
- `/root/ytd` - корневая папка бота
- `/root/ytd/cookies` - папка для куки
- `/download` папка для скачивания файлов
### Скачиваем скрипт на свой сервер
Скачиваем `ytd_bot.py` в папку `/root/ytd`
# Настройка бота
1. **Открываем на редактирование наш файл бота и правим конфигурацию** `nano /root/ytd/ytd_bot.py`

| Переменная  | Значение  |
| ------------- | ---------------------------------- |
| BOT_TOKEN  | токен телеграм бота, делаем бота через @BotFather, инструкции есть в интернете  |
| ALLOWED_USERS  | ваш телеграм ID. Как его получить, инструкции тоже есть  |
| DOWNLOAD_BASE_URL  | "https://ВАШДОМЕН.ru/1234567yourrandom" - здесь пишите свой домен и уникальный рандомный путь для скачивания. Этот же путь, только без домена, мы будем указывать в настройках nginx.  |

2. **Настраиваем nginx** (он уже должен быть установлен, работать на 443 порту, получены SSL сертификаты. Если порт другой - требуется перенастройка бота)

Открываем редактирование сайта в nginx

`nano /etc/nginx/sites-available/default `
> default - настроки сайта по умолчанию. Если у вас другое название файла конфигурации, настраивайте его.
Добавляем в код секцию для скачивания перед закрывающей скобкой блока server {}

```bash
    # Локация для скачивания файлов
    location /1234567yourrandom/ {
        alias /download/;  # Указываем путь к папке на сервере
        autoindex off;  # Отключаем отображение списка файлов

    # Проверяем, существует ли файл
    if (-f $request_filename) {
        # Если файл существует, отдаем его с оригинальным именем
        add_header Content-Disposition "attachment; filename=$arg_filename";
    }
}
```

3. **Проверяем конфиг nginx и перезапускаем**
`nginx -t`
`systemctl restart nginx`

4. **Настраиваем виртуальное окружение Python.**
Запускаем команды ниже в терминале

|  Команда | Описание  |
| ------------ | ------------ |
| `python3 -m venv mybotenv`  | Создаем виртуальную среду mybotenv |
| `source mybotenv/bin/activate` | Активируем виртуальную среду |
| `pip install aiogram yt-dlp` | Устанавливаем необходимое ПО |
| `deactivate` | Выходим из виртуальной среды |

5. **Добавляем в Crontab автоудаление скачанных более чем 60 минут назад файлов**

`crontab -e` вводим эту команду в консоли для открытия списка задач Crontab

Добавляем туда код:
```bash
0 * * * * find /download -type f -mmin +60 -exec rm -f {} \;
```
Проверяем: `crontab -l`
Применяем изменения в планировщике: `systemctl restart cron`

6. **Создаем сервис, добавляем в автозагрузку, запускаем бота.**

- Вводим в консоли: `nano /etc/systemd/system/ytd_bot.service`

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
- Включаем автозагрузку: `systemctl enable ytd_bot.service`
- Запускаем бот: `systemctl start ytd_bot.service`

# FAQ
1. Для работы бота требуется установить [плагин](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc "плагин") в ваш браузер. (п.с.: без куки тоже может скачивать, если видеосервис позволит)
2. Переходим на сайт, откуда будем скачивать видео, и с помощью плагина сохраняем куки файл в формате Netscape. Крайне желательно иметь учетную запись на этом сайте и быть в ней авторизованным. Далее запускаем бот. Загружаем куки файл в бот. Скачиваем видео...
3. Для другого сайта/сервиса, потребуется соответствующий этому сайту куки файл.
4. Для каждого пользователя бот сохраняет свой собственный куки файл с уникальным названием.

При тестировании бота использовались следующие версии ПО:

| Программа  | Версия  |
| ------------ | ------------ |
| Python | 3.12.3 |
| aiogram  | 3.18.0 |
|  yt-dlp  | 2025.2.19 |

# ОТВЕТСТВЕННОСТЬ

1. Бот подходит для частного использования и исключительно в ознакомительных целях!
2. При работе с ботом требуется соблюдать законодательство страны проживания и не скачивать видео, запрещенные к скачиванию в стране проживания и в стране, где арендован VPS сервер!
3. Код бота размещен исключительно в образовательных целях, не предназначен для коммерческого использования.
4. Вся ответственность за использование кода бота на своем сервере, а также за соблюдение законодательства вашей страны (в том числе соблюдение правил скачивания видео) лежит исключительно на вас!
