---
name: xHamster extractor fix
description: Why HTML CSS selectors no longer work and where the data actually lives
---

## Rule
Parse video data from `window.initials` JSON in `<script id="initials-script">`, not from HTML DOM nodes.

## Why
xHamster redesigned their frontend; all video list data is now embedded as JSON in the page rather than rendered as HTML elements. The old `div[data-role="video-section-content-role"]` / `div.video-thumb` selectors return nothing.

## How to apply
In `xhamster_api/modules/consts.py`, `extractor_videos()`:
1. Grab `<script#initials-script>`, split on `window.initials=`, parse with `chompjs.parse_js_object`.
2. Walk candidate paths like `data["searchResult"]["videoThumbProps"]`, `data["videoListComponent"]["videoThumbProps"]` etc.
3. Map each thumb dict: url=pageURL, title=title, thumbnail=thumbURL, length=fmt(duration), views=fmt(views), preview_video=trailerURL, uploader_name=landing.name.
4. Fall back to old HTML parsing only if JSON extraction yields nothing.

Key JSON fields per video: id, duration (seconds int), title, pageURL, thumbURL, imageURL, trailerURL, views (int), landing.{name, link, logo}.
