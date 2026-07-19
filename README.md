# ⚡ Arch Tech — By Shashank

A fast, modern HD video streaming web application. Stream and search thousands of videos instantly in your browser — no account required, no downloads needed.

---

## Features

- 🔥 **Fresh home feed** — Different content every time you open the app
- 🔍 **Search & Explore** — Find anything by keyword or browse by category
- 📺 **HD Streaming** — Adaptive quality: 144p up to 1080p+
- ⬇️ **Video Download** — Download any video as mp4 to your device
- ❤️ **Favourites** — Save videos, track watch history, resume playback
- 🔒 **Auto sign-in** — No login required, identity stored locally
- 📱 **Mobile-first** — Responsive design, touch-friendly controls
- 🎬 **PiP & Fullscreen** — Picture-in-picture and fullscreen modes

---

## Setup

### Requirements

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) (recommended) or `pip`

### Install & run

```bash
# Install dependencies
uv sync
# or: pip install fastapi uvicorn httpx aiosqlite curl_cffi selectolax chompjs eaf-base-api m3u8

# Start the server
python main.py
```

Then open **http://localhost:5000** in your browser.

---

## Environment Variables

| Variable         | Required | Description                                 |
|-----------------|----------|---------------------------------------------|
| `SESSION_SECRET` | No       | Optional secret for future session signing  |

No API keys, no Telegram token, no OAuth — just run and go.

---

## Architecture

```
main.py          — Uvicorn entry point
server.py        — FastAPI backend (API routes, HLS proxy)
database.py      — Async SQLite (history, favourites, settings)
static/
  index.html     — Single-page frontend (vanilla JS, HLS.js)
xhamster_api/    — Video data engine (internal, not user-facing)
downloads/       — Temp folder for in-progress mp4 downloads (auto-cleaned)
```

---

## API Routes

| Method | Route                  | Description                        |
|--------|------------------------|------------------------------------|
| GET    | `/api/search`          | Search videos                      |
| GET    | `/api/trending`        | Trending / latest videos           |
| GET    | `/api/video`           | Full video metadata + stream URL   |
| GET    | `/api/related`         | Related videos                     |
| GET    | `/api/categories`      | All categories                     |
| GET    | `/api/qualities`       | Available stream qualities         |
| GET    | `/api/download-file`   | Download video as mp4              |
| GET    | `/proxy/m3u8`          | HLS playlist proxy                 |
| GET    | `/proxy/seg`           | HLS segment proxy                  |
| *      | `/api/user/*`          | History, favourites, settings      |

---

## Built by

**Arch Tech** · By Shashank
