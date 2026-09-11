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
    value = (title or "").strip()
    if value.upper().startswith("REPLAY ONBOARD - "):
        value = value[len("REPLAY ONBOARD - "):].strip()
    return value.upper()


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

    if onboard_start and onboard_end and onboard_channel:
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
        xbmcgui.Dialog().ok(
            "FIAWEC+",
            ctx["L"]("Serien-Liste fehlgeschlagen:\n\n{}", "Series list failed:\n\n{}").format(exc)
        )
        xbmcplugin.endOfDirectory(ctx["handle"], succeeded=False)


def _render_wec(feeds, series_name, ctx):
    L = ctx["L"]
    for item in feeds:
        label = pretty_event_name(item["title"], L)
        image_url = ctx["feed_preview_art"](item["start"], item["end"], item["channel"])
        ctx["add_item"](
            label, "feed", start=item["start"], end=item["end"], channel=item["channel"], page="1",
            art=ctx["folder_art"](image_url), plot="{} – {}".format(series_name, label),
        )
    if not feeds:
        xbmcgui.Dialog().notification(
            "FIAWEC+", L("No WEC content feeds found", "No WEC content feeds found"),
            xbmcgui.NOTIFICATION_WARNING, 5000,
        )
    _finish(ctx["handle"])


def _render_mlmc(feeds, slug, series_name, ctx):
    L = ctx["L"]
    season = season_from_slug(slug)
    if season == "2026":
        ctx["add_item"](
            L("Nächste Livestreams", "Upcoming livestreams"),
            "series_next_livestreams", series_key="mlmc", year=season,
            art=ctx["official_series_art"]("mlmc"),
            plot="Currently live and announced Michelin Le Mans Cup livestreams – date and time shown in local time.",
        )

    for item in feeds:
        if item["onboard"]:
            continue
        raw_title = item["title"].strip()
        if raw_title.upper() in ("2026 SEASON", "2025 SEASON", "2024 SEASON"):
            label = L("Saison {}".format(season), "{} Season".format(season))
        else:
            label = michelin_event_name(raw_title, L)
            if "mugello" in label.lower() and season != "2024":
                continue
            weekend = ctx["series_weekend_label"]("mlmc", label, season)
            if weekend:
                label = weekend + " – " + label
        image_url = ctx["feed_preview_art"](item["start"], item["end"], item["channel"])
        ctx["add_item"](
            label, "feed", start=item["start"], end=item["end"], channel=item["channel"], page="1",
            art=ctx["folder_art"](image_url), plot="{} – {}".format(series_name, label),
        )

    if not feeds:
        xbmcgui.Dialog().notification(
            "FIAWEC+", L("No video feeds found for {}", "No video feeds found for {}").format(series_name),
            xbmcgui.NOTIFICATION_WARNING, 5000,
        )
    _finish(ctx["handle"])


def _render_elms(feeds, slug, series_name, ctx):
    L = ctx["L"]
    season = season_from_slug(slug)
    if season == "2026":
        ctx["add_item"](
            L("Nächste Livestreams", "Upcoming livestreams"),
            "series_next_livestreams", series_key="elms", year=season,
            art=ctx["official_series_art"]("elms"),
            plot="Currently live and announced European Le Mans Series livestreams – date and time shown in local time.",
        )

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

    if season_feed:
        season_art = ctx["feed_preview_art"](
            season_feed["start"], season_feed["end"], season_feed["channel"]
        )
        ctx["add_item"](
            L("Saison {}".format(season), "{} Season".format(season)),
            "feed", start=season_feed["start"], end=season_feed["end"], channel=season_feed["channel"], page="1",
            art=ctx["folder_art"](season_art),
            plot=L("{} – Saison {}", "{} – Season {}").format(series_name, season),
        )

    for key in order:
        pair = events[key]
        main_feed = pair["main"]
        onboard_feed = pair["onboard"]
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
                art=ctx["folder_art"](image_url), plot=display_name,
            )
        else:
            ctx["add_item"](
                display_name, "event_group",
                art=ctx["folder_art"](image_url), plot=display_name,
                event=event_name,
                main_start=main_feed["start"] if main_feed else "",
                main_end=main_feed["end"] if main_feed else "",
                main_channel=main_feed["channel"] if main_feed else "",
                onboard_start=onboard_feed["start"] if onboard_feed else "",
                onboard_end=onboard_feed["end"] if onboard_feed else "",
                onboard_channel=onboard_feed["channel"] if onboard_feed else "",
            )

    if not feeds:
        xbmcgui.Dialog().notification(
            "FIAWEC+", L("No video feeds found for {}", "No video feeds found for {}").format(series_name),
            xbmcgui.NOTIFICATION_WARNING, 5000,
        )
    _finish(ctx["handle"])


def _finish(handle):
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.setContent(handle, "videos")
    xbmcplugin.endOfDirectory(handle)
