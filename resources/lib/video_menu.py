# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import urllib.parse

import xbmc
import xbmcgui
import xbmcplugin


def video_date_label(video):
    if not isinstance(video, dict):
        return ""
    for key in ("published_at","publishedAt","publish_at","publishAt",
                "publication_date","publicationDate","published",
                "start_date","startDate","created_at","createdAt","date"):
        value = video.get(key)
        if isinstance(value, str):
            match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value.strip())
            if match:
                return "{}.{}.{}".format(match.group(3), match.group(2), match.group(1))
    return ""


def video_display_title(video, title, include_date=False, forced_access=""):
    """Build a video title without FREE/PAY access prefixes."""
    if include_date:
        date_label = video_date_label(video)
        if date_label:
            return "{} – {}".format(date_label, title)
    return title


def short_video_title(name):
    name = (name or "").strip()
    if not name:
        return "Video"
    cleaned = re.sub(r"\s*\|\s*ELMS\s*$", "", name, flags=re.I)
    cleaned = re.sub(r"^4 Hours of [^|]+\|\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*\|\s*4 Hours of [^|]+$", "", cleaned, flags=re.I)
    m = re.match(r"^\[([A-Z]{2})\]\s*\|\s*(Race|Qualifying)$", cleaned, flags=re.I)
    if m:
        return "{} [{}]".format(m.group(2).title(), m.group(1).upper())
    m = re.match(r"^(Race|Qualifying)\s*\[([A-Z]{2})\]$", cleaned, flags=re.I)
    if m:
        return "{} [{}]".format(m.group(1).title(), m.group(2).upper())
    return cleaned.strip(" |") or name


def extract_video_list(response, message):
    payload = message(response)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("videos", "items", "results"):
            if isinstance(payload.get(key), list):
                return payload.get(key)
        data = payload.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("videos", "items", "results"):
                if isinstance(data.get(key), list):
                    return data.get(key)
    return []


def videos_by_tag_request(tag_ids, page_num, ctx):
    tags = [str(x).strip() for x in (tag_ids or []) if str(x).strip()]
    if not tags:
        raise RuntimeError("No tag ID is available for the onboard feed")
    base = "https://api.staylive.tv/platforms/{}/videos-by-tag".format(ctx["platform_uid"])
    parts = [
        "limit=50",
        "page={}".format(urllib.parse.quote(str(page_num or "1"), safe="")),
    ]
    for tag in tags:
        parts.append("tags={}".format(urllib.parse.quote(tag, safe="")))
    url = base + "?" + "&".join(parts)
    try:
        response = ctx["request_json"](url, headers=ctx["api_headers"]())
        videos = extract_video_list(response, ctx["message"])
        ctx["log"]("videos-by-tag accepted: {}".format(url), xbmc.LOGINFO)
        return response, videos
    except Exception as exc:
        text = str(exc)
        if "404" in text and "No videos found on this channel" in text:
            return {}, []
        raise


def render_tag_feed(tags, start, end, page_num, all_tags_required, suppress_access, ctx):
    try:
        tag_ids = [x for x in str(tags or "").split(",") if x]
        current_page = int(page_num or "1")
        response, videos = videos_by_tag_request(tag_ids, str(current_page), ctx)
        for video in videos:
            if not isinstance(video, dict):
                continue
            title = video.get("name") or video.get("title") or "Video"
            slug = video.get("seo_string") or video.get("slug") or ""
            if not slug:
                continue
            display_title = title if str(suppress_access) == "1" else video_display_title(video, title)
            li = xbmcgui.ListItem(label=display_title)
            li.setProperty("IsPlayable", "true")
            li.setInfo("video", {
                "title": title,
                "plot": ctx["clean_text"](video.get("description")) or title,
                "duration": ctx["duration_seconds"](video.get("duration")),
            })
            thumb = video.get("thumbnail") or ctx["extract_art_url"](video)
            if thumb:
                li.setArt({"thumb": thumb, "icon": thumb, "poster": thumb, "fanart": thumb})
            xbmcplugin.addDirectoryItem(
                handle=ctx["handle"], url=ctx["make_url"]("play", slug=slug),
                listitem=li, isFolder=False,
            )
        if len(videos) >= 50:
            ctx["add_item"](
                ctx["L"]("Nächste Seite", "Next page"), "tag_feed",
                tags=",".join(tag_ids), start=start, end=end,
                page=str(current_page + 1), all_tags_required=str(all_tags_required),
                suppress_access=str(suppress_access), art=ctx["folder_art"](),
            )
        if not videos:
            xbmcgui.Dialog().notification(
                "FIA WEC+",
                ctx["L"]("Keine Onboard-Replays in diesem Feed found.", "No onboard replays found in this feed."),
                xbmcgui.NOTIFICATION_INFO, 3500,
            )
        xbmcplugin.setContent(ctx["handle"], "videos")
        xbmcplugin.endOfDirectory(ctx["handle"])
    except Exception as exc:
        ctx["log"]("Tag feed failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            "FIA WEC+",
            ctx["L"]("Onboard-Replay-Feed fehlgeschlagen:\n\n{}", "Onboard replay feed failed:\n\n{}").format(exc),
        )
        xbmcplugin.endOfDirectory(ctx["handle"], succeeded=False)


def render_originals(ctx):
    originals = (
        ("PROJECT GENESIS", "playlist_HKa_zrpfWvsW"),
        ("FORD MISSION HYPERCAR", "playlist_5PhDTc7ZqZp6"),
        ("BRUCE'S DREAM", "playlist_yRQcXj0agQUx"),
    )
    for label, uid in originals:
        ctx["add_item"](label, "playlist", uid=uid, playlist_label=label,
                        art=ctx["menu_art"](), plot=label)
    xbmcplugin.addSortMethod(ctx["handle"], xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.setContent(ctx["handle"], "videos")
    xbmcplugin.endOfDirectory(ctx["handle"])


def render_playlist(uid, label, ctx):
    uid = (uid or "").strip()
    if not uid:
        xbmcgui.Dialog().ok("FIA WEC+", ctx["L"]("Invalid playlist ID.", "Invalid playlist ID."))
        xbmcplugin.endOfDirectory(ctx["handle"], succeeded=False)
        return
    referer = "https://plus.fiawec.com/en/playlist/{}".format(uid)
    base = "https://api.staylive.tv/platforms/{}/playlists/uid/{}".format(
        ctx["platform_uid"], urllib.parse.quote(uid, safe=""))
    try:
        metadata = ctx["request_json"](base, headers=ctx["api_headers"](referer=referer))
        response = ctx["request_json"](base + "?page=1&limit=100", headers=ctx["api_headers"](referer=referer))
        videos = ctx["collect_playlist_videos"](ctx["message"](response))
        if not videos:
            videos = ctx["collect_playlist_videos"](ctx["message"](metadata))
        if not videos:
            xbmcgui.Dialog().ok(
                "FIA WEC+",
                ctx["L"]("{} wurde geladen, aber es wurden keine Videos erkannt.",
                         "{} was loaded, but no videos were found.").format(label),
            )
            xbmcplugin.endOfDirectory(ctx["handle"], succeeded=False)
            return
        for video in videos:
            title = video.get("name") or video.get("title") or "Video"
            display_title = video_display_title(video, title, include_date=True)
            slug = video.get("seo_string") or video.get("seoString") or ""
            if not slug:
                continue
            li = xbmcgui.ListItem(label=display_title)
            li.setProperty("IsPlayable", "true")
            li.setInfo("video", {
                "title": title,
                "plot": ctx["clean_text"](video.get("description")) or title,
                "duration": ctx["duration_seconds"](video.get("duration")),
            })
            thumb = video.get("thumbnail") or video.get("thumbnail_url") or video.get("image")
            if isinstance(thumb, dict):
                thumb = thumb.get("url") or ""
            if thumb:
                li.setArt({"thumb": thumb, "icon": thumb, "poster": thumb, "fanart": thumb})
            xbmcplugin.addDirectoryItem(
                handle=ctx["handle"], url=ctx["make_url"]("play", slug=slug),
                listitem=li, isFolder=False,
            )
        xbmcplugin.addSortMethod(ctx["handle"], xbmcplugin.SORT_METHOD_NONE)
        xbmcplugin.setContent(ctx["handle"], "videos")
        xbmcplugin.endOfDirectory(ctx["handle"])
    except Exception as exc:
        ctx["log"]("Playlist failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            "FIA WEC+",
            ctx["L"]("{} konnte nicht geladen werden:\n\n{}", "{} could not be loaded:\n\n{}").format(label, exc),
        )
        xbmcplugin.endOfDirectory(ctx["handle"], succeeded=False)



def _is_elms_onboard_video(video):
    if not isinstance(video, dict):
        return False
    name = str(video.get("name") or video.get("title") or "")
    low = name.lower()
    return (
        "elms" in low
        and bool(re.search(r"(?:n[°ºo]?\s*|#)\s*\d{1,3}", name, re.I))
        and any(token in low for token in ("lmp2", "lmp3", "lmgt3"))
    )


def _elms_onboard_compact_title(name):
    original = str(name or "").strip()
    low = original.lower()

    if "qualifying" in low:
        session = "Qualifying"
    else:
        # Some ELMS race onboard titles (e.g. Barcelona) omit the word "Race".
        session = "Race"

    if "lmp2 pro/am" in low or "lmp2 pro-am" in low:
        cls = "LMP2 PRO/AM"
    elif "lmp2" in low:
        cls = "LMP2"
    elif "lmp3" in low:
        cls = "LMP3"
    elif "lmgt3" in low:
        cls = "LMGT3"
    else:
        cls = ""

    # Keep only car number + team from the first title segment.
    first = original.split("|", 1)[0].strip()
    first = re.sub(r"(?i)^n[°ºo]?\s*", "#", first)
    first = re.sub(
        r"\s*[-–]\s*(?:LMP2\s*PRO[/ -]?AM|LMP2|LMP3|LMGT3)\s*$",
        "",
        first,
        flags=re.I,
    ).strip()

    return " | ".join(x for x in ("ELMS", session, cls, first) if x)


def _elms_onboard_sort_key(video):
    name = str((video or {}).get("name") or (video or {}).get("title") or "")
    low = name.lower()

    if "qualifying" in low:
        session_order = 1
    else:
        # Session-less ELMS onboard titles are race onboards.
        session_order = 0

    if "lmp2" in low:
        class_order = 0
    elif "lmp3" in low:
        class_order = 1
    elif "lmgt3" in low:
        class_order = 2
    else:
        class_order = 9

    number_match = re.search(r"(?:n[°ºo]?\s*|#)\s*(\d{1,3})", name, re.I)
    number = int(number_match.group(1)) if number_match else 9999
    return (session_order, class_order, number, low)

def render_feed(start, end, channel_id, page_num, forced_access, suppress_access, ctx):
    try:
        current_page = int(page_num or "1")
        url = "https://api.staylive.tv/videos/feed?limit=20&page={}&categories=false".format(current_page)
        if start and end:
            start_q = urllib.parse.quote(start, safe=":-.")
            end_q = urllib.parse.quote(end, safe=":-.")
            url += "&date_range_start={}&date_range_end={}".format(start_q, end_q)
        response = ctx["request_json"](url, headers=ctx["feed_headers"](channel_id))
        videos = ctx["message"](response)
        if not isinstance(videos, list):
            raise RuntimeError("Video-Feed hat ein unexpected format.")

        # ELMS archive onboard feeds use the normal /videos/feed endpoint.
        # Apply compact titles only when the whole returned page is made up
        # of recognizable ELMS onboard videos.
        playable_videos = [v for v in videos if isinstance(v, dict)]
        elms_onboard_feed = bool(playable_videos) and all(
            _is_elms_onboard_video(v) for v in playable_videos
        )
        if elms_onboard_feed:
            videos = sorted(videos, key=_elms_onboard_sort_key)

        for video in videos:
            if not isinstance(video, dict):
                continue
            title = video.get("name") or "Video"
            original_title = title
            if elms_onboard_feed and _is_elms_onboard_video(video):
                display_title = _elms_onboard_compact_title(title)
            else:
                display_title = title if str(suppress_access) == "1" else video_display_title(
                    video, title, forced_access=forced_access)
            slug = video.get("seo_string") or ""
            if not slug:
                continue
            li = xbmcgui.ListItem(label=display_title)
            li.setProperty("IsPlayable", "true")
            li.setInfo("video", {
                "title": title,
                "plot": ctx["clean_text"](video.get("description")) or original_title,
                "duration": ctx["duration_seconds"](video.get("duration")),
            })
            thumb = video.get("thumbnail")
            if thumb:
                li.setArt({"thumb": thumb, "icon": thumb, "poster": thumb, "fanart": thumb})
            xbmcplugin.addDirectoryItem(
                handle=ctx["handle"], url=ctx["make_url"]("play", slug=slug),
                listitem=li, isFolder=False,
            )
        total_pages = 1
        if isinstance(response, dict):
            data = response.get("data") or {}
            if isinstance(data, dict):
                pc = data.get("pageCount") or {}
                if isinstance(pc, dict):
                    try:
                        total_pages = int(pc.get("totalPages") or 1)
                    except (TypeError, ValueError):
                        total_pages = 1
        if current_page < total_pages:
            ctx["add_item"](
                ctx["L"]("Nächste Seite", "Next page"), "feed",
                art=ctx["folder_art"](), start=start, end=end,
                channel=str(channel_id), page=str(current_page + 1),
                suppress_access=str(suppress_access),
            )
        xbmcplugin.setContent(ctx["handle"], "videos")
        xbmcplugin.endOfDirectory(ctx["handle"])
    except Exception as exc:
        text = str(exc)
        if "404" in text and "No videos found on channels" in text:
            ctx["log"]("Feed empty (future/unpublished): {}".format(text), xbmc.LOGINFO)
            xbmcgui.Dialog().notification(
                "FIA WEC+", "No videos are available for this race yet.",
                xbmcgui.NOTIFICATION_INFO, 3500,
            )
            xbmcplugin.setContent(ctx["handle"], "videos")
            xbmcplugin.endOfDirectory(ctx["handle"])
            return
        ctx["log"]("Feed failed: {}".format(exc), xbmc.LOGERROR)
        try:
            debug_url = url
        except Exception:
            debug_url = ctx["L"]("(URL could not be built)", "(URL could not be built)")
        xbmcgui.Dialog().ok(
            "FIA WEC+",
            ctx["L"]("Video-Feed fehlgeschlagen:\n\n{}\n\nURL:\n{}",
                     "Video feed failed:\n\n{}\n\nURL:\n{}").format(exc, debug_url),
        )
        xbmcplugin.endOfDirectory(ctx["handle"], succeeded=False)
