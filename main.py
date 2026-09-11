# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib.config import (
    TEST_SLUG, PLATFORM_UID, ELMS_SEASON_PAGES, MLMC_SEASON_PAGES,
)
from resources.lib.utils import (
    _berlin_datetime_label, normalize_slug, _find_playback_url, _message,
    _text_value, _channel_value, _clean_text, _duration_seconds,
    _looks_like_image_url,
)
from resources.lib.api import (
    request_json as _api_request_json,
    api_headers as _build_api_headers,
    feed_headers as _build_feed_headers,
    get_video as _api_get_video,
    get_livestream as _api_get_livestream,
)
from resources.lib.series_data import (
    series_weekend_label as _series_data_weekend_label,
    feed_title_year as _series_data_feed_title_year,
    series_livestream_match as _series_data_livestream_match,
    future_series_livestreams as _series_data_future_livestreams,
)
from resources.lib.onboard import (
    match_context as _onboard_match_context,
    video_is_other_series as _onboard_video_is_other_series,
    session_from_title as _onboard_session_from_title,
    video_matches as _onboard_video_matches,
    prepare_video as _onboard_prepare_video,
)
from resources.lib.routes import dispatch as _route_dispatch
from resources.lib import series_menu as _series_menu
from resources.lib import video_menu as _video_menu
from resources.lib import auth as _auth
from resources.lib import playback as _playback
from resources.lib import cache as _cache
from resources.lib import diagnostics as _diagnostics
from resources.lib import wec_events as _wec_events
from resources.lib import ui as _ui

ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1])
BASE_URL = sys.argv[0]



def L(_de, en):
    """Return the English UI string."""
    return en



# --- Lightweight response cache -------------------------------------------
# Implementation lives in resources/lib/cache.py. Keep these names here so
# existing helpers can continue to use the historical cache API unchanged.
CACHE_TTL_PAGE = _cache.CACHE_TTL_PAGE
CACHE_TTL_PREVIEW_ART = _cache.CACHE_TTL_PREVIEW_ART
CACHE_TTL_TAG_FEED = _cache.CACHE_TTL_TAG_FEED

def cache_get(key):
    return _cache.cache_get(key)

def cache_set(key, value, ttl_seconds):
    return _cache.cache_set(key, value, ttl_seconds)

def cache_clear():
    return _cache.cache_clear()


def log(message, level=xbmc.LOGINFO):
    xbmc.log("[FIAWEC+] {}".format(message), level)


_cache.configure(ADDON, log)


def setting(name, default=""):
    value = ADDON.getSetting(name)
    return value if value != "" else default


# --- Kodi UI facade --------------------------------------------------------
# Keep historical helper names in main.py while their implementation lives
# in resources/lib/ui.py. This avoids changing already-extracted modules.
def make_url(action, **params):
    return _ui.make_url(action, **params)


def add_item(label, action=None, playable=False, art=None, plot=None, **params):
    return _ui.add_item(label, action, playable, art, plot, **params)






# --- Authentication/account facade ---------------------------------------
# Keep the historical handler names in main.py so existing plugin URLs and
# route mappings remain stable while the implementation lives in auth.py.
def oauth_cookie_select_shared(): return _auth.oauth_cookie_select_shared()
def oauth_cookie_login_shared(): return _auth.oauth_cookie_login_shared()
def oauth_cookie_login_file(): return _auth.oauth_cookie_login_file()
def oauth_cookie_login_manual(): return _auth.oauth_cookie_login_manual()
def oauth_import_token_file(): return _auth.oauth_import_token_file()
def oauth_browser_refresh_import(): return _auth.oauth_browser_refresh_import()
def oauth_direct_login(): return _auth.oauth_direct_login()
def _refresh_access_token_silent(): return _auth._refresh_access_token_silent()
def _ensure_access_token(): return _auth._ensure_access_token()
def oauth_refresh(): return _auth.oauth_refresh()
def oauth_refresh_test(): return _auth.oauth_refresh_test()
def account_menu(): return _auth.account_menu(add_item, _folder_art, request_json, _api_headers, HANDLE)
def oauth_status(): return _auth.oauth_status()
def oauth_logout(): return _auth.oauth_logout()

































































































def diagnose_next_sessions():
    return _diagnostics.diagnose_next_sessions()

def diagnose_extra_content():
    return _diagnostics.diagnose_extra_content()

def _collect_video_channel_tag_feeds(value, rows=None):
    """Find VIDEO_CHANNEL_TAGS ContentFeeds recursively on a Staylive page."""
    if rows is None:
        rows = []
    if isinstance(value, dict):
        if value.get("name") == "ContentFeed":
            props = value.get("props") or {}
            if isinstance(props, dict) and props.get("type") == "VIDEO_CHANNEL_TAGS":
                rows.append({
                    "title": _text_value(props.get("title")) or "",
                    "channel_ids": props.get("id") or [],
                    "tags": props.get("tags") or [],
                    "all_tags_required": bool(props.get("allTagsRequired")),
                    "date_range": props.get("dateRangeFilter") or {},
                })
        for child in value.values():
            _collect_video_channel_tag_feeds(child, rows)
    elif isinstance(value, list):
        for child in value:
            _collect_video_channel_tag_feeds(child, rows)
    return rows


def _wec_onboard_replay_feeds(race_path):
    """Return unique WEC onboard replay VIDEO_CHANNEL_TAGS feeds for a race page."""
    clean_path = str(race_path or "").strip().lstrip("/")
    page_url = "https://api.staylive.tv/platforms/{}/pages/path/{}".format(
        PLATFORM_UID, urllib.parse.quote(clean_path, safe="")
    )
    page = _message(request_json(
        page_url, headers=_api_headers(),
        cache_ttl=CACHE_TTL_PAGE, cache_key="page:" + clean_path,
    ))
    if not isinstance(page, dict):
        return []

    found = []
    seen = set()
    for row in _collect_video_channel_tag_feeds(page):
        title = str(row.get("title") or "")
        if "onboard" not in title.lower():
            continue
        ids = row.get("channel_ids") or []
        if not isinstance(ids, list):
            ids = [ids]
        tags = row.get("tags") or []
        if not isinstance(tags, list):
            tags = [tags]
        ids = [str(x) for x in ids if str(x).strip()]
        tags = [str(x) for x in tags if str(x).strip()]
        if not ids or not tags:
            continue
        dr = row.get("date_range") or {}
        key = (tuple(ids), tuple(tags), str(dr.get("start") or ""), str(dr.get("end") or ""))
        if key in seen:
            continue
        seen.add(key)
        row["channel_ids"] = ids
        row["tags"] = tags
        found.append(row)
    return found


def _tag_feed_headers(channel_ids):
    headers = _api_headers()
    headers["X-STAYLIVE-CHANNELS"] = ",".join(str(x) for x in channel_ids)
    return headers


def _fetch_wec_tag_feed(feeddef, page=1, limit=100):
    """Fetch WEC VIDEO_CHANNEL_TAGS via platform videos-by-tag."""
    channel_ids = feeddef.get("channel_ids") or []
    tags = feeddef.get("tags") or []
    if not isinstance(channel_ids, list):
        channel_ids = [channel_ids]
    if not isinstance(tags, list):
        tags = [tags]

    channel_ids = [str(x).strip() for x in channel_ids if str(x).strip()]
    tags = [str(x).strip() for x in tags if str(x).strip()]
    if not channel_ids or not tags:
        return {}

    # Staylive requires `tags` to be ONE string. Multiple tags are comma-separated.
    # The Imola diagnostic proved channelId=6973 + tags=2026,hypercar returns videos.
    params = [
        ("limit", str(limit)),
        ("page", str(page)),
        ("tags", ",".join(tags)),
        ("channelId", channel_ids[0]),
    ]
    url = "https://api.staylive.tv/platforms/{}/videos-by-tag?{}".format(
        PLATFORM_UID, urllib.parse.urlencode(params)
    )
    return request_json(
        url, headers=_api_headers(),
        cache_ttl=CACHE_TTL_TAG_FEED,
        cache_key="racetag:{}:{}:{}".format(channel_ids[0], ",".join(tags), page),
    )


def _wec_onboard_session(title):
    """Compatibility wrapper for the refactored onboard session classifier."""
    return _onboard_session_from_title(title)

def _fetch_wec_platform_tag_feed(tags, page=1, limit=100):
    """Fetch WEC videos by tags without pinning the request to one race channel."""
    if not isinstance(tags, list):
        tags = [tags]
    tags = [str(x).strip() for x in tags if str(x).strip()]
    if not tags:
        return {}
    params = [
        ("limit", str(limit)),
        ("page", str(page)),
        ("tags", ",".join(tags)),
    ]
    url = "https://api.staylive.tv/platforms/{}/videos-by-tag?{}".format(
        PLATFORM_UID, urllib.parse.urlencode(params)
    )
    return request_json(
        url, headers=_api_headers(),
        cache_ttl=CACHE_TTL_TAG_FEED,
        cache_key="platformtag:{}:{}:{}".format(",".join(tags), page, limit),
    )


def _wec_onboard_match_context(path):
    """Compatibility wrapper for WEC race/year onboard matching context."""
    return _onboard_match_context(path)


def _wec_video_is_other_series(video):
    """Compatibility wrapper for support-series exclusion."""
    return _onboard_video_is_other_series(video)

def _fetch_video_pages(fetch_page, max_pages):
    """Fetch a Staylive videos-by-tag feed across pages, in parallel where possible.

    ``fetch_page(n)`` returns the raw response for page ``n``. Page 1 is
    always fetched first (needed to learn ``pageCount``). If the API
    reports a page count, every remaining page up to ``max_pages`` is
    fetched *concurrently* via a small thread pool instead of one at a
    time — a multi-page onboard/tag feed used to pay N sequential network
    round-trips in a row, which was the main reason opening an onboard
    folder for the first time (cold cache) could take a while. If the API
    doesn't report a page count (seen on some responses), fall back to the
    original one-page-at-a-time walk that stops as soon as a short page
    signals "no more" — safer than guessing how many pages to fetch.

    Returns the combined, in-order list of video dicts from every page.
    """
    all_videos = []
    first = fetch_page(1)
    first_videos = _extract_video_list(first)
    all_videos.extend(first_videos)
    if not first_videos:
        return all_videos

    meta = first.get("data") if isinstance(first, dict) else {}
    try:
        page_count = int((meta or {}).get("pageCount") or 0)
    except Exception:
        page_count = 0

    if page_count:
        last_page = min(page_count, max_pages)
        remaining = list(range(2, last_page + 1))
        if remaining:
            paged = {}
            with ThreadPoolExecutor(max_workers=min(6, len(remaining))) as pool:
                futures = {pool.submit(fetch_page, p): p for p in remaining}
                for future in as_completed(futures):
                    p = futures[future]
                    try:
                        paged[p] = future.result()
                    except Exception:
                        paged[p] = {}
            for p in remaining:
                all_videos.extend(_extract_video_list(paged.get(p) or {}))
        return all_videos

    # No pageCount to go on — walk sequentially and stop at the first
    # short page, exactly like the pre-optimization code did.
    if len(first_videos) < 100:
        return all_videos
    page = 2
    while page <= max_pages:
        data = fetch_page(page)
        videos = _extract_video_list(data)
        if not videos:
            break
        all_videos.extend(videos)
        if len(videos) < 100:
            break
        page += 1
    return all_videos


def _wec_has_onboard_replays(path, car_class, max_probe_pages=2):
    """Cheap existence check: does *any* onboard replay exist for this race+class+year?

    Runs the same platform-wide year+class tag query as
    ``_load_wec_onboard_replays``, but stops as soon as one matching video
    turns up (or after ``max_probe_pages``) since this is only used to
    decide whether to show the "Replay - Onboards Hypercar/LMGT3" folder at
    all. Onboard cameras only exist on Staylive from the 2026 season on
    (confirmed by hand — 2024/2025 races have none), so callers should only
    reach for this on the current/future season; see the year gate around
    its call site in ``wec_race()``.
    """
    wanted_class = str(car_class or "").strip().lower()
    wanted_year, useful_tokens = _wec_onboard_match_context(path)

    for page in range(1, int(max_probe_pages) + 1):
        data = _fetch_wec_platform_tag_feed([wanted_year, wanted_class], page=page, limit=100)
        videos = _extract_video_list(data)
        if not videos:
            return False
        for video in videos:
            if not isinstance(video, dict):
                continue
            if _onboard_video_matches(
                video, wanted_class, wanted_year, useful_tokens, require_race_tokens=True
            ):
                return True
        if len(videos) < 100:
            return False
    return False


def _load_wec_onboard_replays(path, car_class):
    """Load and locally filter all onboard replays for one WEC race/class."""
    wanted_class = str(car_class or "").strip().lower()
    wanted_year, useful_tokens = _wec_onboard_match_context(path)

    result, seen = [], set()

    def accept_video(video, require_race_tokens=True):
        return _onboard_prepare_video(
            video, wanted_class, wanted_year, useful_tokens,
            require_race_tokens=require_race_tokens, seen_slugs=seen,
        )

    # Primary method: race-page VIDEO_CHANNEL_TAGS feeds, scoped to this
    # race's own Staylive channel(s) — exactly like normal replays are
    # fetched (see _wec_2026_replay_videos, which passes channelId). This
    # only ever has to page through the handful of onboard videos that
    # belong to *this* race, so it's fast and usually finishes in one page.
    feeds = _wec_onboard_replay_feeds(path)
    feeddefs = []
    seen_feeddefs = set()
    for row in feeds:
        row_tags = [str(x).strip().lower() for x in (row.get("tags") or [])]
        if wanted_class not in row_tags:
            continue
        ids = row.get("channel_ids") or []
        if not isinstance(ids, list):
            ids = [ids]
        ids = tuple(str(x).strip() for x in ids if str(x).strip())
        tags = tuple(str(x).strip().lower() for x in (row.get("tags") or []) if str(x).strip())
        key = (ids, tags)
        if key in seen_feeddefs:
            continue
        seen_feeddefs.add(key)
        feeddefs.append(row)

    for feeddef in feeddefs:
        videos = _fetch_video_pages(
            lambda p, fd=feeddef: _fetch_wec_tag_feed(fd, page=p, limit=100),
            max_pages=20,
        )
        for video in videos:
            item = accept_video(video, require_race_tokens=False)
            if item:
                result.append(item)

    # Fallback: platform-wide year + class tag query, for race pages that
    # don't embed a VIDEO_CHANNEL_TAGS onboard feed at all (or a Staylive
    # setup that requires the un-scoped route). This is the expensive path
    # — it has to walk the *entire season's* tagged videos and filter them
    # locally by race tokens — so it only runs when the cheap, channel-
    # scoped method above found nothing.
    if not result:
        videos = _fetch_video_pages(
            lambda p: _fetch_wec_platform_tag_feed(
                [wanted_year, wanted_class], page=p, limit=100
            ),
            max_pages=30,
        )
        for video in videos:
            item = accept_video(video)
            if item:
                result.append(item)

    return result


def wec_onboard_replays(path, label="Replay - Onboards Hypercar", car_class="hypercar", session=""):
    """Show session folders, or the vehicle videos inside one onboard session."""
    try:
        videos = _load_wec_onboard_replays(path, car_class)
        wanted_class = str(car_class or "").strip().lower()
        session = str(session or "").strip().lower()

        if not videos:
            xbmcgui.Dialog().notification(
                "FIAWEC+",
                "No {} onboard replays found".format(
                    "LMGT3" if wanted_class == "lmgt3" else "Hypercar"
                ),
                xbmcgui.NOTIFICATION_INFO, 3500,
            )
            xbmcplugin.endOfDirectory(HANDLE)
            return

        # First level: only session folders that actually contain videos.
        if not session:
            preferred = [
                ("race", "Race"),
                ("warmup", "Warmup"),
                ("qualifying", "Qualifying"),
                ("hyperpole", "Hyperpole"),
                ("fp1", "Free Practice 1"),
                ("fp2", "Free Practice 2"),
                ("fp3", "Free Practice 3"),
                ("fp4", "Free Practice 4"),
            ]
            counts = {}
            for video in videos:
                key = video.get("_session_key") or "other"
                counts[key] = counts.get(key, 0) + 1

            for key, session_label in preferred:
                count = counts.get(key, 0)
                if not count:
                    continue
                add_item(
                    "{} ({})".format(session_label, count),
                    "wec_onboard_replays",
                    path=path,
                    replay_label=label,
                    car_class=wanted_class,
                    session=key,
                    plot=L("{} – {} Onboard-Replays", "{} – {} Onboard replays").format(
                        "LMGT3" if wanted_class == "lmgt3" else "Hypercar",
                        session_label,
                    ),
                )

            xbmcplugin.setContent(HANDLE, "videos")
            xbmcplugin.endOfDirectory(HANDLE)
            return

        # Second level: vehicle videos for the selected session.
        selected = [v for v in videos if (v.get("_session_key") or "other") == session]
        selected.sort(key=lambda v: str(v.get("_title") or "").lower())

        for video in selected:
            slug = video["_slug"]
            title = video["_title"]
            thumb = video.get("thumbnail") or _extract_art_url(video)

            li = xbmcgui.ListItem(label=title)
            li.setProperty("IsPlayable", "true")
            li.setInfo("video", {
                "title": title,
                "plot": _clean_text(video.get("description")) or title,
                "duration": _duration_seconds(video.get("duration")),
            })
            if thumb:
                li.setArt({
                    "thumb": thumb, "icon": thumb,
                    "poster": thumb, "fanart": thumb,
                })
            xbmcplugin.addDirectoryItem(
                handle=HANDLE,
                url=make_url("play", slug=slug),
                listitem=li,
                isFolder=False,
            )

        xbmcplugin.setContent(HANDLE, "videos")
        xbmcplugin.endOfDirectory(HANDLE)

    except Exception as exc:
        log("WEC onboard replay failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            "FIAWEC+",
            "Onboard replays could not be loaded:\n\n{}".format(str(exc)[:900]),
        )
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def diagnose_onboard_video_fields():
    return _diagnostics.diagnose_onboard_video_fields()

def diagnose_tag_structure():
    return _diagnostics.diagnose_tag_structure()



def cache_clear_action():
    """Clear the local page/thumbnail cache (menu entry: 'Cache leeren')."""
    ok = cache_clear()
    xbmcgui.Dialog().notification(
        "FIAWEC+",
        L("Cache geleert", "Cache cleared") if ok else L("Cache konnte nicht geleert werden", "Cache could not be cleared"),
        xbmcgui.NOTIFICATION_INFO if ok else xbmcgui.NOTIFICATION_WARNING,
        3000,
    )
    xbmc.executebuiltin("Container.Refresh")











def _collect_race_paths(value, found=None):
    return _wec_events._collect_race_paths(value, found)


def _collect_livestream_slugs(value, found=None):
    return _wec_events._collect_livestream_slugs(value, found)


def _wec_event_match_slug(race_path, video_slug):
    return _wec_events._wec_event_match_slug(race_path, video_slug)


def _wec_live_videos(race_path):
    return _wec_events._wec_live_videos(race_path)


def _race_label_from_path(path):
    return _wec_events._race_label_from_path(path)


def _is_wec_onboard_livestream(item):
    return _wec_events._is_wec_onboard_livestream(item)


def wec_onboard_livestreams(path, label='', year='2026'):
    return _wec_events.wec_onboard_livestreams(path, label, year)


def _wec_2026_replay_videos(race_path, channel_ids=None, max_pages=10):
    return _wec_events._wec_2026_replay_videos(race_path, channel_ids, max_pages)


def _add_wec_replay_video(video):
    return _wec_events._add_wec_replay_video(video)



def wec_race(path, label='', year=''):
    return _wec_events.wec_race(path, label, year)




def _collect_page_image_candidates(value, key_hint="", out=None):
    """Collect image URLs from a Staylive page without depending on one schema."""
    if out is None:
        out = []

    if isinstance(value, dict):
        for key, child in value.items():
            key_l = str(key).lower()
            if isinstance(child, str) and _looks_like_image_url(child):
                score = 0
                # Prefer actual page/hero/event artwork over logos/icons.
                if any(x in key_l for x in ("hero", "cover", "background", "banner", "poster", "thumbnail", "image")):
                    score += 40
                if any(x in key_l for x in ("logo", "icon", "avatar")):
                    score -= 30
                child_l = child.lower()
                if any(x in child_l for x in ("hero", "cover", "banner", "event", "race")):
                    score += 15
                if any(x in child_l for x in ("logo", "icon")):
                    score -= 20
                out.append((score, child))
            _collect_page_image_candidates(child, key_l, out)

    elif isinstance(value, list):
        for child in value:
            _collect_page_image_candidates(child, key_hint, out)

    elif isinstance(value, str) and _looks_like_image_url(value):
        out.append((0, value))

    return out


def _best_page_art(page):
    candidates = _collect_page_image_candidates(page)
    if not candidates:
        return ""

    # Remove duplicates while keeping the best score per URL.
    best_by_url = {}
    for score, url in candidates:
        if score > best_by_url.get(url, -9999):
            best_by_url[url] = score

    ranked = sorted(
        ((score, url) for url, score in best_by_url.items()),
        key=lambda item: item[0],
        reverse=True,
    )
    return ranked[0][1] if ranked else ""


def _wec_local_art(path):
    slug = (path or "").strip("/").split("/")[-1]
    filename = slug + ".jpg"
    local_path = os.path.join(ADDON.getAddonInfo("path"), "resources", "wec", filename)
    if xbmcvfs.exists(local_path):
        return {
            "thumb": local_path,
            "icon": local_path,
            "poster": local_path,
            "fanart": ADDON.getAddonInfo("fanart"),
        }
    return _menu_art()


def _wec_race_preview_art(path):
    """Get a dependable WEC race thumbnail from the race's own video feed."""
    try:
        url = "https://api.staylive.tv/platforms/{}/pages/path/{}".format(
            PLATFORM_UID, urllib.parse.quote(path, safe="/")
        )
        response = request_json(
            url, headers=_api_headers(),
            cache_ttl=CACHE_TTL_PAGE, cache_key="page:" + path,
        )
        page = _message(response)
        if not isinstance(page, dict):
            return ""

        # Use the exact feed-preview path that already supplies artwork
        # successfully for ELMS and MLMC.
        for element in page.get("elements") or []:
            if not isinstance(element, dict) or element.get("name") != "ContentFeed":
                continue

            props = element.get("props") or {}
            if not isinstance(props, dict) or props.get("type") != "VIDEO_CHANNELS":
                continue

            channel_id = _channel_value(props.get("id"))
            if not channel_id:
                continue

            date_range = props.get("dateRangeFilter") or {}
            start_date = date_range.get("start") or ""
            end_date = date_range.get("end") or ""

            image_url = _feed_preview_art(start_date, end_date, str(channel_id))
            if image_url:
                log("WEC artwork found for {} via channel {}".format(path, channel_id), xbmc.LOGINFO)
                return image_url

        # Only if no feed preview exists, try artwork embedded in the page.
        image_url = _best_page_art(page)
        if image_url:
            log("WEC artwork found for {} via page metadata".format(path), xbmc.LOGINFO)
            return image_url

        log("No WEC artwork found for {}".format(path), xbmc.LOGWARNING)

    except Exception as exc:
        log("WEC race preview failed for {}: {}".format(path, exc), xbmc.LOGWARNING)

    return ""


def _collect_playlist_videos(value, found=None, seen=None):
    """Recursively collect video objects from Staylive playlist responses."""
    if found is None:
        found = []
    if seen is None:
        seen = set()

    if isinstance(value, dict):
        slug = value.get("seo_string") or value.get("seoString") or ""
        if slug:
            slug = str(slug)
            if slug not in seen:
                seen.add(slug)
                found.append(value)

        for child in value.values():
            _collect_playlist_videos(child, found, seen)

    elif isinstance(value, list):
        for child in value:
            _collect_playlist_videos(child, found, seen)

    return found


def _collect_video_channel_feeds(value, found=None):
    """Recursively discover Staylive VIDEO_CHANNELS ContentFeed definitions."""
    if found is None:
        found = []

    if isinstance(value, dict):
        if value.get("name") == "ContentFeed":
            props = value.get("props") or {}
            if isinstance(props, dict) and props.get("type") == "VIDEO_CHANNELS":
                channel_id = _channel_value(props.get("id"))
                if channel_id:
                    date_range = props.get("dateRangeFilter") or {}
                    item = {
                        "start": date_range.get("start") or "",
                        "end": date_range.get("end") or "",
                        "channel": str(channel_id),
                        "title": _text_value(props.get("title")) or "Videos",
                    }
                    key = (item["channel"], item["start"], item["end"], item["title"])
                    if not any(
                        (x["channel"], x["start"], x["end"], x["title"]) == key
                        for x in found
                    ):
                        found.append(item)

        for child in value.values():
            _collect_video_channel_feeds(child, found)

    elif isinstance(value, list):
        for child in value:
            _collect_video_channel_feeds(child, found)

    return found


def _collect_video_tag_feeds(value, found=None):
    """Recursively discover Staylive VIDEO_CHANNEL_TAGS ContentFeed definitions."""
    if found is None:
        found = []

    if isinstance(value, dict):
        if value.get("name") == "ContentFeed":
            props = value.get("props") or {}
            if isinstance(props, dict) and props.get("type") == "VIDEO_CHANNEL_TAGS":
                tag_ids = props.get("id")
                if not isinstance(tag_ids, list):
                    tag_ids = [tag_ids] if tag_ids not in (None, "") else []
                tag_ids = [str(x).strip() for x in tag_ids if str(x).strip()]
                if tag_ids:
                    date_range = props.get("dateRangeFilter") or {}
                    item = {
                        "start": date_range.get("start") or "",
                        "end": date_range.get("end") or "",
                        "tags": tag_ids,
                        "title": _text_value(props.get("title")) or L("Onboard-Replays", "Onboard replays"),
                        "all_tags_required": bool(
                            props.get("allTagsRequired")
                            or props.get("all_tags_required")
                        ),
                    }
                    key = (
                        tuple(item["tags"]), item["start"], item["end"],
                        item["title"], item["all_tags_required"]
                    )
                    if not any(
                        (
                            tuple(x["tags"]), x["start"], x["end"],
                            x["title"], x["all_tags_required"]
                        ) == key
                        for x in found
                    ):
                        found.append(item)

        for child in value.values():
            _collect_video_tag_feeds(child, found)

    elif isinstance(value, list):
        for child in value:
            _collect_video_tag_feeds(child, found)

    return found


def _extract_video_list(response):
    return _video_menu.extract_video_list(response, _message)


def _videos_by_tag_request(tag_ids, page_num="1", start="", end="", all_tags_required=False):
    return _video_menu.videos_by_tag_request(tag_ids, page_num, _video_menu_context())


def tag_feed(tags, start="", end="", page_num="1", all_tags_required="0", suppress_access="1"):
    return _video_menu.render_tag_feed(
        tags, start, end, page_num, all_tags_required, suppress_access, _video_menu_context()
    )


def _video_date_label(video):
    return _video_menu.video_date_label(video)


def _video_display_title(video, title, include_date=False, forced_access=""):
    return _video_menu.video_display_title(video, title, include_date, forced_access)


def fiawec_originals():
    return _video_menu.render_originals(_video_menu_context())


def playlist(uid, label="Playlist"):
    return _video_menu.render_playlist(uid, label, _video_menu_context())


def _series_weekend_label(series_name, title, season="2026"):
    return _series_data_weekend_label(series_name, title, season)


def _feed_title_year(title):
    return _series_data_feed_title_year(title)


def _wec_race_feeds(path):
    return _wec_events._wec_race_feeds(path)


def _wec_race_tag_feeds(path):
    return _wec_events._wec_race_tag_feeds(path)


def _discover_wec_races(page):
    return _wec_events._discover_wec_races(page)





def _platform_livestreams_all(limit=100, max_pages=10):
    return _wec_events._platform_livestreams_all(limit, max_pages)


def _future_wec_livestreams(year='2026'):
    return _wec_events._future_wec_livestreams(year)


def _series_livestream_match(item, series_key):
    return _series_data_livestream_match(item, series_key)


def _future_series_livestreams(series_key, year="2026"):
    return _series_data_future_livestreams(
        _platform_livestreams_all(), series_key, year
    )


def series_next_livestreams(series_key, year="2026"):
    """Show upcoming and currently running ELMS/MLMC livestreams."""
    wanted = str(year or "2026").strip()
    key = (series_key or "").strip().lower()
    streams = _future_series_livestreams(key, wanted)
    series_label = {
        "elms": "European Le Mans Series",
        "mlmc": "Michelin Le Mans Cup",
    }.get(key, "FIAWEC+")

    if not streams:
        add_item(
            L("Derzeit keine laufenden oder zukünftigen Livestreams angekündigt", "No live or upcoming livestreams announced right now"),
            "noop",
            art=_official_series_art(key),
            plot=L("Staylive hat derzeit keine laufenden oder zukünftigen Livestreams für {} {} veröffentlicht.", "Staylive hasn't published any live or upcoming livestreams for {} {} right now.").format(series_label, wanted),
        )
    else:
        now_utc = datetime.now(timezone.utc)
        for live in streams:
            when = _berlin_datetime_label(live.get("start"))
            title = live.get("title") or live.get("slug")
            start_dt = live.get("start_dt")
            end_dt = live.get("end_dt")
            is_live = bool(start_dt and start_dt <= now_utc and (not end_dt or end_dt > now_utc))
            live_prefix = "[COLOR red]LIVE[/COLOR] " if is_live else ""
            base_display = "{} – {}".format(when, title) if when else title
            add_item(
                live_prefix + base_display,
                "play_livestream",
                playable=True,
                slug=live.get("slug"),
                art=_official_series_art(key),
                plot="{} – {}".format(series_label, title),
            )

    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.setContent(HANDLE, "videos")
    xbmcplugin.endOfDirectory(HANDLE)


def wec_next_livestreams(year='2026'):
    return _wec_events.wec_next_livestreams(year)


def wec_year(year):
    return _wec_events.wec_year(year)


def wec_icons():
    return _wec_events.wec_icons()


def wec_series():
    return _wec_events.wec_series()




def root():
    return _ui.root()


def _url_from_art_value(value):
    return _ui.url_from_art_value(value)


def _extract_art_url(*objects):
    return _ui.extract_art_url(*objects)


def _official_series_art(key):
    return _ui.official_series_art(key)


def _resource_art(filename):
    return _ui.resource_art(filename)


def _menu_art(image_url=""):
    return _ui.menu_art(image_url)


def _folder_art(image_url=""):
    return _ui.folder_art(image_url)


def _friendly_feed_title(props, start, end, channel_id):
    return _ui.friendly_feed_title(props, start, end, channel_id)


def _iso_to_datetime(value):
    return _ui.iso_to_datetime(value)


def _is_future_feed(start):
    return _ui.is_future_feed(start)


def _feed_preview_art(start, end, channel_id):
    return _ui.feed_preview_art(start, end, channel_id)


def request_json(url, method="GET", data=None, headers=None, cache_ttl=0, cache_key=None):
    return _api_request_json(
        url,
        method=method,
        data=data,
        headers=headers,
        cache_ttl=cache_ttl,
        cache_key=cache_key,
        cache_get=cache_get,
        cache_set=cache_set,
    )


def get_access_token(force=False):
    """Compatibility wrapper for older internal call sites."""
    if force:
        if not _refresh_access_token_silent():
            raise RuntimeError("Token refresh failed. Please sign in again.")
    token = _ensure_access_token()
    if not token:
        raise RuntimeError("Not signed in. Please sign in through the FIAWEC+ add-on.")
    return token






def get_video(slug):
    return _api_get_video(slug, get_access_token(), request_json)


def get_livestream(slug):
    try:
        return _api_get_livestream(slug, get_access_token(), request_json)
    except RuntimeError as exc:
        if str(exc) == "Invalid livestream response":
            raise RuntimeError(L("Ungültige Livestream-Antwort", "Invalid livestream response"))
        raise


def play_livestream(slug):
    return _playback.play_livestream(
        slug,
        handle=HANDLE,
        get_livestream=get_livestream,
        log=log,
        translate=L,
    )


def play(slug):
    return _playback.play_video(
        slug,
        handle=HANDLE,
        get_video=get_video,
        log=log,
        translate=L,
    )

def _api_headers(referer=None):
    return _build_api_headers(get_access_token(), referer=referer)


def _feed_headers(channel_id):
    return _build_feed_headers(channel_id)
























def _pretty_event_name(title):
    return _series_menu.pretty_event_name(title, L)


def _event_key(title):
    return _series_menu.event_key(title)


def _is_onboard_title(title):
    return _series_menu.is_onboard_title(title)


def _series_menu_context():
    return {
        "L": L,
        "handle": HANDLE,
        "add_item": add_item,
        "folder_art": _folder_art,
        "official_series_art": _official_series_art,
        "feed_preview_art": _feed_preview_art,
        "series_weekend_label": _series_weekend_label,
        "request_json": request_json,
        "api_headers": _api_headers,
        "message": _message,
        "collect_video_channel_feeds": _collect_video_channel_feeds,
        "is_future_feed": _is_future_feed,
        "platform_uid": PLATFORM_UID,
        "cache_ttl_page": CACHE_TTL_PAGE,
        "log": log,
    }


def _video_menu_context():
    return {
        "L": L,
        "handle": HANDLE,
        "request_json": request_json,
        "api_headers": _api_headers,
        "feed_headers": _feed_headers,
        "message": _message,
        "clean_text": _clean_text,
        "duration_seconds": _duration_seconds,
        "extract_art_url": _extract_art_url,
        "folder_art": _folder_art,
        "menu_art": _menu_art,
        "add_item": add_item,
        "make_url": make_url,
        "collect_playlist_videos": _collect_playlist_videos,
        "platform_uid": PLATFORM_UID,
        "log": log,
    }


def event_group(event, main_start="", main_end="", main_channel="",
                onboard_start="", onboard_end="", onboard_channel=""):
    return _series_menu.render_event_group(
        event, main_start, main_end, main_channel,
        onboard_start, onboard_end, onboard_channel, _series_menu_context()
    )


def _series_display_name(slug):
    return _series_menu.series_display_name(slug)


def _michelin_event_name(title):
    return _series_menu.michelin_event_name(title, L)


def elms_series():
    return _series_menu.render_season_menu(
        "elms", ELMS_SEASON_PAGES, _series_menu_context()
    )


def mlmc_series():
    return _series_menu.render_season_menu(
        "mlmc", MLMC_SEASON_PAGES, _series_menu_context()
    )


def series(slug):
    return _series_menu.render_series(slug, _series_menu_context())


def _short_video_title(name):
    return _video_menu.short_video_title(name)


def feed(start, end, channel_id, page_num="1", forced_access="", suppress_access="0"):
    return _video_menu.render_feed(
        start, end, channel_id, page_num, forced_access, suppress_access, _video_menu_context()
    )


def test_barcelona_feed_action():
    # Exact URL observed in Firefox for the successful Barcelona feed.
    url = (
        "https://api.staylive.tv/videos/feed"
        "?limit=20&page=1&categories=false"
        "&date_range_start=2026-04-09T22:00:00.000Z"
        "&date_range_end=2026-04-14T22:00:00.000Z"
    )
    try:
        response = request_json(
            url,
            headers=_feed_headers("6999"),
        )
        videos = _message(response)
        count = len(videos) if isinstance(videos, list) else -1
        xbmcgui.Dialog().ok(
            "FIAWEC+ Diagnostics",
            "Barcelona-Feed erfolgreich mit X-STAYLIVE-CHANNELS: 6999.\\n\\n"
            "Videos: {}\\n\\n"
            "URL:\\n{}".format(count, url)
        )
    except Exception as exc:
        xbmcgui.Dialog().ok(
            "FIAWEC+ Diagnostics",
            "Barcelona feed failed.\\n\\n"
            "{}\\n\\nURL:\\n{}".format(exc, url)
        )


def input_slug():
    value = xbmcgui.Dialog().input(
        "FIAWEC+ URL or video slug",
        type=xbmcgui.INPUT_ALPHANUM,
    )
    slug = normalize_slug(value)
    if slug:
        xbmc.executebuiltin("PlayMedia({})".format(make_url("play", slug=slug)))


def refresh_token_action():
    try:
        get_access_token(force=True)
        xbmcgui.Dialog().notification(
            "FIAWEC+",
            "Access token refreshed successfully",
            xbmcgui.NOTIFICATION_INFO,
            4000,
        )
    except Exception as exc:
        log("Token refresh failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok("FIAWEC+", "Token refresh failed:\n\n{}".format(exc))


def test_manual_token_action():
    token = setting("manual_access_token").strip()
    if not token:
        xbmcgui.Dialog().ok(
            "FIAWEC+",
            "Kein Browser-Access-Token eingetragen.\\n\\n"
            "Open Settings and enter the current access_token from "
            "the successful /oauth/token response."
        )
        return

    try:
        video = get_video(TEST_SLUG)
        title = video.get("name") or "Video"
        playback_url = _find_playback_url(video)
        if playback_url:
            host = urllib.parse.urlparse(playback_url).netloc
            xbmcgui.Dialog().ok(
                "FIAWEC+",
                "Access-Token akzeptiert.\\n\\n"
                "Video: {}\\nPlayback-URL: Ja\\nHost: {}".format(title, host)
            )
        else:
            keys = ", ".join(sorted(str(k) for k in video.keys()))
            xbmcgui.Dialog().ok(
                "FIAWEC+",
                "Access-Token akzeptiert, aber keine Playback-URL received.\\n\\n"
                "Video: {}\\nFelder: {}".format(title, keys[:900])
            )
    except Exception as exc:
        log("Manual access-token test failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            "FIAWEC+",
            "Access token test failed:\\n\\n{}".format(exc)
        )


_ui.configure(
    ADDON=ADDON,
    HANDLE=HANDLE,
    BASE_URL=BASE_URL,
    L=L,
    request_json=request_json,
    feed_headers=_feed_headers,
    message=_message,
    text_value=_text_value,
    CACHE_TTL_PREVIEW_ART=CACHE_TTL_PREVIEW_ART,
    log=log,
)


def _configure_diagnostics():
    _diagnostics.configure(
        PLATFORM_UID=PLATFORM_UID,
        request_json=request_json,
        _api_headers=_api_headers,
        _feed_headers=_feed_headers,
        _message=_message,
        _text_value=_text_value,
        _collect_video_channel_feeds=_collect_video_channel_feeds,
        _discover_wec_races=_discover_wec_races,
        _extract_video_list=_extract_video_list,
        log=log,
    )


_configure_diagnostics()



# Configure the extracted WEC event/archive module after all local helpers exist.
_wec_events.configure(
    ADDON=ADDON, HANDLE=HANDLE, L=L, request_json=request_json,
    _api_headers=_api_headers, add_item=add_item, make_url=make_url, log=log,
    _folder_art=_folder_art, _menu_art=_menu_art, _wec_local_art=_wec_local_art,
    _feed_preview_art=_feed_preview_art, _pretty_event_name=_pretty_event_name,
    _collect_video_channel_feeds=_collect_video_channel_feeds,
    _collect_video_tag_feeds=_collect_video_tag_feeds,
    _extract_video_list=_extract_video_list, _feed_title_year=_feed_title_year,
    feed=feed, _wec_has_onboard_replays=_wec_has_onboard_replays,
    _wec_onboard_replay_feeds=_wec_onboard_replay_feeds,
)

def router():
    handler_names = (
        "root", "event_group", "series", "elms_series", "mlmc_series",
        "wec_series", "wec_icons", "wec_year", "wec_next_livestreams",
        "series_next_livestreams", "wec_onboard_livestreams", "wec_race",
        "fiawec_originals", "playlist", "tag_feed", "feed",
        "wec_onboard_replays", "play_livestream", "play", "input_slug",
        "oauth_import_token_file", "oauth_browser_refresh_import",
        "oauth_direct_login", "oauth_cookie_login_file",
        "oauth_cookie_select_shared", "oauth_cookie_login_shared",
        "oauth_cookie_login_manual", "oauth_refresh_test", "account_menu",
        "diagnose_next_sessions", "diagnose_extra_content",
        "diagnose_onboard_video_fields", "diagnose_tag_structure",
        "oauth_status", "oauth_logout", "oauth_refresh", "cache_clear_action",
    )
    handlers = {name: globals()[name] for name in handler_names}
    # Route names are kept stable even where the implementation function has
    # historically used an ``_action`` suffix.
    handlers.update({
        "test_barcelona_feed": test_barcelona_feed_action,
        "test_manual_token": test_manual_token_action,
        "refresh_token": refresh_token_action,
    })
    return _route_dispatch(sys.argv, handlers, ADDON, xbmcplugin, HANDLE)


if __name__ == "__main__":
    router()
