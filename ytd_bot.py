import os
import asyncio
import logging
import time
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import re
from urllib.parse import quote
import hashlib
import json

# Конфигурация
BOT_TOKEN = "ВСТАВЬТЕСЮДАТОКЕНБОТА"
ALLOWED_USERS = [ВАШ_ТГ_ID]
SPECIAL_CODE = "secretcode12345"
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

# Глобальный словарь для хранения режимов скачивания
user_modes = {}

# Create keyboard
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Скачать видео")],
        [KeyboardButton(text="Скачать Youtube")],
        [KeyboardButton(text="🔑 Upload Cookies")]
    ],
    resize_keyboard=True,
    persistent=True
)

# Запуск бота
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    args = message.text.split()[1] if len(message.text.split()) > 1 else ""
    if args == SPECIAL_CODE:
        if message.from_user.id not in ALLOWED_USERS:
            ALLOWED_USERS.append(message.from_user.id)
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("❌ Кто вы? Я вас не знаю! Доступ только по приглашению администратора")
        return
    await message.answer("Привет! Нажмите кнопки для выбора действия:", reply_markup=main_keyboard)

# Обработчик загрузки куки файла
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
async def download_media(message: types.Message, url: str, quality: str = None):
    status_message = await message.answer("🔄 Скачиваю...")
    try:
        ydl_opts = {
            'format': f'{quality}+bestaudio/best' if quality else 'bestvideo+bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_PATH, '%(id)s.%(ext)s'),
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
        slug = hashlib.md5(title.encode('utf-8')).hexdigest()
        timestamp = int(time.time())
        file_name = f"{slug}_{timestamp}.{info['ext']}"
        file_path = os.path.join(DOWNLOAD_PATH, file_name)

        temp_file_path = os.path.join(DOWNLOAD_PATH, f"{info['id']}.{info['ext']}")
        os.rename(temp_file_path, file_path)
        
        def sanitize_filename(title):
            sanitized = re.sub(r'[^a-zA-Zа-яА-Я0-9\.,!\- _]', '', title)
            sanitized = re.sub(r'\s+', ' ', sanitized).strip()
            return sanitized
            
        original_name = f"{sanitize_filename(title)}.{info['ext']}"
        download_url = f"{DOWNLOAD_BASE_URL}/{quote(file_name)}?filename={quote(original_name)}"

        await status_message.edit_text(f"✅ ГОТОВО!\n\n*Название ролика:* `{title}`\n\nНа скачивание 1 час\n\n[Ссылка для скачивания]({download_url})", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_message.edit_text(f"❌ Наводчик контужен: {e}")

# Обработчики кнопок
@dp.message(lambda message: message.text == "Скачать видео")
async def handle_best_download(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    user_modes[message.from_user.id] = 'best'
    await message.answer("Отправьте ссылку на видео для скачивания в лучшем качестве. Можно скачивать видео с различных видеосервисов. Для некоторых использование куки файла обязательно.")

@dp.message(lambda message: message.text == "Скачать Youtube")
async def request_video_url(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    user_modes[message.from_user.id] = 'choose'
    await message.answer("Отправьте ссылку на видео Youtube. Доступен выбор качества для скачивания.")

# Проверяем сообщение на наличие URL
@dp.message(lambda message: re.match(r'https?://', message.text))
async def handle_url(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    
    current_mode = user_modes.pop(message.from_user.id, 'choose')
    
    if current_mode == 'best':
        await download_media(message, message.text)
    else:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'cookiefile': os.path.join(COOKIES_PATH, f"cookies_{message.from_user.id}.txt") if os.path.exists(os.path.join(COOKIES_PATH, f"cookies_{message.from_user.id}.txt")) else None,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(message.text, download=False)
            formats = info.get('formats', [])
        
        buttons = []
        unique_qualities = set()
        for f in formats:
            if f.get('height') and f['height'] >= 480:
                quality = f"{f['height']}p"
                if quality not in unique_qualities:
                    unique_qualities.add(quality)
                    callback_data = json.dumps({"url": message.text, "quality": f['format_id']})
                    buttons.append(InlineKeyboardButton(text=quality, callback_data=callback_data))
        
        buttons.sort(key=lambda x: int(x.text[:-1]), reverse=True)
        keyboard = []
        for i in range(0, len(buttons), 2):
            row = buttons[i:i + 2]
            if len(row) == 1:
                row[0].text = f"🎬 {row[0].text}"
            keyboard.append(row)
        
        await message.answer("Выберите качество видео:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

# Обработка выбора качества
@dp.callback_query()
async def handle_callback_query(query: types.CallbackQuery):
    try:
        data = json.loads(query.data)
        url = data.get("url")
        quality = data.get("quality")

        if not url:
            await query.answer("❌ Ошибка: не найдена ссылка на видео.")
            return

        await download_media(query.message, url, quality)
        await query.answer()
    except Exception as e:
        logger.error(f"Ошибка в обработке callback_query: {e}")
        await query.answer("❌ Произошла ошибка. Попробуйте еще раз.")

# Main function
async def main():
    try:
        logger.info("Поехали...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
