import re
import chompjs

from selectolax.lexbor import LexborHTMLParser

REGEX_M3U8 = re.compile(r'https://[^"]*?_TPL_\.(?:h264|av1)\.mp4\.m3u8')
REGEX_AUTHOR_SHORTS = re.compile(r'"name":"(.*?)"')
REGEX_THUMBNAIL = re.compile(r'<meta property="og:image" content="(.*?)"/>')
REGEX_LENGTH = re.compile(r'<span class="eta">(.*?)</span>')
REGEX_AVATAR = re.compile(r"background-image: url\('(.*?)'\)")
REGEX_LIKES_SHORTS = re.compile(r'"likes":(.*?),"')

headers = {
    "Referer": "https://www.xhamster.com/"
}


def _fmt_duration(seconds) -> str:
    try:
        s = int(seconds)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{sec:02d}"
        return f"{m}:{sec:02d}"
    except Exception:
        return ""


def _fmt_views(views) -> str:
    try:
        v = int(views)
        if v >= 1_000_000:
            return f"{v / 1_000_000:.1f}M views"
        if v >= 1_000:
            return f"{v / 1_000:.1f}K views"
        return f"{v} views"
    except Exception:
        return ""


def _parse_video_thumbs(thumbs: list) -> list[dict]:
    """Convert xHamster's videoThumbProps JSON into the standardised dict format.

    Only includes keys that the Video dataclass accepts — no extra kwargs that
    would break Video.__init__() (which uses slots=True).
    """
    results = []
    for thumb in thumbs:
        if not isinstance(thumb, dict):
            continue
        url = thumb.get("pageURL")
        if not url:
            continue
        landing = thumb.get("landing") or {}
        results.append({
            "url":           url,
            "title":         thumb.get("title"),
            "thumbnail":     thumb.get("thumbURL") or thumb.get("imageURL"),
            "video_id":      str(thumb.get("id", "")),
            "length":        _fmt_duration(thumb["duration"]) if thumb.get("duration") else None,
            "views":         _fmt_views(thumb["views"]) if thumb.get("views") else None,
            "preview_video": thumb.get("trailerURL") or thumb.get("trailerFallbackUrl"),
            "uploader_name": landing.get("name"),
        })
    return results


# All known top-level keys that can hold a videoThumbProps list
_VIDEO_THUMB_PATHS = [
    ("searchResult",),
    ("videoListComponent",),
    ("videoSectionComponent",),
    ("channelVideosComponent",),
    ("pornstarVideosComponent",),
    ("relatedVideosComponent",),
    ("creatorVideosComponent",),
    ("tabSetComponent",),
    ("extendedVideoSectionComponent",),
]


def _extract_from_initials(html_content: str) -> list[dict]:
    """Primary extraction path: read JSON from window.initials."""
    parser = LexborHTMLParser(html_content)
    script = parser.css_first("script#initials-script")
    if not script:
        return []
    try:
        raw = script.text().split("window.initials=", 1)[-1].strip().rstrip(";")
        data = chompjs.parse_js_object(raw)
    except Exception:
        return []

    # Walk known key paths looking for the video list
    for path in _VIDEO_THUMB_PATHS:
        node = data
        for k in path:
            node = node.get(k) if isinstance(node, dict) else None
        # The value itself might be the list, or it might be nested under videoThumbProps
        if isinstance(node, list) and node:
            results = _parse_video_thumbs(node)
            if results:
                return results
        if isinstance(node, dict):
            thumbs = node.get("videoThumbProps") or node.get("thumbProps") or []
            if thumbs:
                results = _parse_video_thumbs(thumbs)
                if results:
                    return results

    return []


def _extract_from_html(html_content: str) -> list[dict]:
    """Legacy fallback: extract from old DOM structure."""
    parser = LexborHTMLParser(html_content)
    stuff = []
    videos_container = (
        parser.css_first('div[data-role="video-section-content-role"]')
        or parser.css_first("div.tabsAndLists-d9218")
        or parser.css_first('div[data-role="favorites-video-collections"]')
    )
    if not videos_container:
        return stuff

    for video in videos_container.css("div.video-thumb"):
        video_id = video.attributes.get("data-video-id")
        a_tag = video.css_first('a[data-role="thumb-link"]')
        if a_tag:
            url = a_tag.attributes.get("href")
            preview_video = a_tag.attributes.get("data-previewvideo")
            title = a_tag.attributes.get("aria-label")
        else:
            url = preview_video = title = None
        if not url:
            continue
        length_el = video.css_first('[data-role="video-duration"]')
        length = length_el.text(strip=True) if length_el else None
        img_tag = video.css_first('img[data-role="thumb-preview-img"]')
        thumbnail = img_tag.attributes.get("src") if img_tag else None
        views_el = video.css_first("div.video-thumb-views")
        views = views_el.text(strip=True) if views_el else None
        stuff.append({
            "title": title, "length": length, "video_id": video_id,
            "url": url, "preview_video": preview_video,
            "thumbnail": thumbnail, "views": views,
        })
    return stuff


def extractor_videos(html_content: str) -> list[dict]:
    """Extract video list from any xHamster listing or search page."""
    results = _extract_from_initials(html_content)
    if results:
        return results
    return _extract_from_html(html_content)


def extractor_shorts(html_content: str) -> list[dict[str, str]]:
    parser = LexborHTMLParser(html_content)
    stuff = []

    # Try JSON first
    script = parser.css_first("script#initials-script")
    if script:
        try:
            raw = script.text().split("window.initials=", 1)[-1].strip().rstrip(";")
            data = chompjs.parse_js_object(raw)
            for key in ("shortsComponent", "momentListComponent", "searchResult"):
                node = data.get(key, {}) or {}
                thumbs = node.get("momentProps") or node.get("videoThumbProps") or []
                if thumbs:
                    results = _parse_video_thumbs(thumbs)
                    if results:
                        return results
        except Exception:
            pass

    # Legacy HTML fallback for shorts
    videos = parser.css_first('div[data-role="video-section-container"]')
    if not videos:
        return stuff
    for video in videos.css(
        "div.item-74fdf.thumb-list__item.video-thumb.video-thumb__moment.thumb-list__item--can-view"
    ):
        video_id = video.attributes.get("data-video-id")
        a_tag = video.css_first("a")
        if not a_tag:
            continue
        url = a_tag.attributes.get("href")
        preview_video = a_tag.attributes.get("data-previewvideo")
        img_tag = video.css_first("img")
        thumbnail = img_tag.attributes.get("src") if img_tag else None
        title_el = video.css_first("a[title]")
        title = title_el.attributes.get("title") if title_el else None
        views_el = video.css_first("div.video-thumb-views")
        views = views_el.text(strip=True) if views_el else None
        stuff.append({
            "title": title, "video_id": video_id, "url": url,
            "preview_video": preview_video, "thumbnail": thumbnail, "views": views,
        })
    return stuff


def build_page_url(url: str, is_search: bool, idx: int) -> str:
    if is_search:
        joiner = "&" if "?" in url else "?"
        return f"{url}{joiner}page={idx}"
    if idx == 1:
        return url
    return f"{url}/{idx}"
