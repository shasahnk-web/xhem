# XStream — Telegram Bot + Mini App

A Telegram bot and Mini App that lets users stream xHamster videos with full metadata, directly inside Telegram. No downloads are ever sent to users — all content is streamed via an HLS proxy.

## Stack

- **Python 3.12** / **FastAPI** (web server + API)
- **aiogram 3.x** (Telegram bot)
- **xhamster_api** (local library — scrapes xHamster)
- **HLS.js** (video playback in the Mini App)

## How to run

```
python main.py
```

This starts **uvicorn** on port 5000. The FastAPI lifespan also launches the aiogram bot in the background via `asyncio.create_task`.

## Key endpoints

| Route | Purpose |
|---|---|
| `GET /` | Telegram Mini App (static/index.html) |
| `GET /api/search?q=...` | Search videos (returns JSON list) |
| `GET /api/video?url=...` | Fetch full video metadata + m3u8 base |
| `GET /api/qualities?url=...` | Probe which quality variants exist |
| `GET /proxy/m3u8?url=...&quality=...` | Proxy + rewrite HLS playlist |
| `GET /proxy/seg?url=...` | Proxy individual TS segments |

## Secrets required

| Secret | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `SESSION_SECRET` | Already set |

## Architecture

```
main.py
  └─ uvicorn → server.py (FastAPI)
       ├─ lifespan starts bot.py (aiogram polling)
       ├─ /api/* routes → xhamster_api (async scraping)
       ├─ /proxy/* routes → HLS stream proxying
       └─ / → static/index.html (Mini App SPA)
```

## User preferences

- Single-file Mini App (inline CSS+JS in index.html)
- Dark, premium design with pink/purple gradient accent
- No direct video file downloads — streaming only
