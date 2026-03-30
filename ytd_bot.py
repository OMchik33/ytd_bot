import os
import re
import json
import time
import hashlib
import logging
import asyncio
import datetime
import shutil
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
ALLOWED_USERS = [
    int(x)
    for x in os.getenv("ALLOWED_USERS", "").replace('"', "").split(",")
    if x.strip().isdigit()
]
SPECIAL_CODE = os.getenv("SPECIAL_CODE")
DOWNLOAD_PATH = Path(os.getenv("DOWNLOAD_PATH", "/download"))
COOKIES_PATH = Path(os.getenv("COOKIES_PATH", "/opt/telegram-bots/ytd_bot/cookies"))
DOWNLOAD_BASE_URL = os.getenv("DOWNLOAD_BASE_URL")

DEBUG_YTDLP = os.getenv("DEBUG_YTDLP", "0") == "1"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if not DOWNLOAD_BASE_URL:
    raise RuntimeError("DOWNLOAD_BASE_URL is not set")

DOWNLOAD_PATH.mkdir(parents=True, exist_ok=True)
COOKIES_PATH.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ytd_bot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

active_url_requests: dict[int, dict] = {}
REQUEST_TTL = datetime.timedelta(hours=1)


# ========================== #
# 🧩 Хелперы
# ========================== #

def sanitize_filename(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "", title)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > 150:
        hash_part = hashlib.md5(title.encode()).hexdigest()[:8]
        name = name[:140] + "_" + hash_part
    return name


def clean_youtube_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    allowed_params = ["v", "t", "list"]
    new_query = {k: v for k, v in query.items() if k in allowed_params}
    clean_query = "&".join([f"{k}={v[0]}" for k, v in new_query.items()])
    return urlunparse(parsed._replace(query=clean_query))


def get_cookie_file(user_id: int) -> Path | None:
    cookie_file = COOKIES_PATH / f"cookies_{user_id}.txt"
    return cookie_file if cookie_file.exists() else None


def detect_node_path() -> str | None:
    p = shutil.which("node")
    if p:
        return p
    for cand in ("/usr/bin/node", "/usr/local/bin/node", "/snap/bin/node"):
        if os.path.exists(cand):
            return cand
    return None


def purge_old_requests():
    now = datetime.datetime.now(datetime.timezone.utc)
    dead = []
    for mid, data in active_url_requests.items():
        ts = data.get("timestamp")
        if not ts or (now - ts > REQUEST_TTL):
            dead.append(mid)
    for mid in dead:
        active_url_requests.pop(mid, None)


def fmt_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return ""
    mb = max(1, round(size_bytes / 1024 / 1024))
    return f" (~{mb} МБ)"


def build_base_ydl_opts(user_id: int, *, skip_download: bool, quiet: bool) -> dict:
    """
    База. downloader НЕ задаём здесь, чтобы можно было сделать retry с ffmpeg.
    """
    cookie_file = get_cookie_file(user_id)
    node_path = detect_node_path()

    opts: dict = {
        "outtmpl": str(DOWNLOAD_PATH / "%(id)s.%(ext)s"),
        "paths": {"home": str(DOWNLOAD_PATH)},
        "noplaylist": True,

        "skip_download": skip_download,
        "quiet": quiet,
        "no_warnings": quiet,

        "nocheckcertificate": True,
        "geo_bypass": True,

        # стабильность
        "retries": 20,
        "fragment_retries": 20,
        "socket_timeout": 30,
        "http_chunk_size": 10 * 1024 * 1024,
        "concurrent_fragment_downloads": 1,
        "continuedl": True,
        "force_ipv4": True,

        # SABR/HLS/прочие “странные” случаи
        "ignore_no_formats_error": True,

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        },

        # EJS remote component
        "remote_components": ["ejs:github"],
    }

    if node_path:
        opts["js_runtimes"] = {"node": {"path": node_path}}
    else:
        opts["js_runtimes"] = {}

    if cookie_file:
        opts["cookiefile"] = str(cookie_file)

    if DEBUG_YTDLP:
        opts["verbose"] = True

    return opts


def get_format_string(mode: str, format_id: str | None) -> str:
    """
    Формат-строки делаем мягкими с fallback.
    """
    if mode == "pick":
        return f"{format_id}+bestaudio[ext=m4a]/best[ext=mp4]/best"

    if mode == "safe":
        return "best[ext=mp4]/best"

    if mode == "bestq":
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

    if mode == "any":
        return "best"

    return "best"


def ydl_extract(url: str, opts: dict, *, download: bool):
    """
    Отдельная функция, чтобы проще было делать retry с другим downloader.
    """
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=download)


def find_downloaded_file(info: dict) -> str | None:
    """
    Пытаемся найти именно итоговый файл после download=True.
    Сначала предпочитаем merged/final path из info,
    а промежуточные .fXXX.* берём только как крайний fallback.
    """

    def existing(path: str | None) -> str | None:
        if path and os.path.exists(path):
            return path
        return None

    # 1) requested_downloads: в нём часто уже есть итоговый filepath
    rds = info.get("requested_downloads") or []
    if isinstance(rds, list):
        for item in rds:
            for key in ("filepath", "filename", "_filename"):
                path = existing(item.get(key))
                if path:
                    name = os.path.basename(path)
                    # предпочитаем НЕ промежуточные файлы .f137.mp4
                    if not re.search(r"\.f\d+\.", name):
                        return path

        # если нашли только промежуточные — запомним как запасной вариант
        for item in rds:
            for key in ("filepath", "filename", "_filename"):
                path = existing(item.get(key))
                if path:
                    return path

    # 2) поля верхнего уровня info
    for key in ("filepath", "filename", "_filename"):
        path = existing(info.get(key))
        if path:
            name = os.path.basename(path)
            if not re.search(r"\.f\d+\.", name):
                return path

    for key in ("filepath", "filename", "_filename"):
        path = existing(info.get(key))
        if path:
            return path

    # 3) fallback по id в папке
    vid = info.get("id")
    if not vid:
        return None

    candidates = list(DOWNLOAD_PATH.glob(f"{vid}.*"))
    candidates = [p for p in candidates if not str(p).endswith(".part")]
    if not candidates:
        return None

    # сначала пробуем взять не-промежуточный файл
    final_candidates = [
        p for p in candidates
        if not re.search(r"\.f\d+\.", p.name)
    ]
    if final_candidates:
        final_candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
        return str(final_candidates[0])

    # если ничего лучше нет — берём самый крупный
    candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
    return str(candidates[0])


# ========================== #
# 🧭 Команды
# ========================== #

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⬇️ Скачать видео"), KeyboardButton(text="🍪 Cookies")],
        [KeyboardButton(text="ℹ️ Инструкция")],
    ],
    resize_keyboard=True,
    persistent=True,
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
        "  - Бот предложит выбрать качество видео.\n"
        "  - Будет кнопка \"🎵 Скачать MP3\" для извлечения аудиодорожки.\n"
        "  - Будет кнопка \"🖼️ Обложка\" для скачивания превью.\n"
        "*🍪 Cookies* - Используйте, если видео требует авторизации или не скачивается.\n"
        "1. Установите [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc).\n"
        "2. Зайдите в аккаунт на нужном сайте.\n"
        "3. Нажмите иконку расширения -> Export (формат **Netscape**).\n"
        "4. Нажмите \"🍪 Cookies\" в боте -> отправьте `.txt` файл.\n"
        "5. Попробуйте скачать видео снова.",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


@dp.message(F.text == "🍪 Cookies")
async def prompt_cookies(message: types.Message):
    await message.answer("Отправьте файл `cookies.txt` (формат Netscape).", parse_mode="Markdown")


@dp.message(F.document & F.document.file_name.endswith(".txt"))
async def handle_cookie_file(message: types.Message):
    destination = COOKIES_PATH / f"cookies_{message.from_user.id}.txt"
    file_info = await bot.get_file(message.document.file_id)
    await bot.download_file(file_info.file_path, destination)
    await message.answer("✅ Cookies сохранены.")


@dp.message(F.text == "⬇️ Скачать видео")
async def prompt_video_url(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    await message.answer("Пришлите ссылку на видео.")


# ========================== #
# 🎥 Загрузка
# ========================== #

async def download_media(
    message: types.Message,
    url: str,
    user_id: int,
    title: str,
    *,
    mode: str,
    format_id: str | None = None,
):
    status = await message.answer("⏳ Подготовка к скачиванию...")

    opts = build_base_ydl_opts(user_id, skip_download=False, quiet=False)

    if mode == "audio":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
        emoji = "🎵"
    else:
        if mode == "pick" and not format_id:
            await status.edit_text("❌ Не передан format_id.")
            return
        opts["format"] = get_format_string(mode, format_id)
        emoji = "🎬" if mode in ("safe", "pick", "any") else "💎"

    # 1) первая попытка — штатный downloader
    try:
        logger.info(f"Downloading url={url} mode={mode} format={opts.get('format')}")
        info = ydl_extract(url, opts, download=True)
    except Exception as e1:
        logger.warning(f"Primary download failed, retry with ffmpeg downloader. err={e1}")

        # 2) retry с ffmpeg downloader (часто спасает m3u8/HLS/SABR)
        opts_ff = dict(opts)
        opts_ff["downloader"] = "ffmpeg"
        try:
            info = ydl_extract(url, opts_ff, download=True)
        except Exception as e2:
            logger.exception(e2)
            await status.edit_text(f"❌ Ошибка:\n`{e2}`", parse_mode="Markdown")
            return

    path = find_downloaded_file(info)
    if not path or not os.path.exists(path):
        await status.edit_text("❌ Файл не найден после скачивания.")
        return

    ext = Path(path).suffix[1:] if Path(path).suffix else "bin"
    unique = f"{hashlib.md5(title.encode()).hexdigest()[:8]}_{int(time.time())}.{ext}"
    final = DOWNLOAD_PATH / unique
    os.replace(path, final)

    clean_title = sanitize_filename(title)
    dlink = f"{DOWNLOAD_BASE_URL}/{quote(unique)}?filename={quote(clean_title + '.' + ext)}"

    await status.edit_text(
        f"✅ {emoji} *{title}*\n\n[Скачать файл]({dlink})",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


# ========================== #
# 🔗 Обработка ссылок
# ========================== #

@dp.message(F.text.regexp(r"https?://\S+"))
async def handle_url(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return

    purge_old_requests()

    url = clean_youtube_url(message.text.strip())
    user_id = message.from_user.id
    status = await message.answer("🔎 Анализ ссылки...")

    title = "Видео"
    thumbnail_url = None
    formats = []

    try:
        opts_info = build_base_ydl_opts(user_id, skip_download=True, quiet=True)
        # НЕ задаём format тут!
        with yt_dlp.YoutubeDL(opts_info) as ydl:
            info = ydl.extract_info(url, download=False)

        title = info.get("title") or title
        thumbnail_url = info.get("thumbnail")
        formats = info.get("formats") or []
    except Exception as e:
        logger.exception(e)

    # Кнопки “всегда”
    base_builder = InlineKeyboardBuilder()
    base_builder.row(
        types.InlineKeyboardButton(text="⬇️ Скачать (обычно/надёжно)", callback_data=json.dumps({"a": "d_safe"})),
        types.InlineKeyboardButton(text="💎 Скачать в лучшем качестве", callback_data=json.dumps({"a": "d_bestq"})),
    )
    base_builder.row(
        types.InlineKeyboardButton(text="🧩 Скачать (любой формат)", callback_data=json.dumps({"a": "d_any"})),
        types.InlineKeyboardButton(text="🎵 Скачать MP3", callback_data=json.dumps({"a": "d_audio"})),
    )
    if thumbnail_url:
        base_builder.row(types.InlineKeyboardButton(text="🖼️ Скачать обложку", callback_data=json.dumps({"a": "t"})))

    # Попытка показать выбор качества (не режем m3u8, иначе на SABR будет пусто)
    available: dict[str, str] = {}
    for f in formats:
        fid = f.get("format_id")
        ext = (f.get("ext") or "").lower()
        height = f.get("height")
        vcodec = f.get("vcodec")

        if not fid:
            continue
        if ext == "mhtml" or "storyboard" in str(fid).lower():
            continue
        if not vcodec or vcodec == "none":
            continue
        if not height:
            m = re.search(r"(\d{3,4})p", f.get("format", "") or "")
            if m:
                height = int(m.group(1))
        if not height:
            continue

        size = f.get("filesize") or f.get("filesize_approx") or 0
        # помечаем ext, но это может быть m3u8/ts/mp4/webm и т.п.
        label = f"{height}p {ext}{fmt_size(size)}"
        available[label] = fid

    if available:
        qual_builder = InlineKeyboardBuilder()
        for label, fid in sorted(
            available.items(),
            key=lambda x: int(re.search(r"(\d+)p", x[0]).group(1)),
            reverse=True,
        )[:12]:  # не раздуваем клаву
            qual_builder.button(text=f"🎬 {label}", callback_data=json.dumps({"a": "pick", "f": fid}))
        qual_builder.adjust(2)

        for row in base_builder.export():
            qual_builder.row(*row)

        kb = qual_builder.as_markup()
        text = f"*{title}*\n\nВыберите качество или используйте режимы скачивания:"
    else:
        kb = base_builder.as_markup()
        text = f"*{title}*\n\nФорматы показать не удалось. Используйте режимы скачивания:"

    msg = await status.edit_text(text, reply_markup=kb, parse_mode="Markdown")

    active_url_requests[msg.message_id] = {
        "url": url,
        "timestamp": datetime.datetime.now(datetime.timezone.utc),
        "title": title,
        "thumbnail_url": thumbnail_url,
    }


# ========================== #
# 🎛 Кнопки
# ========================== #

@dp.callback_query(F.data.startswith("{"))
async def handle_callback(query: types.CallbackQuery):
    try:
        data = json.loads(query.data)
        user_id = query.from_user.id
        msg_id = query.message.message_id

        req = active_url_requests.get(msg_id)
        if not req:
            await query.answer("Запрос устарел.", show_alert=True)
            return

        url = req["url"]
        title = req["title"]
        thumb = req.get("thumbnail_url")

        action = data.get("a")

        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        if action == "pick":
            await query.answer("🚀 Скачиваю выбранное качество...")
            await download_media(query.message, url, user_id, title, mode="pick", format_id=data.get("f"))

        elif action == "d_safe":
            await query.answer("⬇️ Скачиваю (надёжно)...")
            await download_media(query.message, url, user_id, title, mode="safe")

        elif action == "d_bestq":
            await query.answer("💎 Скачиваю (лучшее качество)...")
            await download_media(query.message, url, user_id, title, mode="bestq")

        elif action == "d_any":
            await query.answer("🧩 Скачиваю (любой формат)...")
            await download_media(query.message, url, user_id, title, mode="any")

        elif action == "d_audio":
            await query.answer("🎧 MP3...")
            await download_media(query.message, url, user_id, title, mode="audio")

        elif action == "t":
            await query.answer("🖼️ Обложка...")
            if thumb:
                await query.message.answer_photo(photo=thumb, caption=f"Обложка:\n*{title}*", parse_mode="Markdown")
            else:
                await query.message.answer("❌ Нет обложки.")

        else:
            await query.answer("Неизвестное действие", show_alert=True)

    except Exception as e:
        logger.exception(e)
        await query.message.answer(f"⚠️ Ошибка кнопки:\n`{e}`", parse_mode="Markdown")


# ========================== #
# 🚀 Запуск
# ========================== #

async def main():
    logger.info("Бот запущен.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())