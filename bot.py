"""XStream Telegram Bot — aiogram 3.x"""
from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import quote

from aiogram import Bot, Dispatcher, Router, F
from aiogram.exceptions import TelegramEntityTooLarge
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    BotCommand, CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo,
)

logger = logging.getLogger(__name__)

TOKEN       = os.environ["TELEGRAM_BOT_TOKEN"]
DOMAIN      = os.environ.get("REPLIT_DEV_DOMAIN", "localhost:5000")
WEBAPP_URL  = f"https://{DOMAIN}"

bot = Bot(token=TOKEN)
dp  = Dispatcher()
rt  = Router()
dp.include_router(rt)


# ── Keyboards ─────────────────────────────────────────────────────────────────

def _main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔥 Open XStream", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
    )


def _open_btn(label: str, suffix: str = "") -> InlineKeyboardMarkup:
    url = WEBAPP_URL + (f"#{suffix}" if suffix else "")
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))]]
    )


def _search_kb(query: str) -> InlineKeyboardMarkup:
    url = f"{WEBAPP_URL}?q={quote(query)}#search"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"🔍 Search: {query[:40]}", web_app=WebAppInfo(url=url))]]
    )


def _video_kb(video_url: str) -> InlineKeyboardMarkup:
    url = f"{WEBAPP_URL}?video={quote(video_url, safe='')}#player"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="▶️ Watch Now", web_app=WebAppInfo(url=url))]]
    )


# ── Commands ──────────────────────────────────────────────────────────────────

@rt.message(CommandStart())
async def cmd_start(msg: Message):
    name = msg.from_user.first_name if msg.from_user else "there"
    await msg.answer(
        f"👋 Hey *{name}*! Welcome to *XStream*.\n\n"
        "Stream thousands of videos directly inside Telegram — no downloads, no redirects.\n\n"
        "✅ HD streaming\n"
        "✅ Full metadata\n"
        "✅ Favorites & watch history\n"
        "✅ Resume where you left off\n\n"
        "Tap the button below to open the app 👇",
        parse_mode="Markdown",
        reply_markup=_main_kb(),
    )


@rt.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "📖 *XStream Commands*\n\n"
        "/start — Open the app\n"
        "/search `<query>` — Quick search\n"
        "/trending — Today's trending videos\n"
        "/history — Your watch history\n"
        "/favorites — Your saved favorites\n"
        "/categories — Browse categories\n"
        "/help — This message\n\n"
        "💡 *Tips:*\n"
        "• Paste any xhamster.com URL to open it instantly\n"
        "• Type anything to search",
        parse_mode="Markdown",
        reply_markup=_main_kb(),
    )


@rt.message(Command("trending"))
async def cmd_trending(msg: Message):
    await msg.answer(
        "🔥 *Trending Now*\n\nTap to browse today's most popular videos:",
        parse_mode="Markdown",
        reply_markup=_open_btn("🔥 View Trending", "explore?sort=views&period=monthly"),
    )


@rt.message(Command("categories"))
async def cmd_categories(msg: Message):
    await msg.answer(
        "📂 *Browse Categories*\n\nExplore content by category:",
        parse_mode="Markdown",
        reply_markup=_open_btn("📂 Open Categories", "explore"),
    )


@rt.message(Command("history"))
async def cmd_history(msg: Message):
    await msg.answer(
        "🕐 *Watch History*\n\nResume where you left off:",
        parse_mode="Markdown",
        reply_markup=_open_btn("🕐 View History", "history"),
    )


@rt.message(Command("favorites"))
async def cmd_favorites(msg: Message):
    await msg.answer(
        "❤️ *Your Favorites*\n\nAll your saved videos:",
        parse_mode="Markdown",
        reply_markup=_open_btn("❤️ View Favorites", "favorites"),
    )


@rt.message(Command("search"))
async def cmd_search(msg: Message):
    query = (msg.text or "").removeprefix("/search").strip()
    if not query:
        await msg.answer(
            "Usage: `/search <query>`\n\nExample: `/search beach volleyball`",
            parse_mode="Markdown",
        )
        return
    await msg.answer(f"🔍 Searching for *{query}*…", parse_mode="Markdown",
                     reply_markup=_search_kb(query))


# ── URL handler ───────────────────────────────────────────────────────────────

@rt.message(F.text.regexp(r"https?://[a-z0-9.-]*xhamster\.[a-z]+/"))
async def handle_url(msg: Message):
    url = (msg.text or "").strip().split()[0]
    await msg.answer("Opening in XStream…", reply_markup=_video_kb(url))


# ── Plain text → search ───────────────────────────────────────────────────────

@rt.message(F.text & ~F.text.startswith("/"))
async def handle_text(msg: Message):
    query = (msg.text or "").strip()
    if len(query) < 2:
        return
    await msg.answer(
        f"🔍 Search for *{query}*?",
        parse_mode="Markdown",
        reply_markup=_search_kb(query),
    )


# ── Downloads: deliver in chat, auto-delete after video length ─────────────────

TELEGRAM_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # Bot API hard limit for uploaded files


async def send_downloaded_video(user_id: int, path: str, title: str, duration_seconds: int | None) -> None:
    """Send a downloaded video into the user's chat (not the Mini App), then
    schedule its deletion after a delay equal to the video's own length."""
    size = os.path.getsize(path) if os.path.exists(path) else 0
    if size > TELEGRAM_MAX_UPLOAD_BYTES:
        try:
            os.remove(path)
        except OSError:
            pass
        raise RuntimeError(
            f"video is {size / 1024 / 1024:.0f}MB — Telegram bots can only send files up to 50MB. "
            "Try a lower quality."
        )

    try:
        caption = f"🎬 {title}"
        if duration_seconds:
            caption += f"\n\n⏳ Auto-deletes in {duration_seconds // 60}m {duration_seconds % 60}s"
        msg = await bot.send_video(
            chat_id=user_id,
            video=FSInputFile(path),
            caption=caption[:1024],
            supports_streaming=True,
            request_timeout=300,
        )
    except TelegramEntityTooLarge:
        raise RuntimeError("video is too large for Telegram (50MB bot limit). Try a lower quality.")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    if duration_seconds and duration_seconds > 0:
        asyncio.create_task(_auto_delete(user_id, msg.message_id, duration_seconds))


async def _auto_delete(chat_id: int, message_id: int, delay: int) -> None:
    try:
        await asyncio.sleep(delay)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.debug("auto-delete of message %s failed: %s", message_id, e)


async def notify_download_failed(user_id: int, reason: str) -> None:
    try:
        await bot.send_message(user_id, f"⚠️ Download failed: {reason}")
    except Exception:
        pass


# ── Bot startup ───────────────────────────────────────────────────────────────

async def run_bot():
    await bot.set_my_commands([
        BotCommand(command="start",      description="Open XStream"),
        BotCommand(command="search",     description="Search videos"),
        BotCommand(command="trending",   description="Trending videos"),
        BotCommand(command="categories", description="Browse categories"),
        BotCommand(command="history",    description="Watch history"),
        BotCommand(command="favorites",  description="My favorites"),
        BotCommand(command="help",       description="Help"),
    ])
    logger.info("Bot polling…")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    except asyncio.CancelledError:
        pass
    finally:
        await bot.session.close()
