---
name: xhamster_api Video constructor slots
description: Extractor dict must only contain known Video dataclass fields
---

## Rule
The `Video` dataclass in base_api uses `slots=True`. Passing any unknown keyword argument to `Video.__init__()` raises `TypeError: got an unexpected keyword argument` and the video is silently dropped by the helper worker.

## Why
`Helper.video_worker` calls `self.constructor(core=self.core, **video_data)` where `video_data` is the full dict returned by `extractor_videos`. If you add convenience fields (like `_thumbnail_hq`, `_is_uhd`) they will crash construction.

## How to apply
Only include these keys in the extractor output dict:
url, title, thumbnail, video_id, length, views, preview_video, uploader_name, uploader_subscribers, tags, categories, pornstars, rating_percentage, likes, dislikes, m3u8_base_url.

Any extra data needed by the server layer should be derived from the Video object attributes or fetched separately — do not store it in the extractor dict.
