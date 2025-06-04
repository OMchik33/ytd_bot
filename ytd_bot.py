import os
import asyncio
import logging
import time
import re
import json
import hashlib
from urllib.parse import quote
from pathlib import Path
import datetime
# --- Загрузка переменных из .env файла ---
from dotenv import load_dotenv
load_dotenv() # Загружает переменные из .env файла в переменные окружения

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
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Обработка ALLOWED_USERS: из строки "id1,id2" в список [id1, id2]
allowed_users_str = os.getenv("ALLOWED_USERS", "") # Значение по умолчанию - пустая строка
ALLOWED_USERS = [int(user_id.strip()) for user_id in allowed_users_str.split(',') if user_id.strip().isdigit()]

SPECIAL_CODE = os.getenv("SPECIAL_CODE")
DOWNLOAD_PATH = Path(os.getenv("DOWNLOAD_PATH", "/download")) # Значение по умолчанию, если не найдено
COOKIES_PATH = Path(os.getenv("COOKIES_PATH", "/root/ytd/cookies")) # Пример другого значения по умолчанию
DOWNLOAD_BASE_URL = os.getenv("DOWNLOAD_BASE_URL")

# Проверка, что BOT_TOKEN загружен
if not BOT_TOKEN:
    logger.critical("Ошибка: BOT_TOKEN не найден! Убедитесь, что он задан в .env файле.")
    exit() # Или raise Exception("BOT_TOKEN not found")

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
# Значение: {'url': str, 'timestamp': datetime, 'title': str, 'thumbnail_url': str | None }
active_url_requests = {}
REQUEST_TTL = datetime.timedelta(hours=1) # Время жизни запроса (1 час)

# --- Клавиатура ---
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        # 
        [KeyboardButton(text="ℹ️ Инструкция"), KeyboardButton(text="🍪 Cookies")],
        [KeyboardButton(text="⬇️ Скачать видео")] # Объединенная кнопка
    ],
    resize_keyboard=True,
    persistent=True
)

# --- Хелперы ---
def get_cookie_file(user_id: int) -> Path | None:
    """Возвращает путь к файлу куки пользователя, если он существует."""
    cookie_file = COOKIES_PATH / f"cookies_{user_id}.txt"
    return cookie_file if cookie_file.exists() else None

def get_ydl_opts(user_id: int, format_selection: str = None, download_type: str = 'video') -> dict:
    """Возвращает словарь опций для yt-dlp."""
    opts = {
        # 
        'outtmpl': str(DOWNLOAD_PATH / '%(id)s.%(ext)s'), # Путь для временного файла
        'quiet': False,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'retries': 5,
        'cookiefile': str(cookie_file) if (cookie_file := get_cookie_file(user_id)) else None,
        'http_headers': {
            # 
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        },
        'concurrent_fragment_downloads': 5,
        'fragment_retries': 10,
    }
    if download_type == 'audio':
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192', # Качество MP3
        }]
        opts['merge_output_format'] = None # Не нужно для извлечения аудио
        # yt-dlp сам изменит расширение на mp3 после postprocessing
        # outtmpl остается '%(id)s.%(ext)s', yt-dlp обработает это.
    elif download_type == 'video':
        opts['merge_output_format'] = 'mp4' # Явно указываем MP4 как формат для слияния
        if format_selection:
            opts['format'] = f'{format_selection}+ba/b' # ba - bestaudio, b - best
        else:
            opts['format'] = 'bestvideo[ext=mp4]+bestaudio/best' # Предпочитаем mp4 контейнер
    return opts

def sanitize_filename(title: str) -> str:
    """Очищает имя файла от недопустимых символов."""
    # 
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

    if user_id not in ALLOWED_USERS: # 
        await message.answer("❌ Кто вы? Я вас не знаю! Доступ только по приглашению.")
        return

    await message.answer("Привет! Нажмите кнопку 'Скачать видео' и отправьте мне ссылку.", reply_markup=main_keyboard)

# --- Обработчики кнопок Reply ---
@dp.message(F.text == "ℹ️ Инструкция")
async def instruction(message: types.Message):
    """Показывает инструкцию"""
    if message.from_user.id not in ALLOWED_USERS: return # 
    instruction_text = """
    *Инструкция для использования бота:*

    *⬇️ Скачать видео* - Нажмите эту кнопку, затем отправьте боту ссылку на видео.
      - Бот предложит выбрать качество видео (если доступно несколько вариантов >= 480p).
      - Будет кнопка "🎵 Скачать MP3" для извлечения аудиодорожки.
      - Будет кнопка "🖼️ Обложка" для скачивания превью.
      - Если подходящих видеоформатов нет, бот скачает видео в наилучшем доступном качестве.

    *🍪 Cookies* - Используйте, если видео требует авторизации.
    1. Установите [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc).
    2. Зайдите в аккаунт на нужном сайте.
    3. Нажмите иконку расширения -> Export (формат **Netscape**).
    4. Нажмите "🍪 Cookies" в боте -> отправьте `.txt` файл.
    5. Попробуйте скачать видео снова.
    """ # 
    await message.answer(instruction_text, parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(F.text == "🍪 Cookies")
async def cookies_prompt(message: types.Message):
    """Запрашивает файл куки"""
    if message.from_user.id not in ALLOWED_USERS: return
    cookies_text = "Отправьте мне файл `cookies.txt`, экспортированный из расширения (в формате Netscape)." # 
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
        # 
        await message.answer("✅ Куки-файл успешно загружен и сохранен!")
    except Exception as e:
        logger.error(f"Ошибка при сохранении куки файла для {message.from_user.id}: {e}")
        await message.answer("❌ Не удалось сохранить куки-файл.")

# --- Основная логика скачивания ---
async def download_media(message: types.Message, url: str, user_id: int,
                         original_title: str, # Добавляем original_title
                         format_id: str = None, download_type: str = 'video'):
    """Скачивает медиафайл по URL с заданными опциями."""
    status_msg_text = "⏳ Получение информации о медиа..."
    if download_type == 'audio':
        status_msg_text = "⏳ Получение информации об аудио..."
    elif download_type == 'video':
        status_msg_text = "⏳ Получение информации о видео..."

    status_msg = await message.answer(status_msg_text) # Отправляем новое сообщение о статусе
    ydl_opts = get_ydl_opts(user_id, format_selection=format_id, download_type=download_type)
    download_success = False
    info_after_download = None # Для хранения информации о видео/аудио после скачивания

    try:
        download_action_text = "🔄 Скачиваю видео... Это может занять некоторое время."
        if download_type == 'audio':
            download_action_text = "🔄 Скачиваю аудио (MP3)... Это может занять некоторое время."
        await status_msg.edit_text(download_action_text)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                # Сначала извлекаем инфо, чтобы знать id для формирования имени файла до скачивания.
                # Это важно, так как outtmpl использует %(id)s.
                pre_info = ydl.extract_info(url, download=False)
                file_id_for_tmpl = pre_info.get('id', 'unknown_id')

                # Обновляем шаблон имени файла с правильным ID до фактического скачивания
                # yt-dlp использует 'default' ключ в словаре outtmpl, если outtmpl - словарь.
                # Если outtmpl - строка, как у нас, это изменение не требуется таким образом,
                # но полезно иметь file_id_for_tmpl для поиска файла.
                # ydl.params['outtmpl'] = str(DOWNLOAD_PATH / f'{file_id_for_tmpl}.%(ext)s') # Уже установлено в get_ydl_opts

                # Теперь скачиваем и одновременно получаем инфо о скачанном файле
                info_after_download = ydl.extract_info(url, download=True)
                download_success = True

                # Ищем скачанный файл
                # yt-dlp мог изменить расширение, особенно для аудио (на mp3)
                # или если запрошенный формат не был доступен и был выбран другой.
                original_id = info_after_download.get('id', file_id_for_tmpl) # Используем ID из info_after_download если есть
                temp_file_path = None
                downloaded_filepath_from_info = info_after_download.get('requested_downloads', [{}])[0].get('filepath')

                if downloaded_filepath_from_info and Path(downloaded_filepath_from_info).exists():
                    temp_file_path = Path(downloaded_filepath_from_info)
                    logger.info(f"Найден скачанный файл напрямую из info: {temp_file_path}")
                else: # Запасной вариант: ищем по ID
                    logger.warning(f"Скачанный файл не найден по 'filepath' в info. Ищем по ID: {original_id}")
                    found_files = list(DOWNLOAD_PATH.glob(f"{original_id}.*"))
                    if found_files:
                        temp_file_path = found_files[0] # Берем первый найденный, предполагая, что он нужный
                        logger.info(f"Найден скачанный файл по ID: {temp_file_path}")
                    else:
                        logger.error(f"Файл не найден после скачивания: ID={original_id}")
                        await status_msg.edit_text(f"❌ Ошибка: Не найден скачанный файл после завершения процесса.")
                        return

                if not temp_file_path or not temp_file_path.exists():
                    logger.error(f"Файл не найден после скачивания: ID={original_id}")
                    await status_msg.edit_text(f"❌ Ошибка: Не найден скачанный файл после завершения процесса.")
                    return

                # Получаем реальное расширение скачанного файла
                actual_ext = temp_file_path.suffix[1:]

            except yt_dlp.utils.DownloadError as e:
                error_message = f"❌ Ошибка скачивания:\n`{e}`"
                if "confirm your age" in str(e).lower():
                    error_message += "\n\nℹ️ Возможно, медиа имеет возрастное ограничение. Попробуйте загрузить Cookies."
                elif "private video" in str(e).lower() or "private playlist" in str(e).lower():
                    error_message += "\n\nℹ️ Это приватное медиа. Убедитесь, что у вас есть доступ и загружены Cookies."
                elif "premiere" in str(e).lower():
                    error_message = "❌ Ошибка: Видео является премьерой и еще не доступно для скачивания."
                elif "unavailable" in str(e).lower():
                    error_message = f"❌ Ошибка: Медиа недоступно ({e})."
                await status_msg.edit_text(error_message, parse_mode="Markdown")
                return
            except Exception as e:
                logger.error(f"Неожиданная ошибка yt-dlp на этапе скачивания для {url}: {e}")
                raise

        # Этап 2: Переименование и формирование ссылки (только если скачивание успешно)
        if download_success and temp_file_path and temp_file_path.exists():
            # Используем original_title, переданный из handle_url, т.к. info_after_download может быть неполным
            title_for_filename = original_title
            slug = hashlib.md5(title_for_filename.encode('utf-8') + str(user_id).encode()).hexdigest()[:10]
            timestamp = int(time.time())
            # 
            unique_filename = f"{slug}_{timestamp}.{actual_ext}"
            final_file_path = DOWNLOAD_PATH / unique_filename

            try:
                temp_file_path.rename(final_file_path)
                logger.info(f"Файл переименован в {final_file_path}")
            except OSError as e:
                logger.error(f"Ошибка переименования файла {temp_file_path} в {final_file_path}: {e}")
                await status_msg.edit_text(f"❌ Ошибка файловой системы при сохранении медиа.")
                return

            original_name_for_user = f"{sanitize_filename(title_for_filename)}.{actual_ext}"
            # 
            download_url = f"{DOWNLOAD_BASE_URL}/{quote(unique_filename)}?filename={quote(original_name_for_user)}"
            media_type_emoji = "🎬" if download_type == 'video' else "🎵"

            await status_msg.edit_text(
                f"✅ **Готово!**\n\n"
                f"{media_type_emoji} *{title_for_filename}*\n\n"
                f"🔗 [Скачать файл]({download_url})\n\n"
                f"_Ссылка действительна ограниченное время._",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        elif download_success and not temp_file_path: # Должно быть обработано выше, но на всякий случай
            logger.error(f"Скачивание помечено успешным, но файл не найден для URL {url}")
            await status_msg.edit_text("❌ Внутренняя ошибка: скачанный файл не найден.")

    except yt_dlp.utils.ExtractorError as e:
        logger.warning(f"Ошибка извлечения для {url}: {e}")
        await status_msg.edit_text(f"❌ Ошибка: Не удалось извлечь информацию для этой ссылки.\n`{e}`")
    except yt_dlp.utils.DownloadError as e: # Ловим ошибки скачивания еще раз (могут быть на этапе getinfo)
        logger.error(f"Ошибка скачивания yt-dlp (этап info) для {url}: {e}")
        await status_msg.edit_text(f"❌ Ошибка при получении информации о медиа:\n`{e}`")
    except Exception as e:
        logger.exception(f"Критическая ошибка при обработке {url} для пользователя {user_id}: {e}")
        await status_msg.edit_text(f"❌ Произошла непредвиденная ошибка:\n`{e}`")


# --- Обработчик ссылок ---
@dp.message(F.text.regexp(r'https?://\S+'))
async def handle_url(message: types.Message):
    """Обрабатывает полученную ссылку на видео."""
    if message.from_user.id not in ALLOWED_USERS: return
    if not message.text: return

    url = message.text.strip()
    user_id = message.from_user.id
    status_msg = await message.answer("🔎 Анализирую ссылку...")
    message_id_for_buttons = status_msg.message_id

    now = datetime.datetime.now(datetime.timezone.utc)
    expired_keys = [
        k for k, v in active_url_requests.items()
        if now - v['timestamp'] > REQUEST_TTL
    ]
    for key in expired_keys:
        active_url_requests.pop(key, None)
        logger.info(f"Удален устаревший запрос: {key}")

    try:
        ydl_opts_info = get_ydl_opts(user_id) # Получаем базовые опции, включая cookies
        ydl_opts_info['skip_download'] = True
        ydl_opts_info['quiet'] = True
        # 
        ydl_opts_info['no_warnings'] = True

        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get('formats', [])
        thumbnail_url = info.get('thumbnail')
        title = info.get('title', 'медиафайл') # Более общее название

        # Сохраняем URL и доп. инфо ПЕРЕД отправкой кнопок
        active_url_requests[message_id_for_buttons] = {
            'url': url,
            'timestamp': datetime.datetime.now(datetime.timezone.utc),
            'title': title, # Сохраняем оригинальный заголовок
            'thumbnail_url': thumbnail_url
        }

        quality_buttons_data = []
        unique_qualities = {}

        # 
        for f in formats:
            height = f.get('height')
            format_id = f.get('format_id')
            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none') # Проверяем и аудиокодек

            # Ищем форматы с видео и аудио дорожками (или только видео, если аудио будет сливаться)
            if height and height >= 480 and vcodec != 'none' and format_id:
                # Предпочитаем форматы, которые уже содержат аудио, или DASH видео (http/https)
                # yt-dlp по умолчанию пытается выбрать формат с видео и аудио.
                # Если формат только видео (vcodec != 'none' and acodec == 'none'),
                # yt-dlp автоматически попытается найти и смержить с лучшим аудио.
                # Нам важно, чтобы был видеопоток.
                 quality_label = f"{height}p"
                 if quality_label not in unique_qualities:
                    # 
                    unique_qualities[quality_label] = {
                        "format_id": format_id,
                        "height": height
                    }

        sorted_qualities = sorted(unique_qualities.items(), key=lambda item: item[1]['height'], reverse=True)

        builder = InlineKeyboardBuilder()
        # 
        for label, data in sorted_qualities:
            callback_data = json.dumps({
                "a": "dv", # action: download_video
                "f": data['format_id']
            })
            if len(callback_data.encode('utf-8')) <= 64:
                builder.button(text=f"🎬 {label}", callback_data=callback_data)
            else:
                logger.warning(f"Callback data для видео {label} ({data['format_id']}) слишком длинное. Кнопка пропущена.")

        # --- Новая кнопка MP3 ---
        callback_data_mp3 = json.dumps({"a": "da"}) # action: download_audio
        if len(callback_data_mp3.encode('utf-8')) <= 64:
             builder.button(text="🎵 Скачать MP3", callback_data=callback_data_mp3)
        else:
            logger.warning(f"Callback data для MP3 слишком длинное. Кнопка пропущена.")


        if thumbnail_url:
            callback_data_thumb = json.dumps({"a": "t"}) # action: thumbnail
            if len(callback_data_thumb.encode('utf-8')) <= 64:
                builder.button(text="🖼️ Обложка", callback_data=callback_data_thumb)
            else:
                logger.warning(f"Callback data для обложки слишком длинное. Кнопка пропущена.")


        # Компоновка кнопок: кнопки качества по 2 в ряд, затем MP3 и Обложка на отдельных рядах или вместе
        video_quality_button_count = len(sorted_qualities)
        if video_quality_button_count > 0:
            # Первый ряд - кнопки качества
            builder.adjust(*([2] * (video_quality_button_count // 2) + ([1] if video_quality_button_count % 2 else [])))
        # Остальные кнопки (MP3, Обложка) будут добавлены в новый ряд по умолчанию или по одной, если adjust не указан для них


        keyboard_markup = builder.as_markup() if builder.buttons else None

        if not keyboard_markup: # Если ни одной кнопки не создано (например, все callback_data слишком длинные)
             await status_msg.edit_text(
                f"Найдено медиа: *{title}*\n\n"
                "Не удалось сформировать кнопки выбора. Скачиваю в наилучшем доступном качестве.",
                parse_mode="Markdown"
            )
             active_url_requests.pop(message_id_for_buttons, None) # Очищаем state
             await download_media(message, url, user_id, original_title=title) # Скачиваем best video по умолчанию
             return


        if video_quality_button_count > 0 :
            await status_msg.edit_text(
                f"Найдено медиа: *{title}*\n\nВыберите действие:",
                reply_markup=keyboard_markup,
                parse_mode="Markdown"
            )
        else: # Нет подходящих видео форматов >= 480p, но есть кнопка MP3 и/или обложка
            await status_msg.edit_text(
                f"Найдено медиа: *{title}*\n\nВидеоформаты >= 480p не найдены. Вы можете скачать MP3 или обложку (если доступно), или я скачаю видео в лучшем качестве по умолчанию.",
                reply_markup=keyboard_markup, # Показываем кнопки MP3/Обложка
                parse_mode="Markdown"
            )
            # НЕ начинаем скачивание видео автоматически, даем пользователю выбрать MP3/Обложку.
            # Если пользователь не выберет, а напишет что-то другое, state запроса умрет по TTL.
            # Можно добавить кнопку "Скачать лучшее видео" если video_quality_button_count == 0
            # Или если пользователь захочет, он может отправить ссылку заново для скачивания видео по умолчанию.

    except TelegramBadRequest as e:
        if "BUTTON_DATA_INVALID" in str(e):
            logger.error(f"Ошибка BUTTON_DATA_INVALID для URL: {url}. Данные: {builder.export() if 'builder' in locals() else 'N/A'}")
            await status_msg.edit_text("❌ Ошибка: Не удалось сформировать кнопки (данные слишком длинные).")
        else:
            logger.exception(f"Ошибка Telegram API в handle_url для {url}: {e}")
            await status_msg.edit_text(f"❌ Ошибка Telegram API: {e}")
        active_url_requests.pop(message_id_for_buttons, None)
    except yt_dlp.utils.ExtractorError as e:
        logger.warning(f"Ошибка извлечения для {url} в handle_url: {e}")
        await status_msg.edit_text(f"❌ Ошибка: Не удалось извлечь информацию для этой ссылки.\n`{e}`")
        active_url_requests.pop(message_id_for_buttons, None)
    except yt_dlp.utils.DownloadError as e: # Ошибки, которые могут возникнуть при extract_info
        logger.error(f"Ошибка yt-dlp (info extraction) для {url}: {e}")
        await status_msg.edit_text(f"❌ Ошибка при получении информации о медиа:\n`{e}`")
        active_url_requests.pop(message_id_for_buttons, None)
    except Exception as e:
        logger.exception(f"Критическая ошибка в handle_url для {url} пользователя {message.from_user.id}: {e}")
        await status_msg.edit_text(f"❌ Произошла непредвиденная ошибка при обработке ссылки:\n`{e}`")
        active_url_requests.pop(message_id_for_buttons, None)


# --- Обработчик нажатий Inline кнопок ---
# 
@dp.callback_query(F.data.startswith('{'))
async def handle_callback_query(query: types.CallbackQuery):
    """Обрабатывает нажатия на inline-кнопки."""
    user_id = query.from_user.id
    if user_id not in ALLOWED_USERS:
        await query.answer("Доступ запрещен.", show_alert=True)
        return

    message_id = query.message.message_id
    request_data = active_url_requests.get(message_id)

    if not request_data:
        await query.answer("❌ Запрос устарел или не найден. Пожалуйста, отправьте ссылку заново.", show_alert=True)
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest: pass # Игнорируем, если сообщение уже без кнопок или не может быть изменено
        return

    url = request_data['url']
    original_title = request_data.get('title', 'медиафайл') # Извлекаем title
    thumbnail_url_from_state = request_data.get('thumbnail_url')


    # Убираем кнопки СРАЗУ после нажатия, чтобы предотвратить двойные нажатия
    # И очищаем state, если действие не требует дополнительной информации из него (кроме URL и title)
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception as edit_error:
        logger.warning(f"Не удалось убрать кнопки у сообщения {message_id}: {edit_error}")


    try:
        data = json.loads(query.data)
        action = data.get("a")

        if action == "dv": # download_video
            active_url_requests.pop(message_id, None) # Очищаем state
            format_id = data.get("f")
            if not format_id:
                await query.answer("❌ Ошибка: Не указан формат видео.", show_alert=True)
                return
            await query.answer(f"🚀 Запускаю скачивание видео...")
            # Передаем original_title в download_media
            await download_media(query.message, url, user_id, original_title=original_title, format_id=format_id, download_type='video')

        elif action == "da": # download_audio (MP3)
            active_url_requests.pop(message_id, None) # Очищаем state
            await query.answer("🎧 Запускаю скачивание MP3...")
            # Передаем original_title в download_media
            await download_media(query.message, url, user_id, original_title=original_title, download_type='audio')

        elif action == "t": # thumbnail
            active_url_requests.pop(message_id, None)
            await query.answer("🖼️ Загружаю обложку...")
            await send_thumbnail(query.message, url, user_id, thumbnail_url_from_state, original_title)


        else:
            active_url_requests.pop(message_id, None) # Очищаем state для неизвестных действий
            await query.answer("Неизвестное действие.", show_alert=True)
            logger.warning(f"Получено неизвестное действие '{action}' в callback_data для сообщения {message_id}")

    except json.JSONDecodeError:
        logger.warning(f"Не удалось декодировать JSON из callback_data: {query.data} для сообщения {message_id}")
        await query.answer("❌ Ошибка обработки данных кнопки.", show_alert=True)
        active_url_requests.pop(message_id, None)
    except Exception as e:
        logger.exception(f"Ошибка в handle_callback_query для пользователя {user_id}, сообщения {message_id}: {e}")
        # 
        await query.answer("❌ Произошла ошибка при обработке вашего запроса.", show_alert=True)
        active_url_requests.pop(message_id, None)


# --- Отправка обложки ---
async def send_thumbnail(message: types.Message, url: str, user_id: int, thumbnail_url: str | None, title: str):
    """Отправляет обложку пользователю."""
    # Если thumbnail_url уже есть из state, используем его
    if thumbnail_url:
        try:
            await message.answer_photo(
                photo=thumbnail_url,
                caption=f"Обложка для:\n*{title}*" if title else "Обложка",
                parse_mode="Markdown"
            )
            return
        except Exception as e:
            logger.warning(f"Не удалось отправить обложку по URL из state ({thumbnail_url}): {e}. Попробую извлечь заново.")

    # Если URL из state не сработал или его не было, извлекаем заново
    status_msg = await message.answer("⏳ Получаю обложку...")
    try:
        ydl_opts_info = get_ydl_opts(user_id)
        ydl_opts_info['skip_download'] = True
        ydl_opts_info['quiet'] = True
        ydl_opts_info['no_warnings'] = True

        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)

        new_thumbnail_url = info.get('thumbnail')
        # title уже есть из параметров функции

        if new_thumbnail_url:
            await status_msg.delete() # Удаляем "Получаю обложку..."
            await message.answer_photo(
                photo=new_thumbnail_url,
                caption=f"Обложка для:\n*{title}*" if title else "Обложка",
                parse_mode="Markdown"
            )
        else:
            await status_msg.edit_text("❌ Не удалось найти обложку для этого медиа.")

    except Exception as e:
        logger.error(f"Ошибка при получении обложки для {url}: {e}")
        await status_msg.edit_text(f"❌ Не удалось получить обложку: {e}")


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