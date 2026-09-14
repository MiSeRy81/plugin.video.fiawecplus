# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import urllib.parse

import xbmc
import xbmcgui
import xbmcplugin


WEC_SLUGS = {
    "fia-wec", "fia-world-endurance-championship",
    "world-endurance-championship", "wec",
}
MLMC_SLUGS = {
    "michelin-le-mans-cup", "michelin-le-mans-cup-2025",
    "michelin-le-mans-cup-2024",
}


def pretty_event_name(title, L):
    title = (title or "").strip()
    upper = title.upper()

    if upper == "2026 SEASON":
        return L("Saison 2026", "2026 Season")

    if upper.startswith("REPLAY ONBOARD - "):
        title = title[len("REPLAY ONBOARD - "):].strip()

    words = title.lower().split()
    small = {"of", "the", "and"}
    pretty = []
    for pos, word in enumerate(words):
        if word in small and pos:
            pretty.append(word)
        else:
            pretty.append(word[:1].upper() + word[1:])
    result = " ".join(pretty)
    result = re.sub(r"(?i)\bwec\b", "WEC", result)
    result = re.sub(r"(?i)spa[- ]francorchamps", "Spa-Francorchamps", result)
    result = re.sub(r"(?i)totalenergies", "TotalEnergies", result)
    return result


def event_key(title):
    """Return a stable ELMS event key for pairing main and onboard feeds.

    Staylive occasionally publishes an onboard feed with sponsor/year wording
    that differs from the main race feed (for example Silverstone). Pair known
    race weekends by venue first so those feeds still land in the same folder.
    """
    value = (title or "").strip()
    if value.upper().startswith("REPLAY ONBOARD - "):
        value = value[len("REPLAY ONBOARD - "):].strip()

    normalized = value.upper()
    normalized = normalized.replace("PORTIMÃO", "PORTIMAO")
    normalized = re.sub(r"\b20\d{2}\b", " ", normalized)
    normalized = re.sub(r"[^A-Z0-9]+", " ", normalized)
    normalized = " ".join(normalized.split())

    venue_keys = (
        ("SILVERSTONE", "SILVERSTONE"),
        ("SPA FRANCORCHAMPS", "SPA-FRANCORCHAMPS"),
        ("LE CASTELLET", "LE CASTELLET"),
        ("BARCELONA", "BARCELONA"),
        ("IMOLA", "IMOLA"),
        ("MUGELLO", "MUGELLO"),
        ("PORTIMAO", "PORTIMAO"),
    )
    for token, key in venue_keys:
        if token in normalized:
            return key

    return normalized


def is_onboard_title(title):
    return (title or "").strip().upper().startswith("REPLAY ONBOARD - ")


def series_display_name(slug):
    names = {
        "european-le-mans-series": "European Le Mans Series",
        "european-le-mans-series-2025": "European Le Mans Series 2025",
        "european-le-mans-series-2024": "European Le Mans Series 2024",
        "michelin-le-mans-cup": "Michelin Le Mans Cup",
        "michelin-le-mans-cup-2025": "Michelin Le Mans Cup 2025",
        "michelin-le-mans-cup-2024": "Michelin Le Mans Cup 2024",
        "fia-world-endurance-championship": "FIA World Endurance Championship",
        "world-endurance-championship": "FIA World Endurance Championship",
        "fia-wec": "FIA World Endurance Championship",
        "wec": "FIA World Endurance Championship",
    }
    return names.get(slug, slug.replace("-", " ").title())


def michelin_event_name(title, L):
    value = pretty_event_name(title, L)
    upper = value.upper()
    prefix = "4 HOURS OF "
    if upper.startswith(prefix):
        value = value[len("4 Hours of "):].strip()
    value = value.replace("Spa-francorchamps", "Spa-Francorchamps")
    value = value.replace("spa-francorchamps", "Spa-Francorchamps")
    return value


def season_from_slug(slug):
    if slug.endswith("-2025"):
        return "2025"
    if slug.endswith("-2024"):
        return "2024"
    return "2026"


def render_event_group(event, main_start, main_end, main_channel,
                       onboard_start, onboard_end, onboard_channel, ctx):
    image_url = ""
    if main_start and main_end and main_channel:
        image_url = ctx["feed_preview_art"](main_start, main_end, main_channel)
    if not image_url and onboard_start and onboard_end and onboard_channel:
        image_url = ctx["feed_preview_art"](onboard_start, onboard_end, onboard_channel)

    if main_start and main_end and main_channel:
        ctx["add_item"](
            ctx["L"]("Rennen & Sessions", "Races & sessions"),
            "feed", start=main_start, end=main_end, channel=main_channel, page="1",
            art=ctx["folder_art"](image_url),
            plot=ctx["L"](
                "Rennen, Qualifying, Highlights und weitere Sessions – {}",
                "Races, qualifying, highlights and other sessions – {}"
            ).format(event),
        )

    # Dedicated ELMS onboard channels are event-specific and may publish
    # replays after the main event feed's original date_range_end.  A channel
    # alone is therefore sufficient here; blank start/end intentionally make
    # render_feed query the complete dedicated onboard channel.
    if onboard_channel:
        ctx["add_item"](
            ctx["L"]("Onboard-Replays", "Onboard replays"),
            "feed", start=onboard_start, end=onboard_end, channel=onboard_channel, page="1",
            art=ctx["folder_art"](image_url),
            plot=ctx["L"]("Onboard-Replays – {}", "Onboard replays – {}").format(event),
        )

    _finish(ctx["handle"])


def render_season_menu(series_key, season_pages, ctx):
    if series_key == "elms":
        plot_name = "European Le Mans Series"
    else:
        plot_name = "Michelin Le Mans Cup"

    # Direct access to current/upcoming livestreams above the archive years.
    ctx["add_item"](
        ctx["L"]("Nächste Livestreams", "Upcoming livestreams"),
        "series_next_livestreams",
        series_key=series_key,
        year="2026",
        art=ctx["official_series_art"](series_key),
        plot=ctx["L"](
            "Aktuell laufende und angekündigte Livestreams – Datum und Uhrzeit in lokaler Zeit.",
            "Currently live and announced livestreams – date and time shown in local time."
        ),
    )

    for year in ("2026", "2025", "2024"):
        ctx["add_item"](
            year, "series", slug=season_pages[year],
            art=ctx["official_series_art"](series_key),
            plot="{} {}".format(plot_name, year),
        )
    _finish(ctx["handle"])


def render_series(slug, ctx):
    try:
        L = ctx["L"]
        series_name = series_display_name(slug)
        url = "https://api.staylive.tv/platforms/{}/pages/path/{}".format(
            ctx["platform_uid"], urllib.parse.quote(slug, safe="")
        )
        response = ctx["request_json"](
            url, headers=ctx["api_headers"](),
            cache_ttl=ctx["cache_ttl_page"], cache_key="page:" + slug,
        )
        page = ctx["message"](response)
        if not isinstance(page, dict):
            raise RuntimeError("Serien-Seite hat ein unexpected format.")

        feeds = []
        for discovered in ctx["collect_video_channel_feeds"](page):
            start_date = discovered.get("start") or ""
            end_date = discovered.get("end") or ""
            channel_id = discovered.get("channel") or ""
            title = discovered.get("title") or "Videos"
            if start_date and ctx["is_future_feed"](start_date):
                continue
            feeds.append({
                "start": start_date,
                "end": end_date,
                "channel": str(channel_id),
                "title": title,
                "onboard": is_onboard_title(title),
            })

        if slug in WEC_SLUGS:
            _render_wec(feeds, series_name, ctx)
            return
        if slug in MLMC_SLUGS:
            _render_mlmc(feeds, slug, series_name, ctx)
            return
        _render_elms(feeds, slug, series_name, ctx)

    except Exception as exc:
        ctx["log"]("Series failed: {}".format(exc), xbmc.LOGERROR)
        error_text = str(exc)
        if "Not signed in" in error_text or "sign in" in error_text.lower():
            message = ctx["L"](
                "Anmeldung erforderlich\n\nBitte melde dich über das FIA WEC+ Add-on an, um auf diese Inhalte zuzugreifen.",
                "Sign-in required\n\nPlease sign in through the FIA WEC+ add-on to access this content."
            )
        else:
            message = ctx["L"](
                "Serien-Liste fehlgeschlagen:\n\n{}",
                "Series list failed:\n\n{}"
            ).format(exc)
        xbmcgui.Dialog().ok("FIA WEC+", message)
        xbmcplugin.endOfDirectory(ctx["handle"], succeeded=False)


def _render_wec(feeds, series_name, ctx):
    """Legacy/direct WEC feed renderer kept safe for fallback routes."""
    L = ctx["L"]
    for item in feeds:
        label = pretty_event_name(item["title"], L)
        image_url = ctx["feed_preview_art"](item["start"], item["end"], item["channel"])
        ctx["add_item"](
            label, "feed",
            start=item["start"], end=item["end"], channel=item["channel"], page="1",
            art=ctx["folder_art"](image_url),
            plot=_event_plot(
                "FIA WEC",
                0,
                label,
                item["start"], item["end"],
            ),
        )

    if not feeds:
        xbmcgui.Dialog().notification(
            "FIA WEC+",
            L("No WEC content feeds found", "No WEC content feeds found"),
            xbmcgui.NOTIFICATION_WARNING,
            5000,
        )
    _finish(ctx["handle"])


def _compact_date_range(start_date, end_date):
    def one(value):
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(value or ""))
        return "{}.{}.{}".format(m.group(3), m.group(2), m.group(1)) if m else ""
    a, b = one(start_date), one(end_date)
    return " - ".join(x for x in (a, b) if x)


def _event_plot(series_name, round_no, event_name, start_date, end_date, date_label=""):
    date_line = str(date_label or "").replace(" – ", " - ").strip()
    if not date_line:
        date_line = _compact_date_range(start_date, end_date)
    lines = [series_name, event_name, date_line]
    return "\n".join(x for x in lines if x)


def _race_round_map(items):
    """Chronological Round 1..n for actual race-weekend items."""
    valid = []
    for item in items:
        if not item or item.get("onboard"):
            continue
        title = str(item.get("title") or "").strip()
        if title.upper() in ("2026 SEASON", "2025 SEASON", "2024 SEASON"):
            continue
        valid.append(item)
    valid.sort(key=lambda x: (str(x.get("start") or ""), str(x.get("title") or "").lower()))
    return {id(item): pos for pos, item in enumerate(valid, 1)}


def _mlmc_round_number(event_name, season):
    text = str(event_name or "").lower()
    if "barcelona" in text:
        return 1
    if "le castellet" in text:
        return 2
    if "road to le mans" in text:
        return 3
    if "spa-francorchamps" in text or "spa francorchamps" in text:
        return 4
    if str(season) == "2024":
        if "mugello" in text:
            return 5
        if "portimão" in text or "portimao" in text:
            return 6
    else:
        if "silverstone" in text:
            return 5
        if "portimão" in text or "portimao" in text:
            return 6
    return 0


def _render_mlmc(feeds, slug, series_name, ctx):
    L = ctx["L"]
    season = season_from_slug(slug)
    round_map = _race_round_map(feeds)

    for item in feeds:
        if item["onboard"]:
            continue
        raw_title = item["title"].strip()
        is_season_feed = raw_title.upper() in ("2026 SEASON", "2025 SEASON", "2024 SEASON")
        if is_season_feed:
            label = L("Saison {}".format(season), "{} Season".format(season))
            plot = label
        else:
            event_name = michelin_event_name(raw_title, L)
            # The source titles for older MLMC seasons often end in the year.
            # Keep the year in the folder label only where useful, but remove it
            # from the clean four-line information panel.
            clean_event_name = str(event_name or "").strip()
            year_suffix = " " + str(season)
            if clean_event_name.endswith(year_suffix):
                clean_event_name = clean_event_name[:-len(year_suffix)].rstrip()
            if "mugello" in event_name.lower() and season != "2024":
                continue

            weekend = ctx["series_weekend_label"]("mlmc", event_name, season)
            label = event_name
            if weekend:
                label = weekend + " – " + event_name

            round_no = _mlmc_round_number(event_name, season)
            date_line = (weekend or _compact_date_range(item["start"], item["end"])).replace(" – ", " - ")
            plot = "\n".join(x for x in (
                "Michelin Le Mans Cup",
                clean_event_name,
                date_line,
            ) if x)

        image_url = ctx["feed_preview_art"](item["start"], item["end"], item["channel"])
        ctx["add_item"](
            label, "feed", start=item["start"], end=item["end"], channel=item["channel"], page="1",
            art=ctx["folder_art"](image_url), plot=plot,
        )

    if not feeds:
        xbmcgui.Dialog().notification(
            "FIA WEC+", L("No video feeds found for {}", "No video feeds found for {}").format(series_name),
            xbmcgui.NOTIFICATION_WARNING, 5000,
        )
    _finish(ctx["handle"])



_ELMS_ONBOARD_VERIFIED_CHANNELS = {
    "SILVERSTONE": ("elms-silverstone-onboards", "7614"),
    "SPA-FRANCORCHAMPS": ("elms-spa-onboards", "7513"),
}


def _elms_onboard_channel_path(event_key_value):
    """Return the expected Staylive channel path for an ELMS event key."""
    key = str(event_key_value or "").strip().upper()
    if key == "SPA-FRANCORCHAMPS":
        venue = "spa"
    elif key == "LE CASTELLET":
        venue = "le-castellet"
    else:
        venue = key.lower().replace(" ", "-")
    venue = re.sub(r"[^a-z0-9-]+", "-", venue).strip("-")
    return "elms-{}-onboards".format(venue) if venue else ""


def _find_channel_record(value, expected_path):
    """Recursively find a Staylive channel object matching expected_path."""
    expected = str(expected_path or "").strip().lower()
    if isinstance(value, dict):
        path = str(
            value.get("path") or value.get("channelPath") or
            value.get("channel_path") or value.get("seo_string") or ""
        ).strip().lower()
        channel_id = value.get("id") or value.get("channel") or value.get("channelId") or value.get("channel_id")
        if path == expected and channel_id not in (None, ""):
            return {"path": path, "channel": str(channel_id)}
        for child in value.values():
            found = _find_channel_record(child, expected_path)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_channel_record(child, expected_path)
            if found:
                return found
    return None


def _resolve_elms_onboard_channel(event_key_value, ctx):
    """Resolve a dedicated ELMS onboard channel when it is not embedded.

    Newer ELMS race pages can publish onboard replays in a separate channel
    such as ``elms-silverstone-onboards`` or ``elms-spa-onboards`` without
    exposing that channel in the series page's VIDEO_CHANNEL feed list.
    Probe path-based Staylive routes first, then use verified channel IDs as
    a safe fallback for layouts already confirmed on FIA WEC+.
    """
    expected_path = _elms_onboard_channel_path(event_key_value)
    if not expected_path:
        return ""

    encoded = urllib.parse.quote(expected_path, safe="")
    platform = ctx["platform_uid"]
    candidates = (
        "https://api.staylive.tv/platforms/{}/channels/path/{}".format(platform, encoded),
        "https://api.staylive.tv/channels/path/{}".format(encoded),
        "https://api.staylive.tv/platforms/{}/channels?path={}".format(platform, encoded),
        "https://api.staylive.tv/channels?path={}".format(encoded),
    )

    for url in candidates:
        try:
            response = ctx["request_json"](url, headers=ctx["api_headers"]())
            payload = ctx["message"](response)
            found = _find_channel_record(payload, expected_path)
            if found:
                ctx["log"](
                    "ELMS onboard fallback resolved {} -> channel {}".format(
                        expected_path, found["channel"]
                    ),
                    xbmc.LOGINFO,
                )
                return found["channel"]
        except Exception as exc:
            ctx["log"](
                "ELMS onboard channel probe failed for {} via {}: {}".format(
                    expected_path, url, exc
                ),
                xbmc.LOGDEBUG,
            )

    verified = _ELMS_ONBOARD_VERIFIED_CHANNELS.get(str(event_key_value or "").strip().upper())
    if verified and verified[0] == expected_path:
        ctx["log"](
            "ELMS onboard fallback using verified {} -> channel {}".format(
                expected_path, verified[1]
            ),
            xbmc.LOGINFO,
        )
        return verified[1]
    return ""

def _render_elms(feeds, slug, series_name, ctx):
    L = ctx["L"]
    season = season_from_slug(slug)

    season_feed = None
    events = {}
    order = []
    for item in feeds:
        if item["title"].strip().upper() == "{} SEASON".format(season):
            season_feed = item
            continue
        key = event_key(item["title"])
        if key not in events:
            events[key] = {"main": None, "onboard": None}
            order.append(key)
        if item["onboard"]:
            events[key]["onboard"] = item
        else:
            events[key]["main"] = item

    elms_round_sources = [
        pair["main"] for pair in events.values() if pair.get("main")
    ]
    elms_round_sources.sort(key=lambda x: (str(x.get("start") or ""), str(x.get("title") or "").lower()))
    elms_round_map = {id(item): pos for pos, item in enumerate(elms_round_sources, 1)}

    for key in order:
        pair = events[key]
        main_feed = pair["main"]
        onboard_feed = pair["onboard"]

        # Some ELMS race weekends expose onboard replays in a dedicated
        # ``elms-<event>-onboards`` channel without embedding that channel in
        # the series page. Resolve it generically when the usual onboard feed
        # is missing. The event date range from the main feed keeps the video
        # query scoped to this exact race weekend.
        if main_feed:
            # For event channels that have been verified directly from the
            # FIA WEC+ video JSON, prefer the confirmed onboard channel ID.
            # This avoids relying on the series-page embedding, which is not
            # consistent for all ELMS rounds (e.g. Spa and Silverstone).
            verified = _ELMS_ONBOARD_VERIFIED_CHANNELS.get(str(key or "").strip().upper())
            if verified:
                onboard_feed = {
                    # Do not reuse the main feed date range here. Staylive can
                    # publish onboard race replays after that range has ended.
                    # The dedicated channel itself is already event-specific.
                    "start": "",
                    "end": "",
                    "channel": verified[1],
                    "title": "REPLAY ONBOARD - {}".format(key),
                    "onboard": True,
                }
                ctx["log"](
                    "ELMS onboard using verified {} -> channel {}".format(verified[0], verified[1]),
                    xbmc.LOGINFO,
                )
            elif not onboard_feed:
                fallback_channel = _resolve_elms_onboard_channel(key, ctx)
                if fallback_channel:
                    onboard_feed = {
                        # A resolved elms-<event>-onboards channel is specific
                        # to this race weekend, so query it without the main
                        # feed's date window.
                        "start": "",
                        "end": "",
                        "channel": fallback_channel,
                        "title": "REPLAY ONBOARD - {}".format(key),
                        "onboard": True,
                    }

        source = main_feed or onboard_feed
        if not source:
            continue
        event_name = pretty_event_name(source["title"], L)
        display_name = event_name
        weekend = ctx["series_weekend_label"]("elms", event_name, season)
        if weekend:
            display_name = weekend + " – " + event_name
        preview_source = main_feed or onboard_feed
        image_url = ctx["feed_preview_art"](
            preview_source["start"], preview_source["end"], preview_source["channel"]
        )

        if season in ("2025", "2024"):
            if not main_feed:
                continue
            ctx["add_item"](
                display_name, "feed", start=main_feed["start"], end=main_feed["end"], channel=main_feed["channel"], page="1",
                art=ctx["folder_art"](image_url),
                plot=_event_plot(
                    "European Le Mans Series",
                    elms_round_map.get(id(main_feed), 0),
                    event_name,
                    main_feed["start"], main_feed["end"],
                    weekend,
                ),
            )
        else:
            ctx["add_item"](
                display_name, "event_group",
                art=ctx["folder_art"](image_url),
                plot=_event_plot(
                    "European Le Mans Series",
                    elms_round_map.get(id(main_feed), 0) if main_feed else 0,
                    event_name,
                    source["start"], source["end"],
                    weekend,
                ),
                event=event_name,
                main_start=main_feed["start"] if main_feed else "",
                main_end=main_feed["end"] if main_feed else "",
                main_channel=main_feed["channel"] if main_feed else "",
                onboard_start=onboard_feed["start"] if onboard_feed else "",
                onboard_end=onboard_feed["end"] if onboard_feed else "",
                onboard_channel=onboard_feed["channel"] if onboard_feed else "",
            )

    # Keep general season/additional material after all race weekends.
    if season_feed:
        season_art = ctx["feed_preview_art"](
            season_feed["start"], season_feed["end"], season_feed["channel"]
        )
        ctx["add_item"](
            "{} Season - Additional Content".format(season),
            "feed", start=season_feed["start"], end=season_feed["end"], channel=season_feed["channel"], page="1",
            art=ctx["folder_art"](season_art),
            plot="European Le Mans Series\n{} Season - Additional Content".format(season),
        )

    if not feeds:
        xbmcgui.Dialog().notification(
            "FIA WEC+", L("No video feeds found for {}", "No video feeds found for {}").format(series_name),
            xbmcgui.NOTIFICATION_WARNING, 5000,
        )
    _finish(ctx["handle"])


def _finish(handle):
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.setContent(handle, "videos")
    xbmcplugin.endOfDirectory(handle)
