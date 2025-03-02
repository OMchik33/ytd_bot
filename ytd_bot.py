import os
import asyncio
import aiohttp
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton
import yt_dlp
import re
import random
import string
from urllib.parse import quote
import hashlib

# Конфигурация
BOT_TOKEN = "ВСТАВЬТЕСЮДАТОКЕНБОТА"
ALLOWED_USERS = [ВАШ_ТГ_ID]
DOWNLOAD_PATH = "/download"
COOKIES_PATH = "/root/ytd/cookies"
DOWNLOAD_BASE_URL = "https://ВАШДОМЕН.ru/1234567yourrandom"

# Включение логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Создаем необходимые каталоги
os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(COOKIES_PATH, exist_ok=True)

# Инициализация bot и dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Create keyboard
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📥 Download Video")],
        [KeyboardButton(text="🔑 Upload Cookies")]
    ],
    resize_keyboard=True,
    persistent=True
)

# Start command
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("Кто вы? Я вас не знаю!.")
        return
    await message.answer("Привет! Нажмите кнопки для выбора действия:", reply_markup=main_keyboard)

# Handle cookies upload
@dp.message(lambda message: message.document and message.document.file_name.endswith('.txt'))
async def handle_cookie_file(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    try:
        file = await bot.get_file(message.document.file_id)
        file_path = os.path.join(COOKIES_PATH, f"cookies_{message.from_user.id}.txt")
        await bot.download_file(file.file_path, file_path)
        await message.answer("✅ Куки файл загрузился успешно!")
    except Exception as e:
        logger.error(f"Ошибочка с куки файлом: {e}")
        await message.answer("❌ Куки не загрузился. Попробуйте еще раз.")

# Скачивание видео
async def download_media(message: types.Message, url: str):
    status_message = await message.answer("🔄 Скачиваю...")
    try:
        # yt-dlp options
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_PATH, '%(id)s.%(ext)s'),  # Используем ID видео как временное имя
            'quiet': False,
            'nocheckcertificate': True,
            'geo_bypass': True,
            'retries': 5,
            'cookiefile': os.path.join(COOKIES_PATH, f"cookies_{message.from_user.id}.txt") if os.path.exists(os.path.join(COOKIES_PATH, f"cookies_{message.from_user.id}.txt")) else None,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        title = info.get('title', 'video')
        # Генерация хэша для названия файла
        slug = hashlib.md5(title.encode('utf-8')).hexdigest()
        file_name = f"{slug}.{info['ext']}"
        file_path = os.path.join(DOWNLOAD_PATH, file_name)

        # Переименовываем файл
        temp_file_path = os.path.join(DOWNLOAD_PATH, f"{info['id']}.{info['ext']}")
        os.rename(temp_file_path, file_path)
        # Sanitize filename (удаление смайликов и спецсимволов)
        def sanitize_filename(title):
            # Разрешаем буквы (латинские и русские), цифры, точку, запятую, восклицательный знак, дефис, нижнее подчеркивание и пробел
            sanitized = re.sub(r'[^a-zA-Zа-яА-Я0-9\.,!\- _]', '', title)
            # Удаляем лишние пробелы (если они не нужны)
            sanitized = re.sub(r'\s+', ' ', sanitized).strip()
            return sanitized
        original_name = f"{sanitize_filename(title)}.{info['ext']}"  # Оригинальное имя файла
        # Генерация ссылки на скачивание
        download_url = f"{DOWNLOAD_BASE_URL}/{quote(file_name)}?filename={quote(original_name)}"

        await status_message.edit_text(f"✅ ГОТОВО!\n\nНазвание ролика: `{title}`\n\nНа скачивание 1 час\n\n[Ссылка для скачивания]({download_url})", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_message.edit_text(f"❌ Наводчик контужен: {e}")

# Отправляем сообщение для скачивания видео
@dp.message(lambda message: message.text == "📥 Download Video")
async def request_video_url(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    await message.answer("Отправьте ссылку на видео.")

# Handle incoming URL
@dp.message(lambda message: re.match(r'https?://', message.text))
async def handle_url(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    await download_media(message, message.text)

# Main function
async def main():
    try:
        logger.info("Поехали...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
