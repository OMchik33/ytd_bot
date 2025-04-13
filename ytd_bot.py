# [source: 1]
import os
import asyncio
import logging
import time
import re
import json
import hashlib
from urllib.parse import quote
from pathlib import Path
import datetime # для очистки старых запросов

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest # Импортируем ошибку

import yt_dlp

# --- Конфигурация ---
BOT_TOKEN = "ВСТАВЬТЕСЮДАТОКЕНБОТА" # Вставьте ваш токен
ALLOWED_USERS = [ВАШ_ТГ_ID] # Добавьте ID разрешенных пользователей
SPECIAL_CODE = "secretcode12345" # Секретный код для доступа к боту по ссылке
DOWNLOAD_PATH = Path("/download") # Используем Path для удобства
COOKIES_PATH = Path("/root/ytd/cookies") # Используем Path
DOWNLOAD_BASE_URL = "https://ВАШДОМЕН.ru/1234567yourrandom" # URL для доступа к скачанным файлам

# --- Включение логирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Создаем необходимые каталоги ---
DOWNLOAD_PATH.mkdir(parents=True, exist_ok=True)
COOKIES_PATH.mkdir(parents=True, exist_ok=True)

# --- Инициализация bot и dispatcher ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Хранилище для URL ---
# Ключ: message_id сообщения с кнопками
# Значение: {'url': str, 'timestamp': datetime}
active_url_requests = {}
REQUEST_TTL = datetime.timedelta(hours=1) # Время жизни запроса (1 час)

# --- Клавиатура ---
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        # [source: 2]
        [KeyboardButton(text="ℹ️ Инструкция"), KeyboardButton(text="🍪 Cookies")],
        [KeyboardButton(text="⬇️ Скачать видео")] # Объединенная кнопка
    ],
    resize_keyboard=True,
    persistent=True
)

# --- Хелперы (get_cookie_file, get_ydl_opts, sanitize_filename) ---
def get_cookie_file(user_id: int) -> Path | None:
    """Возвращает путь к файлу куки пользователя, если он существует."""
    cookie_file = COOKIES_PATH / f"cookies_{user_id}.txt"
    return cookie_file if cookie_file.exists() else None

def get_ydl_opts(user_id: int, format_selection: str = None) -> dict:
    """Возвращает словарь опций для yt-dlp."""
    opts = {
        # [source: 5]
        'outtmpl': str(DOWNLOAD_PATH / '%(id)s.%(ext)s'), # Путь для временного файла
        'quiet': False,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'retries': 5,
        'cookiefile': str(cookie_file) if (cookie_file := get_cookie_file(user_id)) else None,
        'http_headers': {
            # [source: 6]
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        },
        'concurrent_fragment_downloads': 5,
        'fragment_retries': 10,
        'merge_output_format': 'mp4', # Явно указываем MP4 как формат для слияния
    }
    if format_selection:
        opts['format'] = f'{format_selection}+ba/b'
    else:
        opts['format'] = 'bestvideo[ext=mp4]+bestaudio/best'
    return opts

def sanitize_filename(title: str) -> str:
    """Очищает имя файла от недопустимых символов."""
    # [source: 8]
    sanitized = re.sub(r'[<>:"/\\|?*]', '', title)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    max_len = 150
    if len(sanitized) > max_len:
        name_part = sanitized[:max_len].rsplit(' ', 1)[0]
        hash_part = hashlib.md5(title.encode('utf-8')).hexdigest()[:8]
        sanitized = f"{name_part}_{hash_part}"
    return sanitized

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1] == SPECIAL_CODE:
        if user_id not in ALLOWED_USERS:
            ALLOWED_USERS.append(user_id)
            logger.info(f"User {user_id} added via special code.")
            await message.answer("✅ Доступ разрешен! Добро пожаловать.")
        else:
            await message.answer("Вы уже в списке допущенных пользователей.")

    if user_id not in ALLOWED_USERS: # [source: 3]
        await message.answer("❌ Кто вы? Я вас не знаю! Доступ только по приглашению.")
        return

    await message.answer("Привет! Нажмите кнопку 'Скачать видео' и отправьте мне ссылку.", reply_markup=main_keyboard)

# --- Обработчики кнопок Reply ---
@dp.message(F.text == "ℹ️ Инструкция")
async def instruction(message: types.Message):
    """Показывает инструкцию"""
    if message.from_user.id not in ALLOWED_USERS: return # [source: 9]
    instruction_text = """
    *Инструкция для использования бота:*

    *⬇️ Скачать видео* - Нажмите эту кнопку, затем отправьте боту ссылку на видео.
      - Если доступно несколько вариантов качества (480p+), бот предложит выбрать.
      - Иначе скачает в наилучшем качестве (предпочтительно MP4).
      - Будет кнопка "🖼️ Обложка" для скачивания превью.

    *🍪 Cookies* - Используйте, если видео требует авторизации.
    1. Установите [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc).
    2. Зайдите в аккаунт на нужном сайте.
    3. Нажмите иконку расширения -> Export (формат **Netscape**).
    4. Нажмите "🍪 Cookies" в боте -> отправьте `.txt` файл.
    5. Попробуйте скачать видео снова.
    """ # [source: 10] [source: 11] [source: 12] [source: 13]
    await message.answer(instruction_text, parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(F.text == "🍪 Cookies")
async def cookies_prompt(message: types.Message):
    """Запрашивает файл куки"""
    if message.from_user.id not in ALLOWED_USERS: return
    cookies_text = "Отправьте мне файл `cookies.txt`, экспортированный из расширения (в формате Netscape)." # [source: 14]
    await message.answer(cookies_text, parse_mode="Markdown")

@dp.message(F.text == "⬇️ Скачать видео")
async def download_video_prompt(message: types.Message):
    """Запрашивает ссылку на видео"""
    if message.from_user.id not in ALLOWED_USERS: return
    await message.answer("Отправьте ссылку на видео для скачивания.")

# --- Обработчик загрузки куки файла ---
@dp.message(F.document & F.document.file_name.endswith('.txt'))
async def handle_cookie_file(message: types.Message):
    """Обрабатывает загрузку файла куки."""
    if message.from_user.id not in ALLOWED_USERS: return
    if not message.document: return

    file_id = message.document.file_id
    file_info = await bot.get_file(file_id)
    file_path_tg = file_info.file_path
    destination = COOKIES_PATH / f"cookies_{message.from_user.id}.txt"

    try:
        await bot.download_file(file_path_tg, destination=str(destination))
        logger.info(f"Cookies file saved for user {message.from_user.id}")
        # [source: 4]
        await message.answer("✅ Куки-файл успешно загружен и сохранен!")
    except Exception as e:
        logger.error(f"Ошибка при сохранении куки файла для {message.from_user.id}: {e}")
        await message.answer("❌ Не удалось сохранить куки-файл.")

# --- Основная логика скачивания ---
async def download_media(message: types.Message, url: str, user_id: int, format_id: str = None):
    """Скачивает медиафайл по URL с заданными опциями."""
    status_msg = await message.answer("⏳ Получение информации о видео...") # Отправляем новое сообщение о статусе
    ydl_opts = get_ydl_opts(user_id, format_selection=format_id)
    download_success = False # Флаг успешного скачивания
    info = None # Для хранения информации о видео

    try:
        # Этап 1: Извлечение информации (если нужно) и скачивание
        await status_msg.edit_text("🔄 Скачиваю видео... Это может занять некоторое время.")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                # Извлекаем инфо перед скачиванием чтобы знать id и ext
                info = ydl.extract_info(url, download=False)
                file_id = info.get('id', 'unknown_id')
                file_ext = info.get('ext', 'mp4')
                # Обновляем шаблон имени файла с правильным расширением
                # Важно: yt-dlp может изменить расширение при конвертации/скачивании другого формата
                ydl.params['outtmpl']['default'] = str(DOWNLOAD_PATH / f'{file_id}.%(ext)s')

                # Теперь скачиваем
                ydl.download([url])
                download_success = True # Отмечаем успешное скачивание

                # После успешного скачивания, нужно снова получить инфо, т.к. ydl.download может изменить info
                # Или найти скачанный файл по ID
                original_id = info.get('id', 'unknown_id')
                temp_file_path = None
                # Ищем файл с ID и любым расширением
                found_files = list(DOWNLOAD_PATH.glob(f"{original_id}.*"))
                if found_files:
                    temp_file_path = found_files[0]
                    original_ext = temp_file_path.suffix[1:] # Получаем реальное расширение скачанного файла
                    logger.info(f"Найден скачанный файл: {temp_file_path}")
                else:
                    # Если не нашли - пытаемся использовать исходное расширение (менее надежно)
                    original_ext = info.get('ext', 'mp4')
                    temp_file_path = DOWNLOAD_PATH / f"{original_id}.{original_ext}"
                    logger.warning(f"Скачанный файл не найден по ID '{original_id}', пробуем исходное расширение: {temp_file_path}")


                if not temp_file_path or not temp_file_path.exists():
                    logger.error(f"Файл не найден после скачивания: ID={original_id}")
                    await status_msg.edit_text(f"❌ Ошибка: Не найден скачанный файл после завершения процесса.")
                    return

            except yt_dlp.utils.DownloadError as e:
                error_message = f"❌ Ошибка скачивания:\n`{e}`"
                if "confirm your age" in str(e).lower():
                    error_message += "\n\nℹ️ Возможно, видео имеет возрастное ограничение. Попробуйте загрузить Cookies."
                elif "private video" in str(e).lower():
                    error_message += "\n\nℹ️ Это приватное видео. Убедитесь, что у вас есть доступ и загружены Cookies."
                elif "premiere" in str(e).lower():
                    error_message = "❌ Ошибка: Видео является премьерой и еще не доступно для скачивания."
                elif "unavailable" in str(e).lower():
                    error_message = f"❌ Ошибка: Видео недоступно ({e})."
                await status_msg.edit_text(error_message, parse_mode="Markdown")
                return # Прекращаем выполнение
            except Exception as e:
                logger.error(f"Неожиданная ошибка yt-dlp на этапе скачивания для {url}: {e}")
                raise # Перевыбрасываем

        # Этап 2: Переименование и формирование ссылки (только если скачивание успешно)
        if download_success and temp_file_path and temp_file_path.exists():
            title = info.get('title', 'video') if info else 'video'
            # Создание уникального имени файла для хранения
            slug = hashlib.md5(title.encode('utf-8') + str(user_id).encode()).hexdigest()[:10]
            timestamp = int(time.time())
            # [source: 7]
            unique_filename = f"{slug}_{timestamp}.{original_ext}"
            final_file_path = DOWNLOAD_PATH / unique_filename

            try:
                temp_file_path.rename(final_file_path)
                logger.info(f"Файл переименован в {final_file_path}")
            except OSError as e:
                logger.error(f"Ошибка переименования файла {temp_file_path} в {final_file_path}: {e}")
                await status_msg.edit_text(f"❌ Ошибка файловой системы при сохранении видео.")
                return

            # Создание имени файла для пользователя
            original_name_for_user = f"{sanitize_filename(title)}.{original_ext}"
            # [source: 8]
            download_url = f"{DOWNLOAD_BASE_URL}/{quote(unique_filename)}?filename={quote(original_name_for_user)}"

            await status_msg.edit_text(
                f"✅ **Готово!**\n\n"
                f"🎬 *{title}*\n\n"
                f"🔗 [Скачать файл]({download_url})\n\n"
                f"_Ссылка действительна ограниченное время._",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        elif download_success and not temp_file_path:
            logger.error(f"Скачивание помечено успешным, но файл не найден для URL {url}")
            await status_msg.edit_text("❌ Внутренняя ошибка: скачанный файл не найден.")

    except yt_dlp.utils.ExtractorError as e:
        logger.warning(f"Ошибка извлечения для {url}: {e}")
        await status_msg.edit_text(f"❌ Ошибка: Не удалось извлечь информацию для этой ссылки.\n`{e}`")
    except yt_dlp.utils.DownloadError as e: # Ловим ошибки скачивания еще раз (могут быть на этапе getinfo)
        logger.error(f"Ошибка скачивания yt-dlp (этап info) для {url}: {e}")
        await status_msg.edit_text(f"❌ Ошибка при получении информации о видео:\n`{e}`")
    except Exception as e:
        logger.exception(f"Критическая ошибка при обработке {url} для пользователя {user_id}: {e}")
        await status_msg.edit_text(f"❌ Произошла непредвиденная ошибка:\n`{e}`")


# --- Обработчик ссылок ---
@dp.message(F.text.regexp(r'https?://\S+'))
async def handle_url(message: types.Message):
    """Обрабатывает полученную ссылку на видео."""
    if message.from_user.id not in ALLOWED_USERS: return
    if not message.text: return

    url = message.text
    user_id = message.from_user.id
    # Используем answer, чтобы получить message_id для хранения URL
    status_msg = await message.answer("🔎 Анализирую ссылку...")
    message_id_for_buttons = status_msg.message_id # ID сообщения, где будут кнопки

    # --- Очистка старых запросов ---
    now = datetime.datetime.now(datetime.timezone.utc)
    expired_keys = [
        k for k, v in active_url_requests.items()
        if now - v['timestamp'] > REQUEST_TTL
    ]
    for key in expired_keys:
        active_url_requests.pop(key, None)
    # --- ---

    try:
        # Извлекаем только информацию
        ydl_opts_info = get_ydl_opts(user_id)
        ydl_opts_info['skip_download'] = True
        ydl_opts_info['quiet'] = True
        # [source: 16]
        ydl_opts_info['no_warnings'] = True

        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get('formats', [])
        thumbnail_url = info.get('thumbnail')
        title = info.get('title', 'видео')

        # --- Логика выбора качества ---
        quality_buttons = []
        unique_qualities = {}

        # [source: 17]
        for f in formats:
            height = f.get('height')
            format_id = f.get('format_id')
            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')

            if height and height >= 480 and vcodec != 'none' and format_id:
                if acodec != 'none' or f.get('protocol') in ('https', 'http'):
                    quality_label = f"{height}p"
                    if quality_label not in unique_qualities:
                        # [source: 18]
                        unique_qualities[quality_label] = {
                            "format_id": format_id,
                            "height": height
                        }

        sorted_qualities = sorted(unique_qualities.items(), key=lambda item: item[1]['height'], reverse=True)

        # --- Формирование клавиатуры ---
        builder = InlineKeyboardBuilder()
        # [source: 19]
        for label, data in sorted_qualities:
            # УКОРОЧЕННЫЕ ДАННЫЕ!
            callback_data = json.dumps({
                "a": "d", # action: download
                "f": data['format_id'] # format_id
            })
            # Проверка длины callback_data (Telegram лимит ~64 байта)
            if len(callback_data.encode('utf-8')) <= 64:
                builder.button(text=f"🎬 {label}", callback_data=callback_data)
            else:
                logger.warning(f"Callback data для {label} ({data['format_id']}) слишком длинное: {len(callback_data.encode('utf-8'))} байт. Кнопка пропущена.")


        # Добавляем кнопку обложки
        if thumbnail_url:
            # УКОРОЧЕННЫЕ ДАННЫЕ!
            callback_data_thumb = json.dumps({"a": "t"}) # action: thumbnail
            if len(callback_data_thumb.encode('utf-8')) <= 64:
                builder.button(text="🖼️ Обложка", callback_data=callback_data_thumb)

        # Компоновка
        # Исправление: Преобразуем builder.buttons в список перед получением длины
        quality_button_count = len(list(builder.buttons)) - (1 if thumbnail_url else 0) # Считаем только кнопки качества
        if quality_button_count > 0 :
            builder.adjust(2 if quality_button_count > 1 else 1) # По 2 в ряд, если их больше 1


        # --- Отправка сообщения ---
        keyboard_markup = builder.as_markup() if builder.buttons else None

        # Сохраняем URL перед отправкой кнопок
        active_url_requests[message_id_for_buttons] = {
            'url': url,
            'timestamp': datetime.datetime.now(datetime.timezone.utc)
        }

        if quality_button_count > 1: # Предлагаем выбор
            await status_msg.edit_text(
                f"Найдено видео: *{title}*\n\nВыберите качество для скачивания:",
                reply_markup=keyboard_markup,
                parse_mode="Markdown"
            )
        elif quality_button_count == 1: # Только один вариант
            single_format_id = sorted_qualities[0][1]['format_id']
            await status_msg.edit_text(
                f"Найдено видео: *{title}*\n\nДоступно только одно качество >= 480p. Начинаю скачивание.",
                reply_markup=keyboard_markup, # Оставляем кнопку обложки, если есть
                parse_mode="Markdown"
            )
            # Тут не вызываем download_media, т.к. пользователь должен нажать кнопку (или обложку)
            # Если бы хотели скачать автоматом, нужно было бы вызвать тут:
            # active_url_requests.pop(message_id_for_buttons, None) # Очищаем перед авто-скачиванием
            # await download_media(message, url, user_id, format_id=single_format_id)
        else: # Нет подходящих форматов >= 480p
            await status_msg.edit_text(
                f"Найдено видео: *{title}*\n\nНе найдено форматов >= 480p. Скачиваю в наилучшем доступном качестве.",
                reply_markup=keyboard_markup, # Оставляем кнопку обложки, если есть
                parse_mode="Markdown"
            )
            # Скачиваем best по умолчанию, но сначала очищаем state
            active_url_requests.pop(message_id_for_buttons, None)
            await download_media(message, url, user_id) # Скачиваем best

    except TelegramBadRequest as e:
        # Ловим конкретно ошибку невалидных данных кнопки
        if "BUTTON_DATA_INVALID" in str(e):
            logger.error(f"Ошибка BUTTON_DATA_INVALID при создании кнопок для URL: {url}. Данные: {builder.export()}")
            await status_msg.edit_text("❌ Ошибка: Не удалось сформировать кнопки выбора качества (данные слишком длинные). Попробуйте другую ссылку.")
            active_url_requests.pop(message_id_for_buttons, None) # Очищаем state
        else:
            logger.exception(f"Ошибка Telegram API в handle_url для {url}: {e}")
            await status_msg.edit_text(f"❌ Ошибка Telegram API: {e}")
    except yt_dlp.utils.ExtractorError as e:
        logger.warning(f"Ошибка извлечения для {url} в handle_url: {e}")
        await status_msg.edit_text(f"❌ Ошибка: Не удалось извлечь информацию для этой ссылки.\n`{e}`")
        active_url_requests.pop(message_id_for_buttons, None)
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Ошибка yt-dlp (info extraction) для {url}: {e}")
        await status_msg.edit_text(f"❌ Ошибка при получении информации о видео:\n`{e}`")
        active_url_requests.pop(message_id_for_buttons, None)
    except Exception as e:
        logger.exception(f"Критическая ошибка в handle_url для {url} пользователя {message.from_user.id}: {e}")
        await status_msg.edit_text(f"❌ Произошла непредвиденная ошибка при обработке ссылки:\n`{e}`")
        active_url_requests.pop(message_id_for_buttons, None) # Очищаем state при любой ошибке


# --- Обработчик нажатий Inline кнопок ---
# [source: 20]
@dp.callback_query(F.data.startswith('{'))
async def handle_callback_query(query: types.CallbackQuery):
    """Обрабатывает нажатия на inline-кнопки."""
    user_id = query.from_user.id
    if user_id not in ALLOWED_USERS:
        await query.answer("Доступ запрещен.", show_alert=True)
        return

    message_id = query.message.message_id
    # Извлекаем URL из нашего временного хранилища
    request_data = active_url_requests.get(message_id)

    if not request_data:
        await query.answer("❌ Запрос устарел или не найден. Пожалуйста, отправьте ссылку заново.", show_alert=True)
        # Попытаемся убрать кнопки у старого сообщения
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass # Игнорируем ошибки редактирования старых сообщений
        return

    url = request_data['url']
    # Очищаем state СРАЗУ после извлечения URL, чтобы избежать повторных нажатий
    active_url_requests.pop(message_id, None)

    try:
        data = json.loads(query.data)
        action = data.get("a") # Используем укороченное 'a'

        # Убираем кнопки после нажатия на любую из них
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception as edit_error:
            logger.warning(f"Не удалось убрать кнопки у сообщения {message_id}: {edit_error}")


        if action == "d": # download
            format_id = data.get("f") # Используем укороченное 'f'
            if not format_id:
                await query.answer("❌ Ошибка: Не указан формат.", show_alert=True)
                return

            await query.answer(f"🚀 Запускаю скачивание...")
            await download_media(query.message, url, user_id, format_id=format_id)

        elif action == "t": # thumbnail
            await query.answer("🖼️ Загружаю обложку...")
            # Передаем query.message чтобы ответ был в том же чате
            await send_thumbnail(query.message, url, user_id)

        else:
            await query.answer("Неизвестное действие.", show_alert=True)
            logger.warning(f"Получено неизвестное действие '{action}' в callback_data для сообщения {message_id}")

    except json.JSONDecodeError:
        logger.warning(f"Не удалось декодировать JSON из callback_data: {query.data} для сообщения {message_id}")
        await query.answer("❌ Ошибка обработки данных кнопки.", show_alert=True)
        active_url_requests.pop(message_id, None) # Очистка state при ошибке
    except Exception as e:
        logger.exception(f"Ошибка в handle_callback_query для пользователя {user_id}, сообщения {message_id}: {e}")
        # [source: 21]
        await query.answer("❌ Произошла ошибка при обработке вашего запроса.", show_alert=True)
        active_url_requests.pop(message_id, None) # Очистка state при ошибке


# --- Отправка обложки ---
async def send_thumbnail(message: types.Message, url: str, user_id: int):
    """Извлекает URL обложки и отправляет ее пользователю."""
    # Не используем status_msg, отвечаем прямо на исходное сообщение
    try:
        ydl_opts_info = get_ydl_opts(user_id)
        ydl_opts_info['skip_download'] = True
        ydl_opts_info['quiet'] = True
        ydl_opts_info['no_warnings'] = True

        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)

        thumbnail_url = info.get('thumbnail')
        title = info.get('title', 'video')

        if thumbnail_url:
            # Отправляем как новое сообщение в чат
            await message.answer_photo(
                photo=thumbnail_url,
                caption=f"Обложка для видео:\n*{title}*" if title else "Обложка для видео",
                parse_mode="Markdown"
            )
        else:
            # Отправляем как новое сообщение в чат
            await message.answer("❌ Не удалось найти обложку для этого видео.")

    except Exception as e:
        logger.error(f"Ошибка при получении обложки для {url}: {e}")
        # Отправляем как новое сообщение в чат
        await message.answer(f"❌ Не удалось получить обложку: {e}")


# --- Запуск бота ---
async def main():
    """Основная функция запуска бота."""
    try:
        logger.info("Запуск бота...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        logger.info("Бот остановлен.")
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске/работе бота: {e}", exc_info=True)
    finally:
        await bot.session.close()
        logger.info("Сессия бота закрыта.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")
