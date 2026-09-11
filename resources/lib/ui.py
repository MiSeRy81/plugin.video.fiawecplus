# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import urllib.parse
from datetime import datetime, timezone

import xbmc
import xbmcgui
import xbmcplugin


OFFICIAL_SERIES_ART = {
    "wec": "https://www.fiawec.com/uploads/instagram-634242a889b22889adccbdc2e9876006-69371a9ee1d84002751267.jpg",
    "elms": "https://www.europeanlemansseries.com/media/cache/hero_desktop/umbrella_media/photo-1920x1080-69d80d5e9d564145750315.jpg",
    "mlmc": "https://www.lemanscup.com/media/cache/hero_desktop/umbrella_media/00-mlmc-collective2-69d649699f7a1099464138.jpg",
}

_CTX = {}


def configure(**deps):
    """Configure the Kodi UI facade from main.py without creating imports back to it."""
    _CTX.clear()
    _CTX.update(deps)


def _d(name):
    return _CTX[name]


def make_url(action, **params):
    query = {"action": action}
    query.update(params)
    return _d("BASE_URL") + "?" + urllib.parse.urlencode(query)


def add_item(label, action=None, playable=False, art=None, plot=None, **params):
    li = xbmcgui.ListItem(label=label)
    info = {"title": label}
    if plot:
        info["plot"] = plot
    li.setInfo("video", info)

    if art:
        clean_art = {k: v for k, v in art.items() if v}
        if clean_art:
            li.setArt(clean_art)

    if playable:
        li.setProperty("IsPlayable", "true")

    base_url = _d("BASE_URL")
    url = make_url(action, **params) if action else base_url
    xbmcplugin.addDirectoryItem(
        handle=_d("HANDLE"),
        url=url,
        listitem=li,
        isFolder=not playable and action not in (
            "settings", "input_slug", "refresh_token",
            "oauth_reopen_login",
            "oauth_import_token_file", "oauth_direct_login",
            "oauth_cookie_login_file", "oauth_cookie_login_manual",
            "oauth_cookie_select_shared", "oauth_cookie_login_shared",
            "oauth_logout", "oauth_status", "oauth_refresh_test"
        ),
    )


def root():
    L = _d("L")
    add_item(
        "FIA World Endurance Championship",
        "wec_series",
        art=official_series_art("wec"),
        plot=L("FIA WEC – Rennen, Sessions, Replays und kostenfreie Inhalte", "FIA WEC – races, sessions, replays and free content"),
        rev="1041",
    )
    add_item(
        "European Le Mans Series",
        "elms_series",
        art=official_series_art("elms"),
        plot=L("European Le Mans Series – Rennen, Sessions und Replays", "European Le Mans Series – races, sessions and replays"),
        rev="1041",
    )
    add_item(
        "Michelin Le Mans Cup",
        "mlmc_series",
        art=official_series_art("mlmc"),
        plot=L("Michelin Le Mans Cup – Rennen, Sessions und Replays", "Michelin Le Mans Cup – races, sessions and replays"),
        rev="1041",
    )
    add_item(
        L("Konto", "Account"),
        "account_menu",
        art=menu_art(),
        plot=L("FIAWEC+ – Konto und Anmeldung", "FIAWEC+ – account and sign-in"),
        rev="1041",
    )
    xbmcplugin.addSortMethod(_d("HANDLE"), xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.setContent(_d("HANDLE"), "videos")
    xbmcplugin.endOfDirectory(_d("HANDLE"))


def url_from_art_value(value):
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("http://") or value.startswith("https://"):
            return value
        return ""
    if isinstance(value, dict):
        for key in (
            "url", "src", "source", "href", "original", "large",
            "landscape", "desktop", "image", "thumbnail"
        ):
            found = url_from_art_value(value.get(key))
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = url_from_art_value(item)
            if found:
                return found
    return ""


def extract_art_url(*objects):
    preferred = (
        "thumbnail", "thumbnailUrl", "thumbnail_url",
        "image", "imageUrl", "image_url",
        "landscapeImage", "landscape_image",
        "backgroundImage", "background_image",
        "cover", "poster", "artwork", "hero", "media"
    )
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        for key in preferred:
            found = url_from_art_value(obj.get(key))
            if found:
                return found
        for value in obj.values():
            if isinstance(value, dict):
                for key in preferred:
                    found = url_from_art_value(value.get(key))
                    if found:
                        return found
    return ""


def official_series_art(key):
    addon = _d("ADDON")
    image_url = OFFICIAL_SERIES_ART.get(key) or addon.getAddonInfo("icon")
    return {
        "thumb": image_url,
        "icon": image_url,
        "poster": image_url,
        "fanart": addon.getAddonInfo("fanart"),
    }


def resource_art(filename):
    addon = _d("ADDON")
    path = os.path.join(addon.getAddonInfo("path"), "resources", filename)
    return {
        "thumb": path,
        "icon": path,
        "poster": path,
        "fanart": addon.getAddonInfo("fanart"),
    }


def menu_art(image_url=""):
    addon = _d("ADDON")
    icon = image_url or addon.getAddonInfo("icon")
    return {
        "thumb": icon,
        "icon": icon,
        "poster": icon,
        "fanart": addon.getAddonInfo("fanart"),
    }


def folder_art(image_url=""):
    addon = _d("ADDON")
    icon = image_url or addon.getAddonInfo("icon")
    fanart = image_url or addon.getAddonInfo("fanart")
    return {
        "thumb": icon,
        "icon": icon,
        "poster": icon,
        "fanart": fanart,
    }


def friendly_feed_title(props, start, end, channel_id):
    title = _d("text_value")(props.get("title"))
    if title:
        return title
    if start.startswith("2025-12-31") and end.startswith("2026-12-30"):
        return _d("L")("Saison 2026", "2026 Season")
    return "{} – {}".format(start[:10], end[:10])


def iso_to_datetime(value):
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


def is_future_feed(start):
    dt = iso_to_datetime(start)
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt > datetime.now(timezone.utc)


def feed_preview_art(start, end, channel_id):
    cache_key = "preview_art:{}:{}:{}".format(channel_id, start, end)
    try:
        url = "https://api.staylive.tv/videos/feed?limit=6&page=1&categories=false"
        if start and end:
            start_q = urllib.parse.quote(start, safe=":-.")
            end_q = urllib.parse.quote(end, safe=":-.")
            url += "&date_range_start={}&date_range_end={}".format(start_q, end_q)
        response = _d("request_json")(
            url,
            headers=_d("feed_headers")(channel_id),
            cache_ttl=_d("CACHE_TTL_PREVIEW_ART"),
            cache_key=cache_key,
        )
        videos = _d("message")(response)
        if isinstance(videos, list):
            ordered = sorted(
                [v for v in videos if isinstance(v, dict)],
                key=lambda v: (
                    0 if "race" in (v.get("name") or "").lower() else
                    1 if "highlight" in (v.get("name") or "").lower() else 2
                )
            )
            for video in ordered:
                thumb = video.get("thumbnail") or extract_art_url(video)
                if thumb:
                    return thumb
    except Exception as exc:
        _d("log")("Preview artwork failed for channel {}: {}".format(channel_id, exc), xbmc.LOGWARNING)
    return ""
