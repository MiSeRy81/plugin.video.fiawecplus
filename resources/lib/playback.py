# -*- coding: utf-8 -*-
from __future__ import annotations

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.utils import normalize_slug, _find_playback_url, _clean_text


def _fail(handle, title, message, log, log_prefix):
    log("{}: {}".format(log_prefix, message), xbmc.LOGERROR)
    xbmcgui.Dialog().ok(title, message)
    xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())


def play_livestream(slug, *, handle, get_livestream, log, translate):
    """Resolve a Staylive livestream URL and hand it to Kodi."""
    slug = normalize_slug(slug)
    if not slug:
        xbmcgui.Dialog().notification(
            "FIAWEC+",
            translate("Ungültiger Livestream-Slug", "Invalid livestream slug"),
            xbmcgui.NOTIFICATION_ERROR,
        )
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    try:
        stream = get_livestream(slug)
        playback_url = _find_playback_url(stream)
        if not playback_url:
            keys = ", ".join(sorted(str(k) for k in stream.keys()))
            raise RuntimeError(
                "Livestream does not contain a playback_url. "
                "Vorhandene Felder: {}".format(keys[:700])
            )

        title = stream.get("name") or stream.get("title") or slug
        item = xbmcgui.ListItem(label=title, path=playback_url)
        item.setInfo("video", {
            "title": title,
            "plot": _clean_text(stream.get("description")) or "",
        })
        item.setProperty("IsPlayable", "true")
        item.setMimeType("application/vnd.apple.mpegurl")
        xbmcplugin.setResolvedUrl(handle, True, item)
    except Exception as exc:
        _fail(
            handle,
            "FIAWEC+",
            translate(
                "Livestream-Wiedergabe fehlgeschlagen:\n\n{}",
                "Livestream playback failed:\n\n{}",
            ).format(exc),
            log,
            "Livestream playback failed",
        )


def play_video(slug, *, handle, get_video, log, translate):
    """Resolve a Staylive VOD URL and hand it to Kodi."""
    slug = normalize_slug(slug)
    if not slug:
        xbmcgui.Dialog().notification(
            "FIAWEC+",
            translate("Ungültiger Video-Slug", "Invalid video slug"),
            xbmcgui.NOTIFICATION_ERROR,
        )
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    try:
        video = get_video(slug)
        playback_url = _find_playback_url(video)
        if not playback_url:
            keys = ", ".join(sorted(str(k) for k in video.keys()))
            raise RuntimeError(
                "Video object does not contain a playback_url. "
                "Vorhandene Felder: {}".format(keys[:700])
            )

        title = video.get("name") or slug
        item = xbmcgui.ListItem(label=title, path=playback_url)
        item.setInfo("video", {
            "title": title,
            "plot": _clean_text(video.get("description")) or "",
        })

        thumb = video.get("thumbnail")
        if thumb:
            item.setArt({"thumb": thumb, "icon": thumb, "poster": thumb})

        item.setProperty("IsPlayable", "true")
        item.setMimeType("application/vnd.apple.mpegurl")
        xbmcplugin.setResolvedUrl(handle, True, item)
    except Exception as exc:
        _fail(
            handle,
            "FIAWEC+",
            translate(
                "Wiedergabe fehlgeschlagen:\n\n{}",
                "Playback failed:\n\n{}",
            ).format(exc),
            log,
            "Playback failed",
        )
