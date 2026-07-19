"""Arch Tech — FastAPI backend (Vercel-compatible).

Routes:
  /api/search          — search videos
  /api/video           — full video metadata
  /api/trending        — trending / latest / popular
  /api/categories      — category list
  /api/channel         — channel metadata + videos
  /api/related         — related videos
  /api/qualities       — probe available HLS qualities
  /api/download-file   — download video as mp4 to browser
  /api/user/*          — history, favorites, bookmarks, settings
  /proxy/m3u8          — rewrite HLS playlist
  /proxy/seg           — proxy TS / fMP4 segments
  /                    — serves index.html (local dev only; Vercel uses public/)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import random
import re
import time
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

try:
    from base_api.modules.errors import DataNotLoadedError as _DNLE
except ImportError:
    class _DNLE(Exception):  # type: ignore[no-redef]
        pass


def _sg(obj, attr, default=None):
    """Safe attribute getter — returns default instead of raising DataNotLoadedError."""
    try:
        val = getattr(obj, attr, default)
        return default if val is None else val
    except _DNLE:
        return default


import database as db
from xhamster_api import Client

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── Lazy initialisation (required for Vercel serverless) ─────────────────────
# Vercel does not reliably fire lifespan/startup events; we init on first use.

_init_lock = asyncio.Lock()
_initialized = False
xhclient: Client | None = None


async def _ensure_init() -> None:
    global _initialized, xhclient
    if _initialized:
        return
    async with _init_lock:
        if _initialized:
            return
        await db.init_db()
        xhclient = Client()
        _initialized = True


# ── SSRF allowlist ────────────────────────────────────────────────────────────

_ALLOWED_HOSTS = re.compile(
    r"^([a-z0-9-]+\.)*("
    r"xhamster\.com|xhamster\.desi|xhamster\.one|xhamster5\.com|"
    r"xh-cdn\.com|xhcdn\.com|xhcdn2\.com|xhpingcdn\.com|"
    r"thumb-v\d+\.xhpingcdn\.com|"
    r"ic-vt-nss\.xhpingcdn\.com|thumb-nss\.xhpingcdn\.com|"
    r"ic-tt-nss\.xhpingcdn\.com|thumb-v-nss\.xhpingcdn\.com"
    r")$",
    re.IGNORECASE,
)


def _guard(url: str) -> None:
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            raise ValueError(f"bad scheme: {p.scheme}")
        if not _ALLOWED_HOSTS.match(p.netloc or ""):
            raise ValueError(f"host not allowlisted: {p.netloc}")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Arch Tech API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def b64enc(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def b64dec(s: str) -> str:
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    try:
        return base64.urlsafe_b64decode(s.encode()).decode()
    except Exception as exc:
        raise HTTPException(400, f"invalid base64: {exc}") from exc


async def _fetch(url: str, timeout: int = 15):
    hdrs = {"Referer": "https://xhamster.com/", "Origin": "https://xhamster.com"}
    try:
        if xhclient:
            r = await xhclient.core.session.get(url, headers=hdrs)
            if r.status_code == 200:
                return r
    except Exception:
        pass
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as hx:
        r = await hx.get(url, headers=hdrs)
        return r if r.status_code == 200 else None


def _video_dict(v) -> dict:
    return {
        "title":    getattr(v, "title", None),
        "url":      getattr(v, "url", None),
        "thumbnail": getattr(v, "thumbnail", None),
        "duration": getattr(v, "length", None),
        "views":    getattr(v, "views", None),
        "video_id": getattr(v, "video_id", None),
        "preview":  getattr(v, "preview_video", None),
        "uploader": getattr(v, "uploader_name", None),
    }


# ── Categories ────────────────────────────────────────────────────────────────

CATEGORIES = [
    {"id": "amateur",          "label": "Amateur",      "emoji": "📹"},
    {"id": "milf",             "label": "MILF",         "emoji": "💋"},
    {"id": "teen",             "label": "Teen",         "emoji": "🌸"},
    {"id": "lesbian",          "label": "Lesbian",      "emoji": "🌈"},
    {"id": "big-tits",         "label": "Big Tits",     "emoji": "🔥"},
    {"id": "anal",             "label": "Anal",         "emoji": "💦"},
    {"id": "mature",           "label": "Mature",       "emoji": "👑"},
    {"id": "mom",              "label": "Mom",          "emoji": "👩"},
    {"id": "bdsm",             "label": "BDSM",         "emoji": "⛓"},
    {"id": "old-young",        "label": "Old & Young",  "emoji": "🎭"},
    {"id": "russian",          "label": "Russian",      "emoji": "🇷🇺"},
    {"id": "german",           "label": "German",       "emoji": "🇩🇪"},
    {"id": "vintage",          "label": "Vintage",      "emoji": "🎞"},
    {"id": "hairy",            "label": "Hairy",        "emoji": "🌿"},
    {"id": "big-natural-tits", "label": "Natural Tits", "emoji": "🍈"},
    {"id": "granny",           "label": "Granny",       "emoji": "👵"},
    {"id": "18-year-old",      "label": "18+",          "emoji": "🎂"},
    {"id": "brutal-sex",       "label": "Rough",        "emoji": "⚡"},
    {"id": "porn-for-women",   "label": "For Women",    "emoji": "💝"},
]


# ── Search ────────────────────────────────────────────────────────────────────

@app.get("/api/search")
async def api_search(
    q:    str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    sort: str = Query(""),
):
    await _ensure_init()
    results = []
    try:
        async for result in xhclient.search_videos(
            q, pages=page, load_html=False, sort_by=sort or None,
        ):
            try:
                results.append(_video_dict(result.video))
            except Exception as e:
                logger.debug("skip result: %s", e)
    except Exception as e:
        raise HTTPException(502, f"search failed: {e}")
    return JSONResponse(results)


# ── Trending / Latest / Popular ───────────────────────────────────────────────

_FEED_QUERY_POOL = [
    "amateur", "milf", "teen", "big-tits", "lesbian", "anal",
    "mature", "russian", "german", "hairy", "brutal-sex", "old-young",
]


@app.get("/api/trending")
async def api_trending(
    sort:     str  = Query("views"),
    period:   str  = Query("monthly"),
    category: str  = Query(""),
    page:     int  = Query(1, ge=1),
    fresh:    bool = Query(False),
):
    await _ensure_init()
    results = []
    query = category or (random.choice(_FEED_QUERY_POOL) if fresh else "amateur")
    page_to_use = random.randint(1, 3) if fresh else page
    try:
        async for result in xhclient.search_videos(
            query=query, pages=page_to_use, load_html=False,
            sort_by=sort or None, date=period or None,
        ):
            try:
                results.append(_video_dict(result.video))
            except Exception as e:
                logger.debug("skip result: %s", e)
    except Exception as e:
        raise HTTPException(502, f"trending failed: {e}")
    if fresh:
        random.shuffle(results)
    return JSONResponse(results)


# ── Categories ────────────────────────────────────────────────────────────────

@app.get("/api/categories")
async def api_categories():
    return JSONResponse(CATEGORIES)


# ── Full video metadata ───────────────────────────────────────────────────────

@app.get("/api/video")
async def api_video(url: str = Query(...)):
    await _ensure_init()
    try:
        v = await xhclient.get_video(url)
    except Exception as e:
        raise HTTPException(502, f"could not fetch video: {e}")

    m3u8 = _sg(v, "m3u8_base_url")
    return JSONResponse({
        "title":         _sg(v, "title"),
        "url":           _sg(v, "url", url),
        "thumbnail":     _sg(v, "thumbnail"),
        "m3u8_base":     m3u8,
        "proxy_url":     f"/proxy/m3u8?url={b64enc(m3u8)}" if m3u8 else None,
        "likes":         _sg(v, "likes"),
        "dislikes":      _sg(v, "dislikes"),
        "rating":        _sg(v, "rating_percentage"),
        "views":         _sg(v, "views"),
        "uploader":      _sg(v, "uploader_name"),
        "uploader_subs": _sg(v, "uploader_subscribers"),
        "tags":          _sg(v, "tags", []),
        "categories":    _sg(v, "categories", []),
        "pornstars":     _sg(v, "pornstars", []),
        "duration":      _sg(v, "length"),
        "video_id":      _sg(v, "video_id"),
    })


# ── Related videos ────────────────────────────────────────────────────────────

@app.get("/api/related")
async def api_related(url: str = Query(...)):
    await _ensure_init()
    results = []
    try:
        v = await xhclient.get_video(url)
        tags = _sg(v, "tags", [])[:3]
        cats = _sg(v, "categories", [])[:1]
        query = " ".join(tags or cats or ["trending"])
        async for result in xhclient.search_videos(query, pages=1, load_html=False):
            try:
                d = _video_dict(result.video)
                if d.get("url") != url:
                    results.append(d)
            except Exception:
                pass
            if len(results) >= 10:
                break
    except Exception as e:
        raise HTTPException(502, f"related failed: {e}")
    return JSONResponse(results)


# ── Channel ───────────────────────────────────────────────────────────────────

@app.get("/api/channel")
async def api_channel(url: str = Query(...), page: int = Query(1, ge=1)):
    await _ensure_init()
    try:
        ch = await xhclient.get_channel(url)
        videos = []
        async for result in ch.videos(pages=page, load_html=False):
            try:
                videos.append(_video_dict(result.video))
            except Exception:
                pass
        return JSONResponse({
            "name":         ch.name,
            "avatar":       ch.avatar_url,
            "subscribers":  ch.subscribers_count,
            "videos_count": ch.videos_count,
            "views":        ch.total_views_count,
            "url":          url,
            "videos":       videos,
        })
    except Exception as e:
        raise HTTPException(502, f"channel failed: {e}")


# ── Qualities probe ───────────────────────────────────────────────────────────

_QUALITIES = ["2048p", "1080p", "720p", "480p", "360p", "240p", "144p"]


@app.get("/api/qualities")
async def api_qualities(url: str = Query(...)):
    async def _probe(q: str):
        u = url.replace("_TPL_", q)
        try:
            _guard(u)
            r = await _fetch(u)
            return q if r else None
        except Exception:
            return None

    hits = await asyncio.gather(*[_probe(q) for q in _QUALITIES])
    return JSONResponse([q for q in hits if q] or ["720p"])


# ── Download — browser file download ─────────────────────────────────────────

# Writable tmp dir on both Vercel and local
DOWNLOAD_DIR = "/tmp/downloads" if os.environ.get("VERCEL") else "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

_active_downloads: set[int] = set()
_DOWNLOAD_COOLDOWN = 30
_last_download_at: dict[int, float] = {}


@app.get("/api/download-file")
async def api_download_file(
    url:     str = Query(...),
    quality: str = Query("240p"),
    user_id: int = Query(0),
):
    await _ensure_init()
    from base_api.modules.config import DownloadConfigHLS

    now = time.time()
    if user_id and user_id in _active_downloads:
        raise HTTPException(429, "A download is already in progress.")
    if user_id and now - _last_download_at.get(user_id, 0) < _DOWNLOAD_COOLDOWN:
        raise HTTPException(429, "Please wait before requesting another download.")

    path: str | None = None
    try:
        if user_id:
            _active_downloads.add(user_id)
            _last_download_at[user_id] = now

        v = await xhclient.get_video(url)
        title    = _sg(v, "title", "video") or "video"
        video_id = _sg(v, "video_id", str(int(time.time())))
        m3u8     = _sg(v, "m3u8_base_url")
        if not m3u8:
            raise HTTPException(502, "No stream found for this video.")

        safe_title = re.sub(r'[^\w\s-]', '', title)[:60].strip().replace(' ', '_')
        filename   = f"{safe_title or video_id}.mp4"
        path       = os.path.join(DOWNLOAD_DIR, f"{video_id}_{int(time.time())}.mp4")

        config = DownloadConfigHLS(
            quality=quality or "240p",
            path=path,
            no_title=True,
            remux=False,
        )
        ok = await v.download(configuration=config)
        if not ok or not os.path.exists(path):
            raise HTTPException(502, "Could not download this video — try a lower quality.")

        return FileResponse(
            path,
            media_type="video/mp4",
            filename=filename,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        raise
    except Exception as e:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        raise HTTPException(502, str(e))
    finally:
        if user_id:
            _active_downloads.discard(user_id)


# ── User: upsert ─────────────────────────────────────────────────────────────

@app.post("/api/user/upsert")
async def upsert_user_endpoint(data: dict):
    await _ensure_init()
    uid = data.get("user_id")
    if not uid:
        raise HTTPException(400, "user_id required")
    await db.upsert_user(uid, data.get("username"), data.get("first_name"), data.get("last_name"))
    return JSONResponse({"ok": True})


# ── User: history ─────────────────────────────────────────────────────────────

@app.get("/api/user/history")
async def get_history(user_id: int = Query(...), limit: int = 20, offset: int = 0):
    await _ensure_init()
    return JSONResponse(await db.get_history(user_id, limit, offset))


@app.post("/api/user/history")
async def post_history(data: dict):
    await _ensure_init()
    uid = data.get("user_id")
    if not uid:
        raise HTTPException(400, "user_id required")
    await db.upsert_user(uid)
    await db.add_to_history(
        uid, data["video_url"], data.get("video_title"),
        data.get("video_thumbnail"), data.get("video_duration"),
        data.get("watch_position", 0),
    )
    return JSONResponse({"ok": True})


@app.put("/api/user/progress")
async def update_progress(data: dict):
    await _ensure_init()
    uid = data.get("user_id")
    if not uid:
        raise HTTPException(400, "user_id required")
    await db.upsert_user(uid)
    await db.add_to_history(uid, data["video_url"], watch_position=data.get("position", 0))
    return JSONResponse({"ok": True})


@app.get("/api/user/progress")
async def get_progress(user_id: int = Query(...), video_url: str = Query(...)):
    await _ensure_init()
    pos = await db.get_watch_position(user_id, video_url)
    return JSONResponse({"position": pos})


@app.delete("/api/user/history")
async def clear_history(user_id: int = Query(...)):
    await _ensure_init()
    await db.clear_history(user_id)
    return JSONResponse({"ok": True})


# ── User: favorites ───────────────────────────────────────────────────────────

@app.get("/api/user/favorites")
async def get_favorites(user_id: int = Query(...), limit: int = 20, offset: int = 0):
    await _ensure_init()
    return JSONResponse(await db.get_favorites(user_id, limit, offset))


@app.post("/api/user/favorites")
async def add_favorite(data: dict):
    await _ensure_init()
    uid = data.get("user_id")
    if not uid:
        raise HTTPException(400, "user_id required")
    await db.upsert_user(uid)
    added = await db.add_to_favorites(
        uid, data["video_url"], data.get("video_title"),
        data.get("video_thumbnail"), data.get("video_duration"),
    )
    return JSONResponse({"ok": True, "added": added})


@app.delete("/api/user/favorites")
async def remove_favorite(user_id: int = Query(...), video_url: str = Query(...)):
    await _ensure_init()
    removed = await db.remove_from_favorites(user_id, video_url)
    return JSONResponse({"ok": True, "removed": removed})


@app.get("/api/user/is_favorite")
async def check_favorite(user_id: int = Query(...), video_url: str = Query(...)):
    await _ensure_init()
    return JSONResponse({"is_favorite": await db.is_favorite(user_id, video_url)})


# ── User: bookmarks ───────────────────────────────────────────────────────────

@app.get("/api/user/bookmarks")
async def get_bookmarks(user_id: int = Query(...)):
    await _ensure_init()
    return JSONResponse(await db.get_bookmarks(user_id))


@app.post("/api/user/bookmarks")
async def add_bookmark(data: dict):
    await _ensure_init()
    uid = data.get("user_id")
    if not uid:
        raise HTTPException(400, "user_id required")
    await db.upsert_user(uid)
    await db.add_bookmark(uid, data["video_url"], data.get("video_title"), data.get("position", 0))
    return JSONResponse({"ok": True})


@app.delete("/api/user/bookmarks")
async def remove_bookmark(user_id: int = Query(...), video_url: str = Query(...)):
    await _ensure_init()
    await db.remove_bookmark(user_id, video_url)
    return JSONResponse({"ok": True})


# ── User: stats + settings ────────────────────────────────────────────────────

@app.get("/api/user/stats")
async def user_stats(user_id: int = Query(...)):
    await _ensure_init()
    return JSONResponse(await db.get_user_stats(user_id))


@app.get("/api/user/settings")
async def user_settings(user_id: int = Query(...)):
    await _ensure_init()
    return JSONResponse(await db.get_user_settings(user_id))


@app.post("/api/user/settings")
async def save_settings(data: dict):
    await _ensure_init()
    uid = data.get("user_id")
    if not uid:
        raise HTTPException(400, "user_id required")
    await db.upsert_user(uid)
    await db.update_user_settings(uid, data.get("settings", {}))
    return JSONResponse({"ok": True})


# ── HLS Proxy ─────────────────────────────────────────────────────────────────

_URI_ATTR = re.compile(r'URI="([^"]+)"', re.I)


def _is_playlist(uri: str) -> bool:
    return ".m3u8" in uri.split("?")[0].lower()


def _proxy_uri(abs_url: str, quality: str, playlist: bool) -> str:
    enc = b64enc(abs_url)
    return f"/proxy/m3u8?url={enc}&quality={quality}" if playlist else f"/proxy/seg?url={enc}"


def _rewrite_m3u8(content: str, base: str, quality: str) -> str:
    out = []
    for line in content.splitlines():
        s = line.strip()
        if s == "":
            out.append(line)
        elif s.startswith("#"):
            def _sub(m: re.Match) -> str:
                raw = m.group(1)
                abs_u = raw if raw.startswith("http") else urljoin(base, raw)
                return f'URI="{_proxy_uri(abs_u, quality, _is_playlist(abs_u))}"'
            out.append(_URI_ATTR.sub(_sub, line))
        else:
            abs_url = s if s.startswith("http") else urljoin(base, s)
            out.append(_proxy_uri(abs_url, quality, _is_playlist(abs_url)))
    return "\n".join(out)


@app.get("/proxy/m3u8")
async def proxy_m3u8(url: str = Query(...), quality: str = Query("720p")):
    decoded  = b64dec(url)
    m3u8_url = decoded.replace("_TPL_", quality) if "_TPL_" in decoded else decoded
    _guard(m3u8_url)

    resp = await _fetch(m3u8_url)
    if not resp:
        raise HTTPException(502, "failed to fetch HLS playlist")

    base      = m3u8_url.rsplit("/", 1)[0] + "/"
    rewritten = _rewrite_m3u8(resp.text, base, quality)
    return Response(
        rewritten,
        media_type="application/vnd.apple.mpegurl",
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"},
    )


@app.get("/proxy/seg")
async def proxy_seg(url: str = Query(...)):
    decoded = b64dec(url)
    _guard(decoded)
    hdrs = {"Referer": "https://xhamster.com/", "Origin": "https://xhamster.com"}
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=30) as hx:
            r    = await hx.get(decoded, headers=hdrs)
            hops = 0
            while r.is_redirect and hops < 5:
                location = r.headers.get("location", "")
                if not location:
                    break
                abs_loc = location if location.startswith("http") else urljoin(decoded, location)
                _guard(abs_loc)
                r    = await hx.get(abs_loc, headers=hdrs)
                hops += 1
            if r.status_code != 200:
                raise HTTPException(502, f"upstream {r.status_code}")
            ct = r.headers.get("content-type", "video/MP2T")
            return Response(r.content, media_type=ct,
                            headers={"Access-Control-Allow-Origin": "*"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return JSONResponse({"status": "ok"})


# ── Static files (local dev only — Vercel uses public/ folder via CDN) ────────

_IS_VERCEL = bool(os.environ.get("VERCEL"))

if not _IS_VERCEL:
    class NoCacheStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"]         = "no-cache"
            response.headers["Expires"]        = "0"
            return response

    app.mount("/", NoCacheStaticFiles(directory="static", html=True), name="static")
