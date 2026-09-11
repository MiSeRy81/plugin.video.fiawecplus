# -*- coding: utf-8 -*-
from __future__ import annotations

"""WEC race/event discovery, archive menus and livestream grouping.

This module intentionally keeps Kodi-facing behaviour identical to the historical
main.py implementation. Dependencies that belong to the main controller are
injected once through configure() to avoid circular imports.
"""

import os
import re
import urllib.parse
from datetime import datetime, timezone

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.config import PLATFORM_UID
from resources.lib.cache import CACHE_TTL_PAGE, CACHE_TTL_TAG_FEED
from resources.lib.utils import (
    _message, _parse_staylive_datetime, _berlin_datetime_label, normalize_slug,
    _clean_text, _duration_seconds,
)
from resources.lib.series_data import (
    discover_wec_races as _series_data_discover_wec_races,
    future_wec_livestreams as _series_data_future_wec_livestreams,
)

# Injected controller helpers. They are assigned by configure() from main.py.
ADDON = None
HANDLE = -1
L = None
request_json = None
_api_headers = None
add_item = None
make_url = None
log = None
_folder_art = None
_menu_art = None
_wec_local_art = None
_feed_preview_art = None
_pretty_event_name = None
_collect_video_channel_feeds = None
_collect_video_tag_feeds = None
_extract_video_list = None
_feed_title_year = None
feed = None
_wec_has_onboard_replays = None
_wec_onboard_replay_feeds = None

def configure(**deps):
    """Inject main-controller callbacks without importing main.py."""
    globals().update(deps)

def _collect_race_paths(value, found=None):
    if found is None:
        found = []

    if isinstance(value, dict):
        for v in value.values():
            _collect_race_paths(v, found)
    elif isinstance(value, list):
        for v in value:
            _collect_race_paths(v, found)
    elif isinstance(value, str):
        text = value.strip()
        candidates = [text]
        try:
            parsed = urllib.parse.urlparse(text)
            if parsed.path:
                candidates.append(parsed.path)
        except Exception:
            pass

        for candidate in candidates:
            candidate = candidate.split("?", 1)[0].split("#", 1)[0]
            candidate = candidate.strip("/")
            if candidate.startswith("en/"):
                candidate = candidate[3:]
            if candidate.startswith("race/"):
                if candidate not in found:
                    found.append(candidate)

    return found


def _collect_livestream_slugs(value, found=None):
    """Recursively collect Staylive /livestream/<video-slug> links."""
    if found is None:
        found = []

    if isinstance(value, dict):
        for child in value.values():
            _collect_livestream_slugs(child, found)
    elif isinstance(value, list):
        for child in value:
            _collect_livestream_slugs(child, found)
    elif isinstance(value, str):
        text = value.strip()
        candidates = [text]
        try:
            parsed = urllib.parse.urlparse(text)
            if parsed.path:
                candidates.append(parsed.path)
        except Exception:
            pass

        for candidate in candidates:
            candidate = candidate.split("?", 1)[0].split("#", 1)[0].strip("/")
            if candidate.startswith("en/"):
                candidate = candidate[3:]
            if candidate.startswith("livestream/"):
                slug = candidate.split("/", 1)[1].strip("/")
                if slug and slug not in found:
                    found.append(slug)
    return found


def _wec_event_match_slug(race_path, video_slug):
    """Match a discovered livestream slug to the currently opened WEC event."""
    event = (race_path or "").strip("/").split("/")[-1].lower()
    slug = (video_slug or "").lower()
    if event and event in slug:
        return True

    # Commercial prefixes are not always used in Staylive livestream slugs.
    simplified = event
    for word in ("totalenergies-", "rolex-"):
        simplified = simplified.replace(word, "")
    return bool(simplified and simplified in slug)


def _wec_live_videos(race_path):
    """Return only finished WEC session streams for one race folder."""
    clean = (race_path or "").strip("/")
    if clean.startswith("en/"):
        clean = clean[3:]

    now_utc = datetime.now(timezone.utc)
    videos = []
    seen = set()

    # Use the fully paginated platform catalogue so older finished sessions
    # such as Free Practice / Qualifying are not lost after page 1.
    for item in _platform_livestreams_all(limit=100, max_pages=10):
        if not isinstance(item, dict):
            continue

        slug = normalize_slug(item.get("seo_string") or item.get("slug") or "")
        if not slug or slug in seen:
            continue
        if not _wec_event_match_slug(clean, slug):
            continue

        start = item.get("start") or item.get("start_at") or item.get("startAt") or ""
        end = item.get("end") or item.get("end_at") or item.get("endAt") or ""
        start_dt = _parse_staylive_datetime(start)
        end_dt = _parse_staylive_datetime(end)

        # Current 2026 race folders must not absorb archived sessions from
        # another season.
        if start_dt and start_dt.strftime("%Y") != "2026":
            continue

        # Race folders are an archive view: only sessions whose advertised
        # Staylive end time has passed belong here. Upcoming/running streams
        # remain exclusively under "Live".
        if not end_dt or end_dt > now_utc:
            continue

        title = item.get("name") or item.get("title") or _pretty_event_name(slug)
        videos.append({
            "slug": slug,
            "title": title,
            "art": {},
            "start": start,
            "end": end,
            "status": item.get("status") or item.get("state") or "",
        })
        seen.add(slug)

    videos.sort(key=lambda x: (
        _parse_staylive_datetime(x.get("start")) or datetime.min.replace(tzinfo=timezone.utc),
        str(x.get("title") or "").lower(),
    ))
    return videos


def _race_label_from_path(path):
    slug = (path or "").strip("/").split("/")[-1]
    words = slug.replace("-", " ").split()
    small = {"of", "the", "and"}
    pretty = []
    for pos, word in enumerate(words):
        if word.lower() in small and pos:
            pretty.append(word.lower())
        else:
            pretty.append(word[:1].upper() + word[1:].lower())

    label = " ".join(pretty)
    label = label.replace("Spa Francorchamps", "Spa-Francorchamps")
    label = label.replace("Spa-francorchamps", "Spa-Francorchamps")
    label = label.replace("Totalenergies", "TotalEnergies")
    label = label.replace("Wec Icons", "WEC Icons")
    label = label.replace("Sao Paulo", "São Paulo")
    return label or slug


def _is_wec_onboard_livestream(item):
    title = str((item or {}).get("title") or "").strip()
    low = title.lower()
    if "onboard" in low:
        return True
    # Staylive vehicle streams currently look like:
    # "N°007 ASTON MARTIN THOR TEAM | Lone Star Le Mans 2026 | Free Practice 3"
    if "|" in title and any(token in low for token in (
        "free practice", "qualifying", "hyperpole", "race"
    )):
        return True
    return False


def wec_onboard_livestreams(path, label="", year="2026"):
    clean_path = (path or "").strip("/")
    if clean_path.startswith("en/"):
        clean_path = clean_path[3:]
    if not clean_path.startswith("race/"):
        clean_path = "race/" + clean_path

    race_name = label or _race_label_from_path(clean_path)
    streams = [
        x for x in _wec_live_videos(clean_path)
        if _is_wec_onboard_livestream(x)
    ]

    for live in streams:
        art = live.get("art") or _wec_local_art(clean_path)
        add_item(
            live.get("title") or "Onboard livestream",
            "play_livestream",
            slug=live.get("slug") or "",
            art=art,
            plot=L("{} {} – Onboard livestream", "{} {} – Onboard livestream").format(
                race_name, str(year or "").strip()
            ).strip(),
            playable=True,
        )

    if not streams:
        xbmcgui.Dialog().notification(
            "FIAWEC+",
            "No onboard livestreams found",
            xbmcgui.NOTIFICATION_INFO,
            3500,
        )

    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.setContent(HANDLE, "videos")
    xbmcplugin.endOfDirectory(HANDLE)


def _wec_2026_replay_videos(race_path, channel_ids=None, max_pages=10):
    """Load this race's 2026 replays via Staylive's platform-scoped tag route.

    A bare ``/tags/videos/feed?tags=2026`` request (no platform prefix, no
    ``channelId``) is rejected server-side with ``HTTP 500`` — see
    ``diagnose_tag_route()`` / ``_fetch_wec_tag_feed()``, which proved that
    Staylive only accepts the platform-scoped
    ``/platforms/{PLATFORM_UID}/videos-by-tag`` route and requires an
    explicit ``channelId``. We therefore query that proven route once per
    channel, exactly like the onboard replay feeds already do.

    ``channel_ids`` lets the caller (``wec_race``) hand over the channel
    id(s) it already fetched from the race page, so this function does not
    have to reload and re-parse that page a second time. If omitted, the
    page is resolved here as a fallback for other callers.

    Two lightweight optimizations on top of the original 500-fixing version:
    - no duplicate page fetch (see ``channel_ids`` above);
    - each ``videos-by-tag`` page is cached for ``CACHE_TTL_TAG_FEED``
      seconds, so navigating in and out of the same race folder within that
      window is served from cache instead of hitting the API again.
    """
    clean = (race_path or "").strip("/")
    if clean.startswith("en/"):
        clean = clean[3:]
    if not clean.startswith("race/"):
        clean = "race/" + clean

    if channel_ids is None:
        channel_ids = []
        seen_channels = set()
        for f in _wec_race_feeds(clean):
            cid = str(f.get("channel") or "").strip()
            if cid and cid not in seen_channels:
                seen_channels.add(cid)
                channel_ids.append(cid)

    if not channel_ids:
        return []

    results = []
    seen = set()

    for channel_id in channel_ids:
        for page_num in range(1, int(max_pages) + 1):
            params = [
                ("limit", "20"),
                ("page", str(page_num)),
                ("tags", "2026"),
                ("channelId", channel_id),
            ]
            url = "https://api.staylive.tv/platforms/{}/videos-by-tag?{}".format(
                PLATFORM_UID, urllib.parse.urlencode(params)
            )
            try:
                response = request_json(
                    url, headers=_api_headers(),
                    cache_ttl=CACHE_TTL_TAG_FEED,
                    cache_key="tag2026:{}:{}".format(channel_id, page_num),
                )
            except Exception as exc:
                # A 404 here just means "accepted, no videos on this
                # channel/page" — not a failure, so move on quietly.
                if "404" in str(exc):
                    break
                raise

            videos = _extract_video_list(response)
            if not videos:
                break

            for video in videos:
                if not isinstance(video, dict):
                    continue

                slug = normalize_slug(video.get("seo_string") or video.get("slug") or "")
                if not slug or slug in seen:
                    continue
                if not _wec_event_match_slug(clean, slug):
                    continue

                # Vehicle onboards stay in the dedicated Hypercar/LMGT3 folders.
                channel_path = str(video.get("channelPath") or video.get("channel_path") or "").lower()
                channel_name = str(video.get("channelName") or video.get("channel_name") or "").lower()
                tags = [str(x).lower() for x in (video.get("tags") or [])]
                if "onboard" in channel_path or "onboard" in channel_name:
                    continue
                if "hypercar" in tags or "lmgt3" in tags:
                    continue

                results.append(video)
                seen.add(slug)

            if len(videos) < 20:
                break

    # Keep the website-like order: newest/current session groups first.
    results.sort(
        key=lambda v: str(v.get("created_at") or v.get("published_at") or ""),
        reverse=True,
    )
    return results


def _add_wec_replay_video(video):
    title = video.get("name") or video.get("title") or "Replay"
    slug = normalize_slug(video.get("seo_string") or video.get("slug") or "")
    if not slug:
        return

    li = xbmcgui.ListItem(label=title)
    li.setProperty("IsPlayable", "true")
    li.setInfo(
        "video",
        {
            "title": title,
            "plot": _clean_text(video.get("description")) or title,
            "duration": _duration_seconds(video.get("duration")),
        },
    )
    thumb = video.get("thumbnail")
    if thumb:
        li.setArt({"thumb": thumb, "icon": thumb, "poster": thumb, "fanart": thumb})

    xbmcplugin.addDirectoryItem(
        handle=HANDLE,
        url=make_url("play", slug=slug),
        listitem=li,
        isFolder=False,
    )


def wec_race(path, label="", year=""):
    """Open one WEC race page, optionally restricted to one season."""
    try:
        clean_path = (path or "").strip("/")
        if clean_path.startswith("en/"):
            clean_path = clean_path[3:]
        if not clean_path.startswith("race/"):
            clean_path = "race/" + clean_path

        feeds = _wec_race_feeds(clean_path)
        tag_feeds = _wec_race_tag_feeds(clean_path)

        # Grab this race's VIDEO_CHANNEL id(s) now, while the raw (unfiltered)
        # feed list is still around, so the 2026 tag lookup below can reuse
        # them instead of re-fetching and re-parsing this same page.
        race_channel_ids = []
        _seen_race_channels = set()
        for _f in feeds:
            _cid = str(_f.get("channel") or "").strip()
            if _cid and _cid not in _seen_race_channels:
                _seen_race_channels.add(_cid)
                race_channel_ids.append(_cid)

        wanted_year = str(year or "").strip()
        if wanted_year == "2026":
            # WEC race pages are season-spanning containers. Besides explicit
            # archive folders ("Replay 2025", ...) they may contain a generic
            # "More Content" feed with videos from older seasons. For the 2026
            # season we therefore accept only feeds that are actually assigned
            # to 2026, and never the cross-season "More Content" bucket.
            filtered = []
            for f in feeds:
                title_norm = (_pretty_event_name(f.get("title") or "") or "").strip().lower()
                if title_norm == "more content":
                    continue

                title_year = f.get("title_year") or ""
                feed_year = f.get("year") or ""

                if title_year:
                    if title_year == wanted_year:
                        filtered.append(f)
                elif feed_year == wanted_year:
                    filtered.append(f)
                elif "replay 2026" in title_norm:
                    # Current FIAWEC+ race pages use this generic replay
                    # bucket for converted FP/Qualifying/Race streams.
                    filtered.append(f)

            if not filtered:
                for f in feeds:
                    title_norm = (_pretty_event_name(f.get("title") or "") or "").strip().lower()
                    if title_norm.startswith("replay") and "more content" not in title_norm:
                        filtered.append(f)
            feeds = filtered
        elif wanted_year:
            # For historical seasons, an explicit year in the feed title wins.
            feeds = [
                f for f in feeds
                if (
                    f.get("title_year") == wanted_year
                    or (not f.get("title_year") and f.get("year") == wanted_year)
                )
            ]

        if wanted_year:
            tag_feeds = [
                f for f in tag_feeds
                if (
                    f.get("title_year") == wanted_year
                    or (not f.get("title_year") and f.get("year") == wanted_year)
                )
            ]

        race_name = label or _race_label_from_path(clean_path)

        # Since September 2026 Staylive builds the current race archive from
        # the platform-scoped /platforms/{PLATFORM_UID}/videos-by-tag route
        # (tags=2026, one call per this race's own channel id — see
        # _wec_2026_replay_videos). Use that source for the 2026 archive
        # instead of old VIDEO_CHANNELS buckets (Replay 2025/2024).
        replay_2026_videos = (
            _wec_2026_replay_videos(clean_path, channel_ids=race_channel_ids)
            if wanted_year == "2026" else []
        )

        if wanted_year == "2026":
            for video in replay_2026_videos:
                _add_wec_replay_video(video)
            # Never expose season-spanning legacy Replay 2025/2024 folders in
            # the 2026 race archive.
            feeds = []
            live_videos = []
            onboard_live_videos = []
        else:
            live_videos = []
            onboard_live_videos = []

            # Historical WEC seasons keep the established VIDEO_CHANNELS flow.
            if len(feeds) == 1 and not tag_feeds:
                item = feeds[0]
                return feed(item["start"], item["end"], item["channel"], "1", suppress_access="1")

            for item in feeds:
                image_url = _feed_preview_art(item["start"], item["end"], item["channel"])
                add_item(
                    _pretty_event_name(item["title"]),
                    "feed",
                    start=item["start"],
                    end=item["end"],
                    channel=item["channel"],
                    page="1",
                    suppress_access="1",
                    art=_folder_art(image_url),
                    plot="{}{} – {}".format(
                        race_name,
                        " {}".format(wanted_year) if wanted_year else "",
                        item["title"]
                    ),
                )


        # Onboard replays: keep Hypercar and LMGT3 as separate folders.
        replay_defs = _wec_onboard_replay_feeds(clean_path)
        replay_classes = set()
        for replay_def in replay_defs:
            replay_tags = [str(x).lower() for x in (replay_def.get("tags") or [])]
            if "hypercar" in replay_tags:
                replay_classes.add("hypercar")
            if "lmgt3" in replay_tags:
                replay_classes.add("lmgt3")

        # Onboard cameras only exist on Staylive from the 2026 season on —
        # 2024/2025 races have none at all, confirmed by hand. 2026 race
        # pages generally embed VIDEO_CHANNEL_TAGS blocks (replay_defs
        # above already finds those), but just in case a future page
        # doesn't, keep a cheap platform-wide existence probe as a
        # fallback for the current/future seasons only — running it for
        # 2024/2025 too would just burn API calls on something that
        # never exists there.
        if not wanted_year or wanted_year >= "2026":
            for cls in ("hypercar", "lmgt3"):
                if cls not in replay_classes and _wec_has_onboard_replays(clean_path, cls):
                    replay_classes.add(cls)

        if "hypercar" in replay_classes:
            add_item(
                "Replay - Onboards Hypercar",
                "wec_onboard_replays",
                path=clean_path,
                replay_label="Replay - Onboards Hypercar",
                car_class="hypercar",
                art=_wec_local_art(clean_path),
                plot="{} {} – Replay - Onboards Hypercar".format(
                    race_name, wanted_year if wanted_year else ""
                ).strip(),
            )
        if "lmgt3" in replay_classes:
            add_item(
                "Replay - Onboards LMGT3",
                "wec_onboard_replays",
                path=clean_path,
                replay_label="Replay - Onboards LMGT3",
                car_class="lmgt3",
                art=_wec_local_art(clean_path),
                plot="{} {} – Replay - Onboards LMGT3".format(
                    race_name, wanted_year if wanted_year else ""
                ).strip(),
            )

        # Vehicle-specific streams are deliberately tucked away in one folder.
        if onboard_live_videos:
            pass  # Onboard livestreams intentionally hidden since 1.5.18

        if not feeds and not tag_feeds and not live_videos:
            suffix = " ({})".format(wanted_year) if wanted_year else ""
            xbmcgui.Dialog().notification(
                "FIAWEC+",
                "No video feeds found for {}{}".format(race_name, suffix),
                xbmcgui.NOTIFICATION_WARNING,
                5000,
            )

        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
        xbmcplugin.setContent(HANDLE, "videos")
        xbmcplugin.endOfDirectory(HANDLE)

    except Exception as exc:
        log("WEC race failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            "FIAWEC+",
            L("WEC-Rennseite fehlgeschlagen:\n\n{}", "WEC race page failed:\n\n{}").format(exc)
        )
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def _wec_race_feeds(path):
    """Return the VIDEO_CHANNEL feeds of one WEC race page."""
    clean_path = (path or "").strip("/")
    if clean_path.startswith("en/"):
        clean_path = clean_path[3:]
    if not clean_path.startswith("race/"):
        clean_path = "race/" + clean_path

    url = "https://api.staylive.tv/platforms/{}/pages/path/{}".format(
        PLATFORM_UID, urllib.parse.quote(clean_path, safe="")
    )
    response = request_json(
        url, headers=_api_headers(),
        cache_ttl=CACHE_TTL_PAGE, cache_key="page:" + clean_path,
    )
    page = _message(response)
    if not isinstance(page, dict):
        return []

    feeds = []
    for discovered in _collect_video_channel_feeds(page):
        channel_id = discovered.get("channel") or ""
        start_date = discovered.get("start") or ""
        end_date = discovered.get("end") or ""
        title = discovered.get("title") or "Videos"

        # For FIAWEC+ race pages the date range identifies the season.
        year = ""
        if len(end_date) >= 4 and end_date[:4].isdigit():
            year = end_date[:4]
        elif len(start_date) >= 4 and start_date[:4].isdigit():
            year = start_date[:4]

        title_year = _feed_title_year(title)
        feeds.append({
            "start": start_date,
            "end": end_date,
            "channel": str(channel_id),
            "title": title,
            "year": year,
            "title_year": title_year,
        })

    return feeds


def _wec_race_tag_feeds(path):
    """Return VIDEO_CHANNEL_TAGS feeds (e.g. WEC onboard replays) for one race."""
    clean_path = (path or "").strip("/")
    if clean_path.startswith("en/"):
        clean_path = clean_path[3:]
    if not clean_path.startswith("race/"):
        clean_path = "race/" + clean_path

    url = "https://api.staylive.tv/platforms/{}/pages/path/{}".format(
        PLATFORM_UID, urllib.parse.quote(clean_path, safe="")
    )
    page = _message(request_json(
        url, headers=_api_headers(),
        cache_ttl=CACHE_TTL_PAGE, cache_key="page:" + clean_path,
    ))
    if not isinstance(page, dict):
        return []

    feeds = []
    for item in _collect_video_tag_feeds(page):
        title = item.get("title") or ""
        # On WEC race pages, only surface tag feeds explicitly marked as
        # onboard/replay content; ignore unrelated tagged "More Content".
        low = title.lower()
        if "onboard" not in low:
            continue

        start_date = item.get("start") or ""
        end_date = item.get("end") or ""
        year = ""
        if len(end_date) >= 4 and end_date[:4].isdigit():
            year = end_date[:4]
        elif len(start_date) >= 4 and start_date[:4].isdigit():
            year = start_date[:4]

        item = dict(item)
        item["year"] = year
        item["title_year"] = _feed_title_year(title)
        feeds.append(item)

    return feeds


def _discover_wec_races(page):
    return _series_data_discover_wec_races(page, _collect_race_paths)


def _platform_livestreams_all(limit=100, max_pages=10):
    """Load the platform livestream catalogue, including future scheduled streams."""
    result = []
    seen = set()
    for page in range(1, max_pages + 1):
        url = (
            "https://api.staylive.tv/platforms/{}/livestreams"
            "?limit={}&page={}"
        ).format(PLATFORM_UID, int(limit), page)
        try:
            payload = _message(request_json(url, headers=_api_headers()))
        except Exception as exc:
            log("Livestream page {} failed: {}".format(page, exc), xbmc.LOGINFO)
            break

        rows = []
        if isinstance(payload, dict):
            if isinstance(payload.get("livestreams"), list):
                rows = payload.get("livestreams")
            elif isinstance(payload.get("data"), dict):
                data = payload.get("data")
                rows = data.get("livestreams") or data.get("items") or data.get("results") or []
            elif isinstance(payload.get("data"), list):
                rows = payload.get("data")
        elif isinstance(payload, list):
            rows = payload

        if not rows:
            break

        for item in rows:
            if not isinstance(item, dict):
                continue
            slug = normalize_slug(item.get("seo_string") or item.get("slug") or "")
            key = slug or str(item.get("id") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(item)

        if len(rows) < limit:
            break
    return result


def _future_wec_livestreams(year="2026"):
    return _series_data_future_wec_livestreams(
        _platform_livestreams_all(), year, _wec_event_match_slug, _is_wec_onboard_livestream
    )


def wec_next_livestreams(year="2026"):
    """Show upcoming and currently running WEC livestreams for the selected season."""
    wanted = str(year or "2026").strip()
    streams = _future_wec_livestreams(wanted)

    if not streams:
        add_item(
            L("Derzeit keine laufenden oder zukünftigen Livestreams angekündigt", "No live or upcoming livestreams announced right now"),
            "noop",
            art=_folder_art(),
            plot=L("Staylive hat derzeit keine laufenden oder zukünftigen WEC-Livestreams für {} veröffentlicht.", "Staylive hasn't published any live or upcoming WEC livestreams for {} right now.").format(wanted),
        )
    else:
        for live in streams:
            when = _berlin_datetime_label(live.get("start"))
            title = live.get("title") or live.get("slug")

            start_dt = live.get("start_dt")
            end_dt = _parse_staylive_datetime(live.get("end"))
            now_utc = datetime.now(timezone.utc)
            is_live = bool(
                start_dt and start_dt <= now_utc and
                (not end_dt or end_dt > now_utc)
            )
            live_prefix = "[COLOR red]LIVE[/COLOR] " if is_live else ""
            base_display = "{} – {}".format(when, title) if when else title
            display = live_prefix + base_display
            race = live.get("race") or {}
            add_item(
                display,
                "play_livestream",
                playable=True,
                slug=live.get("slug"),
                art=_wec_local_art(race.get("path", "")),
                plot="{} – {}".format(race.get("label", "FIA WEC"), title),
            )

    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.setContent(HANDLE, "videos")
    xbmcplugin.endOfDirectory(HANDLE)


def wec_year(year):
    """Show all WEC races for one season/year."""
    try:
        slug = "fia-wec"
        url = "https://api.staylive.tv/platforms/{}/pages/path/{}".format(
            PLATFORM_UID, urllib.parse.quote(slug, safe="")
        )
        response = request_json(
            url, headers=_api_headers(),
            cache_ttl=CACHE_TTL_PAGE, cache_key="page:" + slug,
        )
        page = _message(response)
        if not isinstance(page, dict):
            raise RuntimeError("FIA-WEC-Seite hat ein unexpected format.")

        races = _discover_wec_races(page)
        wanted = str(year or "").strip()

        year_races = [r for r in races if r.get("year") == wanted]
        year_races.sort(key=lambda r: (r.get("date") or "", r.get("label") or ""))

        if wanted == "2026":
            add_item(
                L("Nächste Livestreams", "Upcoming livestreams"),
                "wec_next_livestreams",
                year=wanted,
                art=_folder_art(),
                plot="Currently live and announced FIA WEC livestreams – date and time shown in local time.",
            )

        for race in year_races:
            # The season menu is an archive. For the current season, hide
            # race weekends until their final calendar day has passed.
            if wanted == "2026":
                date_label_check = race.get("date_label") or ""
                end_match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})\s*$", date_label_check)
                if end_match:
                    archive_end = datetime(
                        int(end_match.group(3)),
                        int(end_match.group(2)),
                        int(end_match.group(1)),
                        ).date()
                    if archive_end > datetime.now().date():
                        continue

            date_label = race.get("date_label") or ""
            display = "{} – {}".format(date_label, race["label"]) if date_label else race["label"]
            add_item(
                display,
                "wec_race",
                path=race["path"],
                event_name=race["label"],
                year=wanted,
                art=_wec_local_art(race["path"]),
                plot="FIA WEC {} – {}".format(wanted, race["label"]),
                art_rev="1044",
            )

        playlists = {
            "2026": ("playlist_p-m2lLoaHVvX", "Full Access 2026"),
            "2025": ("playlist_r4APiLo9Rw2M", "Full Access 2025"),
        }
        if wanted in playlists:
            uid, playlist_label = playlists[wanted]
            add_item(
                playlist_label,
                "playlist",
                uid=uid,
                playlist_label=playlist_label,
                art=_folder_art(),
                plot="FIA WEC – {}".format(playlist_label),
            )

        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
        xbmcplugin.setContent(HANDLE, "videos")
        xbmcplugin.endOfDirectory(HANDLE)

    except Exception as exc:
        log("WEC year failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            "FIAWEC+",
            L("WEC-Saison {} konnte nicht geladen werden:\n\n{}", "WEC season {} could not be loaded:\n\n{}").format(year, exc)
        )
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def wec_icons():
    """Open the WEC Icons feed directly from the FIA WEC page."""
    try:
        url = "https://api.staylive.tv/platforms/{}/pages/path/fia-wec".format(PLATFORM_UID)
        page = _message(request_json(
            url, headers=_api_headers(),
            cache_ttl=CACHE_TTL_PAGE, cache_key="page:fia-wec",
        ))
        for item in _collect_video_channel_feeds(page):
            title = item.get("title") or ""
            if _pretty_event_name(title) != "WEC Icons":
                continue
            return feed(
                item.get("start") or "",
                item.get("end") or "",
                str(item.get("channel") or ""),
                "1",
            )
        raise RuntimeError("WEC Icons feed was not found.")
    except Exception as exc:
        log("WEC Icons failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok("FIAWEC+", L("WEC Icons konnte nicht geladen werden:\n\n{}", "WEC Icons could not be loaded:\n\n{}").format(exc))
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def wec_series():
    """Open FIA WEC and show season/year folders first."""
    try:
        slug = "fia-wec"
        url = "https://api.staylive.tv/platforms/{}/pages/path/{}".format(
            PLATFORM_UID, urllib.parse.quote(slug, safe="")
        )
        response = request_json(
            url, headers=_api_headers(),
            cache_ttl=CACHE_TTL_PAGE, cache_key="page:" + slug,
        )
        page = _message(response)
        if not isinstance(page, dict):
            raise RuntimeError("FIA-WEC-Seite hat ein unexpected format.")

        races = _discover_wec_races(page)

        years = set(r.get("year") for r in races if r.get("year"))
        years.update(("2026", "2025"))

        for year in sorted(years, reverse=True):
            add_item(
                year,
                "wec_year",
                year=year,
                art=_folder_art(),
                plot=L("FIA World Endurance Championship – Saison {}", "FIA World Endurance Championship – Season {}").format(year),
            )

        add_item(
            "Originals",
            "fiawec_originals",
            art=_menu_art(),
            plot="Originals",
            rev="12150",
        )
        add_item(
            "WEC Insider",
            "playlist",
            uid="playlist_GjrZFhxdScR_",
            playlist_label="WEC Insider",
            art=_menu_art(),
            plot="WEC Insider – The most compelling stories from each race weekend, from inside the FIA WEC.",
            rev="12150",
        )

        icons_path = os.path.join(
            ADDON.getAddonInfo("path"), "resources", "wec", "wec-icons.jpg"
        )
        add_item(
            "WEC Icons",
            "wec_icons",
            art={
                "thumb": icons_path,
                "icon": icons_path,
                "poster": icons_path,
                "fanart": ADDON.getAddonInfo("fanart"),
            },
            plot="FIA World Endurance Championship – WEC Icons",
            rev="12150",
        )

        xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
        xbmcplugin.setContent(HANDLE, "videos")
        xbmcplugin.endOfDirectory(HANDLE)

    except Exception as exc:
        log("WEC series failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            "FIAWEC+",
            L("FIA WEC konnte nicht geladen werden:\n\n{}", "FIA WEC could not be loaded:\n\n{}").format(exc)
        )
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)

