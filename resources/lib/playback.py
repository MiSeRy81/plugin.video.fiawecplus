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
            subscriber_only = video.get("subscribers_only", video.get("subscribersOnly"))
            is_paid = False
            if isinstance(subscriber_only, bool):
                is_paid = subscriber_only
            elif isinstance(subscriber_only, (int, float)):
                is_paid = subscriber_only != 0
            elif isinstance(subscriber_only, str):
                is_paid = subscriber_only.strip().lower() in ("1", "true", "yes", "pay", "paid")

            if is_paid:
                _fail(
                    handle,
                    "FIAWEC+",
                    translate(
                        "Kostenpflichtiges Abonnement erforderlich\n\nDieses Video erfordert ein kostenpflichtiges FIAWEC+ Abonnement.",
                        "Paid subscription required\n\nThis video requires a paid FIAWEC+ subscription.",
                    ),
                    log,
                    "Paid subscription required",
                )
                return

            _fail(
                handle,
                "FIAWEC+",
                translate(
                    "Dieses Video ist derzeit nicht zur Wiedergabe verfügbar.",
                    "This video is currently unavailable for playback.",
                ),
                log,
                "Playback URL unavailable",
            )
            return

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
