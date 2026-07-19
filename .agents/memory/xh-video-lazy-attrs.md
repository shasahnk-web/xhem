---
name: xhamster_api lazy Video attributes
description: get_video() returns a Video object whose fields can raise DataNotLoadedError on access; how to read attributes safely.
---

`xhclient.get_video(url)` returns a `Video` object that is populated lazily. Fields like
`views`, `likes`, `dislikes`, `tags`, `categories`, `pornstars`, `rating_percentage`,
`uploader_subscribers` are not guaranteed to be filled from the initial fetch. Accessing
an unpopulated field directly (`v.views`) raises `base_api.modules.errors.DataNotLoadedError`
instead of returning `None` — this crashes any endpoint that reads these fields directly,
producing an HTTP 500 with no obvious code bug (the field name looks legit).

**Why:** the library trades convenience for guarding against silently-wrong data — it would
rather crash loudly than let you read a field that was never fetched. But dataclasses can
have dozens of such fields, and it's not obvious from the outside which ones are "safe" for
a given fetch path.

**How to apply:** never access `Video` (or similar lazy-loaded) attributes directly in
request handlers. Use a safe getter that catches `DataNotLoadedError` and returns a default,
e.g.:

```python
try:
    from base_api.modules.errors import DataNotLoadedError as _DNLE
except ImportError:
    class _DNLE(Exception):
        pass

def _sg(obj, attr, default=None):
    try:
        val = getattr(obj, attr, default)
        return default if val is None else val
    except _DNLE:
        return default
```

Apply `_sg(v, "attr", default)` for every field read off a `Video` object in any endpoint,
not just the ones you've already seen fail — untested fields can raise the same error under
different fetch conditions. `m3u8_base_url` and `title` have been observed to load reliably;
treat everything else as potentially lazy.

Keep the `except ImportError` fallback narrow (define a private sentinel exception class)
rather than falling back to bare `Exception`, or the safe getter will silently swallow real
bugs if the import path ever breaks.
