"""Async SQLite database layer for XStream."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import aiosqlite

DB_PATH = "xstream.db"
logger = logging.getLogger(__name__)

_CREATE_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    last_name   TEXT,
    created_at  INTEGER NOT NULL DEFAULT (unixepoch()),
    last_seen   INTEGER NOT NULL DEFAULT (unixepoch()),
    settings    TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    video_url       TEXT    NOT NULL,
    video_title     TEXT,
    video_thumbnail TEXT,
    video_duration  TEXT,
    watch_position  INTEGER NOT NULL DEFAULT 0,
    watched_at      INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE(user_id, video_url)
);

CREATE TABLE IF NOT EXISTS favorites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    video_url       TEXT    NOT NULL,
    video_title     TEXT,
    video_thumbnail TEXT,
    video_duration  TEXT,
    added_at        INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE(user_id, video_url)
);

CREATE TABLE IF NOT EXISTS bookmarks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    video_url   TEXT    NOT NULL,
    video_title TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    added_at    INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE(user_id, video_url)
);

CREATE INDEX IF NOT EXISTS idx_history_user   ON history(user_id, watched_at DESC);
CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id, added_at DESC);
CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks(user_id);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_CREATE_SQL)
        await db.commit()
    logger.info("Database initialised at %s", DB_PATH)


# ── Users ─────────────────────────────────────────────────────────────────────

async def upsert_user(
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users(user_id, username, first_name, last_name, last_seen)
               VALUES(?, ?, ?, ?, unixepoch())
               ON CONFLICT(user_id) DO UPDATE SET
                   username   = excluded.username,
                   first_name = excluded.first_name,
                   last_name  = excluded.last_name,
                   last_seen  = unixepoch()""",
            (user_id, username, first_name, last_name),
        )
        await db.commit()


async def get_user_settings(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT settings FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                try:
                    return json.loads(row[0])
                except Exception:
                    return {}
    return {}


async def update_user_settings(user_id: int, settings: dict) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET settings = ? WHERE user_id = ?",
            (json.dumps(settings), user_id),
        )
        await db.commit()


# ── History ───────────────────────────────────────────────────────────────────

async def add_to_history(
    user_id: int,
    video_url: str,
    video_title: str | None = None,
    video_thumbnail: str | None = None,
    video_duration: str | None = None,
    watch_position: int = 0,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO history(user_id, video_url, video_title, video_thumbnail,
                                   video_duration, watch_position, watched_at)
               VALUES(?, ?, ?, ?, ?, ?, unixepoch())
               ON CONFLICT(user_id, video_url) DO UPDATE SET
                   watch_position = excluded.watch_position,
                   watched_at     = unixepoch(),
                   video_title    = COALESCE(excluded.video_title, video_title),
                   video_thumbnail= COALESCE(excluded.video_thumbnail, video_thumbnail),
                   video_duration = COALESCE(excluded.video_duration, video_duration)""",
            (user_id, video_url, video_title, video_thumbnail, video_duration, watch_position),
        )
        await db.commit()


async def get_history(user_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT video_url, video_title, video_thumbnail, video_duration,
                      watch_position, watched_at
               FROM history WHERE user_id = ?
               ORDER BY watched_at DESC LIMIT ? OFFSET ?""",
            (user_id, limit, offset),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_watch_position(user_id: int, video_url: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT watch_position FROM history WHERE user_id=? AND video_url=?",
            (user_id, video_url),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def clear_history(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM history WHERE user_id=?", (user_id,))
        await db.commit()


# ── Favorites ─────────────────────────────────────────────────────────────────

async def add_to_favorites(
    user_id: int,
    video_url: str,
    video_title: str | None = None,
    video_thumbnail: str | None = None,
    video_duration: str | None = None,
) -> bool:
    """Returns True if newly added, False if already existed."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """INSERT INTO favorites(user_id, video_url, video_title,
                                         video_thumbnail, video_duration)
                   VALUES(?, ?, ?, ?, ?)""",
                (user_id, video_url, video_title, video_thumbnail, video_duration),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_from_favorites(user_id: int, video_url: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM favorites WHERE user_id=? AND video_url=?",
            (user_id, video_url),
        )
        await db.commit()
        return cur.rowcount > 0


async def is_favorite(user_id: int, video_url: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM favorites WHERE user_id=? AND video_url=?",
            (user_id, video_url),
        ) as cur:
            return await cur.fetchone() is not None


async def get_favorites(user_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT video_url, video_title, video_thumbnail, video_duration, added_at
               FROM favorites WHERE user_id=?
               ORDER BY added_at DESC LIMIT ? OFFSET ?""",
            (user_id, limit, offset),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ── Bookmarks ─────────────────────────────────────────────────────────────────

async def add_bookmark(
    user_id: int, video_url: str, video_title: str | None = None, position: int = 0
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO bookmarks(user_id, video_url, video_title, position)
               VALUES(?, ?, ?, ?)
               ON CONFLICT(user_id, video_url) DO UPDATE SET
                   position  = excluded.position,
                   added_at  = unixepoch()""",
            (user_id, video_url, video_title, position),
        )
        await db.commit()


async def get_bookmarks(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT video_url, video_title, position, added_at FROM bookmarks WHERE user_id=? ORDER BY added_at DESC",
            (user_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def remove_bookmark(user_id: int, video_url: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM bookmarks WHERE user_id=? AND video_url=?",
            (user_id, video_url),
        )
        await db.commit()


# ── Stats ─────────────────────────────────────────────────────────────────────

async def get_user_stats(user_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM history WHERE user_id=?", (user_id,)
        ) as cur:
            history_count = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM favorites WHERE user_id=?", (user_id,)
        ) as cur:
            fav_count = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM bookmarks WHERE user_id=?", (user_id,)
        ) as cur:
            bm_count = (await cur.fetchone())[0]
    return {
        "history_count": history_count,
        "favorites_count": fav_count,
        "bookmarks_count": bm_count,
    }
