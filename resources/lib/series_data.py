# -*- coding: utf-8 -*-
"""Series/event data helpers for FIAWEC+.

Internal refactor module.  This module deliberately contains no Kodi UI code
and performs no HTTP requests.  It normalizes and filters data already loaded
by the plugin, keeping WEC/ELMS/MLMC catalogue rules separate from main.py.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from resources.lib.config import (
    ELMS_2026_WEEKENDS, ELMS_2025_WEEKENDS, ELMS_2024_WEEKENDS,
    MLMC_2026_WEEKENDS, MLMC_2025_WEEKENDS, MLMC_2024_WEEKENDS,
    WEC_SEASON_SCHEDULES,
)
from resources.lib.utils import normalize_slug, _parse_staylive_datetime


def _pretty_event_name(title):
    """Small UI-independent copy of the event-title normalization rules."""
    title = (title or "").strip()
    if title.upper().startswith("REPLAY ONBOARD - "):
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


def series_weekend_label(series_name, title, season="2026"):
    text = _pretty_event_name(title or "").lower()
    if series_name == "elms":
        table = {
            "2026": ELMS_2026_WEEKENDS,
            "2025": ELMS_2025_WEEKENDS,
            "2024": ELMS_2024_WEEKENDS,
        }.get(str(season), ELMS_2026_WEEKENDS)
    else:
        table = {
            "2026": MLMC_2026_WEEKENDS,
            "2025": MLMC_2025_WEEKENDS,
            "2024": MLMC_2024_WEEKENDS,
        }.get(str(season), MLMC_2026_WEEKENDS)
    for key, date_label in table.items():
        if key in text:
            return date_label
    return ""


def feed_title_year(title):
    """Extract an explicit season year from a feed title, e.g. Replay 2024."""
    text = _pretty_event_name(title or "")
    match = re.search(r"\b(20\d{2})\b", text)
    return match.group(1) if match else ""


def discover_wec_races(page, collect_race_paths):
    """Return canonical WEC season entries backed by available race pages."""
    race_paths = collect_race_paths(page)
    normalized = {p.strip("/").lower() for p in race_paths}

    # Current official 2026 pages stay visible even if Staylive has not linked
    # a future event from the landing page yet.
    for item in WEC_SEASON_SCHEDULES.get("2026", []):
        normalized.add(item["path"].strip("/").lower())

    races = []
    for year, schedule in WEC_SEASON_SCHEDULES.items():
        for item in schedule:
            path_norm = item["path"].strip("/").lower()
            if path_norm == "race/6-hours-of-barcelona":
                continue
            if year != "2026" and path_norm not in normalized:
                continue
            races.append({
                "path": item["path"],
                "label": item["label"],
                "year": year,
                "date": item["date"],
                "date_label": item["date_label"],
            })

    races.sort(
        key=lambda r: (r.get("year") or "", r.get("date") or "", r.get("label") or ""),
        reverse=True,
    )
    return races


def series_livestream_match(item, series_key):
    """Return True when a platform livestream clearly belongs to ELMS/MLMC."""
    slug = normalize_slug(item.get("seo_string") or item.get("slug") or "")
    title = str(item.get("name") or item.get("title") or "")
    haystack = "{} {}".format(slug, title).lower()

    if series_key == "elms":
        return bool(
            re.search(r"(?:^|[-_ |])elms(?:$|[-_ |])", haystack)
            or "european le mans series" in haystack
            or "european-le-mans-series" in haystack
        )
    if series_key == "mlmc":
        return bool(
            re.search(r"(?:^|[-_ |])mlmc(?:$|[-_ |])", haystack)
            or "michelin le mans cup" in haystack
            or "michelin-le-mans-cup" in haystack
            or "le mans cup" in haystack
        )
    return False


def future_series_livestreams(items, series_key, year="2026", now_utc=None):
    """Filter already-loaded Staylive items to upcoming/current ELMS or MLMC."""
    wanted = str(year or "2026").strip()
    now_utc = now_utc or datetime.now(timezone.utc)
    result = []
    seen = set()

    for item in items:
        if not series_livestream_match(item, series_key):
            continue

        slug = normalize_slug(item.get("seo_string") or item.get("slug") or "")
        if not slug or slug in seen:
            continue

        start_raw = item.get("start") or item.get("start_at") or item.get("startAt") or ""
        end_raw = item.get("end") or item.get("end_at") or item.get("endAt") or ""
        start_dt = _parse_staylive_datetime(start_raw)
        end_dt = _parse_staylive_datetime(end_raw)
        if not start_dt or start_dt.strftime("%Y") != wanted:
            continue
        if end_dt and end_dt <= now_utc:
            continue

        title = str(item.get("name") or item.get("title") or _pretty_event_name(slug)).strip()
        result.append({
            "slug": slug,
            "title": title,
            "start": start_raw,
            "start_dt": start_dt,
            "end": end_raw,
            "end_dt": end_dt,
        })
        seen.add(slug)

    result.sort(key=lambda x: (x["start_dt"], x["title"].lower()))
    return result


def future_wec_livestreams(items, year, event_match_slug, is_onboard_livestream, now_utc=None):
    """Filter already-loaded Staylive items to upcoming/current WEC streams."""
    wanted = str(year or "2026").strip()
    races = WEC_SEASON_SCHEDULES.get(wanted, [])
    now_utc = now_utc or datetime.now(timezone.utc)
    result = []
    seen = set()

    for item in items:
        slug = normalize_slug(item.get("seo_string") or item.get("slug") or "")
        if not slug or slug in seen:
            continue

        start_raw = item.get("start") or item.get("start_at") or item.get("startAt") or ""
        end_raw = item.get("end") or item.get("end_at") or item.get("endAt") or ""
        start_dt = _parse_staylive_datetime(start_raw)
        end_dt = _parse_staylive_datetime(end_raw)
        if not start_dt:
            continue
        if end_dt and end_dt <= now_utc:
            continue
        if start_dt.strftime("%Y") != wanted:
            continue

        race = None
        for candidate in races:
            if event_match_slug(candidate.get("path", ""), slug):
                race = candidate
                break
        if race is None:
            continue

        title = str(item.get("name") or item.get("title") or _pretty_event_name(slug)).strip()
        if is_onboard_livestream({"title": title}):
            continue
        result.append({
            "slug": slug,
            "title": title,
            "start": start_raw,
            "start_dt": start_dt,
            "end": end_raw,
            "end_dt": end_dt,
            "race": race,
        })
        seen.add(slug)

    result.sort(key=lambda x: (x["start_dt"], x["title"].lower()))
    return result
