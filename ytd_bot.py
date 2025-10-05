import os
import re
import json
import time
import hashlib
import logging
import asyncio
import datetime
from pathlib import Path
from urllib.parse import quote, urlparse, parse_qs, urlunparse

import yt_dlp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# ========================== #
# 🔧 Конфигурация окружения
# ========================== #

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS = [int(x) for x in os.getenv("ALLOWED_USERS", "").replace('"', '').split(',') if x.strip().isdigit()]
SPECIAL_CODE = os.getenv("SPECIAL_CODE")
DOWNLOAD_PATH = Path(os.getenv("DOWNLOAD_PATH", "/download"))
COOKIES_PATH = Path(os.getenv("COOKIES_PATH", "/opt/telegram-bots/ytd_bot/cookies"))
DOWNLOAD_BASE_URL = os.getenv("DOWNLOAD_BASE_URL")

DOWNLOAD_PATH.mkdir(parents=True, exist_ok=True)
COOKIES_PATH.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ytd_bot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

active_url_requests = {}
REQUEST_TTL = datetime.timedelta(hours=1)


# ========================== #
# 🧩 Хелперы
# ========================== #
def sanitize_filename(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '', title)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > 150:
        hash_part = hashlib.md5(title.encode()).hexdigest()[:8]
        name = name[:140] + "_" + hash_part
    return name


def clean_youtube_url(url: str) -> str:
    """Удаляет хвосты ?list=..., &index=..., &feature=... и прочее."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    allowed_params = ['v', 't']
    new_query = {k: v for k, v in query.items() if k in allowed_params}
    clean_query = "&".join([f"{k}={v[0]}" for k, v in new_query.items()])
    return urlunparse(parsed._replace(query=clean_query))


def get_cookie_file(user_id: int) -> Path | None:
    cookie_file = COOKIES_PATH / f"cookies_{user_id}.txt"
    return cookie_file if cookie_file.exists() else None


def get_ydl_opts(user_id: int, format_selection: str = None, download_type: str = 'video') -> dict:
    cookie_file = get_cookie_file(user_id)
    opts = {
        'outtmpl': str(DOWNLOAD_PATH / '%(id)s.%(ext)s'),
        'quiet': False,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'retries': 5,
        'cookiefile': str(cookie_file) if cookie_file else None,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        },
        'fragment_retries': 10,
        'concurrent_fragment_downloads': 5,
        'noplaylist': True,
        'sleep_interval_requests': 1,
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'android', 'tv', 'ios', 'mweb']
            }
        },
    }

    # === аудио ===
    if download_type == 'audio':
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]

    # === видео ===
    elif download_type == 'video':
        opts['merge_output_format'] = 'mp4'

        # 🎯 если пользователь выбрал конкретный формат — используем его
        if format_selection:
            opts['format'] = f"{format_selection}+bestaudio[ext=m4a]/best[ext=mp4]/18"
        else:
            # иначе — скачиваем лучшее из mp4
            opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/18'

        opts['postprocessors'] = [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }]

    return opts



# ========================== #
# 🧭 Команды
# ========================== #
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⬇️ Скачать видео"), KeyboardButton(text="🍪 Cookies")],
        [KeyboardButton(text="ℹ️ Инструкция")]
    ],
    resize_keyboard=True,
    persistent=True
)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1] == SPECIAL_CODE and user_id not in ALLOWED_USERS:
        ALLOWED_USERS.append(user_id)
        await message.answer("✅ Доступ разрешён! Добро пожаловать.")
    elif user_id not in ALLOWED_USERS:
        await message.answer("❌ Доступ запрещён. Введите специальный код.")
        return
    await message.answer("Привет! Отправь ссылку на видео для скачивания.", reply_markup=main_keyboard)


@dp.message(F.text == "ℹ️ Инструкция")
async def show_help(message: types.Message):
    await message.answer(
        "*Инструкция для использования бота:*\n\n"
        "*⬇️ Скачать видео* - Нажмите эту кнопку, затем отправьте боту ссылку на видео.\n"
        "  - Бот предложит выбрать качество видео (если доступно несколько вариантов >= 480p).\n"
        "  - Будет кнопка \"🎵 Скачать MP3\" для извлечения аудиодорожки.\n"
        "  - Будет кнопка \"🖼️ Обложка\" для скачивания превью.\n"
        "*🍪 Cookies* - Используйте, если видео требует авторизации.\n"
        "1. Установите [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc).\n"
        "2. Зайдите в аккаунт на нужном сайте.\n"
        "3. Нажмите иконку расширения -> Export (формат **Netscape**).\n"
        "4. Нажмите \"🍪 Cookies\" в боте -> отправьте `.txt` файл.\n"
        "5. Попробуйте скачать видео снова.",
        parse_mode="Markdown"
    )


@dp.message(F.text == "🍪 Cookies")
async def prompt_cookies(message: types.Message):
    await message.answer("Отправьте сюда файл `cookies.txt` (формат Netscape).", parse_mode="Markdown")


@dp.message(F.document & F.document.file_name.endswith('.txt'))
async def handle_cookie_file(message: types.Message):
    destination = COOKIES_PATH / f"cookies_{message.from_user.id}.txt"
    file_info = await bot.get_file(message.document.file_id)
    await bot.download_file(file_info.file_path, destination)
    await message.answer("✅ Куки-файл сохранён. Теперь попробуйте снова.")


# ========================== #
# 🎥 Загрузка медиа
# ========================== #
async def download_media(message: types.Message, url: str, user_id: int,
                         title: str, format_id: str = None,
                         download_type: str = 'video'):
    status = await message.answer("⏳ Подготовка к скачиванию...")
    opts = get_ydl_opts(user_id, format_selection=format_id, download_type=download_type)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = info.get('requested_downloads', [{}])[0].get('filepath')
            if not path or not os.path.exists(path):
                await status.edit_text("❌ Файл не найден после скачивания.")
                return

            ext = Path(path).suffix[1:]
            unique = f"{hashlib.md5(title.encode()).hexdigest()[:8]}_{int(time.time())}.{ext}"
            final = DOWNLOAD_PATH / unique
            os.rename(path, final)

            clean_title = sanitize_filename(title)
            dlink = f"{DOWNLOAD_BASE_URL}/{quote(unique)}?filename={quote(clean_title + '.' + ext)}"
            emoji = "🎬" if download_type == "video" else "🎵"

            await status.edit_text(
                f"✅ {emoji} *{title}*\n\n[Скачать файл]({dlink})",
                parse_mode="Markdown", disable_web_page_preview=True
            )

    except Exception as e:
        logger.exception(e)
        await status.edit_text(f"❌ Ошибка при скачивании:\n`{e}`", parse_mode="Markdown")


# ========================== #
# 🔗 Обработка ссылок
# ========================== #
@dp.message(F.text.regexp(r'https?://\S+'))
async def handle_url(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return

    url = clean_youtube_url(message.text.strip())
    user_id = message.from_user.id
    status = await message.answer("🔎 Анализирую ссылку...")

    builder = InlineKeyboardBuilder()
    thumbnail_url = None
    title = "Неизвестное видео"

    try:
        opts = get_ydl_opts(user_id)
        opts.update({'skip_download': True, 'quiet': True, 'no_warnings': True, 'noplaylist': True})

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get('formats') or []
        thumbnail_url = info.get('thumbnail')
        title = info.get('title', title)

        # 🟡 Если нет форматов — fallback
        if not formats:
            builder.button(text="🎵 Скачать MP3", callback_data=json.dumps({"a": "da"}))
            if thumbnail_url:
                builder.button(text="🖼️ Обложка", callback_data=json.dumps({"a": "t"}))
            builder.adjust(2)

            active_url_requests[status.message_id] = {
                'url': url,
                'timestamp': datetime.datetime.now(datetime.timezone.utc),
                'title': title,
                'thumbnail_url': thumbnail_url
            }

            await status.edit_text(
                f"🎬 *{title}*\n\n"
                "Видео-форматы не найдены, но можно скачать аудио (MP3) или обложку.",
                reply_markup=builder.as_markup(),
                parse_mode="Markdown"
            )
            return

         # ✅ Собираем и фильтруем реальные видеоформаты (без storyboard и mhtml)
        available = {}

        for f in formats:
            fid = f.get("format_id")
            ext = f.get("ext", "")
            height = f.get("height") or 0
            vcodec = f.get("vcodec", "")
            acodec = f.get("acodec", "")

            # 🚫 Пропускаем storyboard (mhtml) и фейковые форматы
            if not fid or "storyboard" in fid or ext == "mhtml":
                continue

            # 🚫 Пропускаем форматы без кодеков (служебные)
            if not vcodec and not acodec:
                continue

            # 💾 Пытаемся получить размер файла
            size = f.get("filesize") or f.get("filesize_approx") or 0

            # если размер неизвестен — вычисляем из битрейта и длительности
            if not size:
                duration = f.get("duration") or info.get("duration") or 0
                tbr = f.get("tbr") or 0  # кбит/с
                if duration > 0 and tbr > 0:
                    size = tbr * 1000 * duration / 8  # -> байты

            # 🎬 Формируем подпись кнопки
            if height:
                label = f"{height}p {ext}"
            else:
                label = ext.upper()

            if size:
                # если размер получен через расчёт — добавляем тильду
                approx = "~" if not f.get("filesize") else ""
                mb = max(1, round(size / 1024 / 1024))
                label += f" ({approx}{mb} МБ)"

            available[label] = fid

        # Сортировка по высоте в порядке убывания
        for label, fid in sorted(
            available.items(),
            key=lambda x: int(re.search(r'(\d+)p', x[0]).group(1)) if re.search(r'(\d+)p', x[0]) else 0,
            reverse=True
        ):
            builder.button(
                text=f"🎬 {label}",
                callback_data=json.dumps({"a": "dv", "f": fid})
            )

        # ⚙️ Разбиваем на ряды — видео по 2 в ряд
        builder.adjust(2)

        # 🎵 Кнопка MP3 во всю ширину
        builder.row(
            types.InlineKeyboardButton(
                text="🎵 Скачать MP3",
                callback_data=json.dumps({"a": "da"})
            )
        )

        # 🖼️ Кнопка обложки во всю ширину (если есть)
        if thumbnail_url:
            builder.row(
                types.InlineKeyboardButton(
                    text="🖼️ Обложка",
                    callback_data=json.dumps({"a": "t"})
                )
            )

        msg = await status.edit_text(
            f"Найдено медиа: *{title}*\n\nВыберите формат для скачивания:",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )



        # ✅ сохраняем актуальный message_id
        active_url_requests[msg.message_id] = {
            'url': url,
            'timestamp': datetime.datetime.now(datetime.timezone.utc),
            'title': title,
            'thumbnail_url': thumbnail_url
        }

    except Exception as e:
        logger.exception(e)
        await status.edit_text(f"❌ Произошла непредвиденная ошибка при обработке ссылки:\n`{e}`",
                               parse_mode="Markdown")


# ========================== #
# 🎛 Обработка кнопок
# ========================== #
@dp.callback_query(F.data.startswith('{'))
async def handle_callback(query: types.CallbackQuery):
    try:
        data = json.loads(query.data)
        user_id = query.from_user.id
        msg_id = query.message.message_id

        req = active_url_requests.get(msg_id)
        if not req:
            await query.answer("Запрос устарел или не найден. Отправьте ссылку заново.", show_alert=True)
            return

        url = req['url']
        title = req['title']
        thumb = req.get('thumbnail_url')

        await query.message.edit_reply_markup(reply_markup=None)

        if data['a'] == 'dv':
            await query.answer("🚀 Скачиваю видео...")
            await download_media(query.message, url, user_id, title, format_id=data['f'], download_type='video')
        elif data['a'] == 'da':
            await query.answer("🎧 Скачиваю MP3...")
            await download_media(query.message, url, user_id, title, download_type='audio')
        elif data['a'] == 't':
            await query.answer("🖼️ Загружаю обложку...")
            if thumb:
                await query.message.answer_photo(photo=thumb, caption=f"Обложка:\n*{title}*", parse_mode="Markdown")
            else:
                await query.message.answer("❌ Обложка недоступна.")
    except Exception as e:
        logger.exception(e)
        await query.message.answer(f"⚠️ Ошибка при обработке кнопки:\n`{e}`", parse_mode="Markdown")


# ========================== #
# 🚀 Запуск
# ========================== #
async def main():
    logger.info("Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
