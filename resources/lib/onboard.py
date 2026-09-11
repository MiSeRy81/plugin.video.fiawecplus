# -*- coding: utf-8 -*-
"""WEC onboard replay matching/filter helpers.

Internal refactor module.  No Kodi UI and no network requests live here.
It centralizes the rules that decide whether a Staylive video belongs to a
specific WEC race/class/year, including the Le Mans vs. Lone Star Le Mans
edge case and exclusion of ELMS/MLMC support-series videos.
"""
from __future__ import annotations

import re

from resources.lib.utils import normalize_slug


def match_context(path):
    """Return ``(wanted_year, useful_race_tokens)`` for a WEC race path."""
    clean_path = str(path or "").strip().lstrip("/")
    race_slug = clean_path.rstrip("/").split("/")[-1].lower()

    match = re.search(r"(20\d{2})", str(path or ""))
    wanted_year = match.group(1) if match else "2026"

    race_name_key = race_slug
    for prefix in (
        "6-hours-of-", "8-hours-of-", "24-hours-of-",
        "rolex-6-hours-of-", "totalenergies-6-hours-of-",
    ):
        if race_name_key.startswith(prefix):
            race_name_key = race_name_key[len(prefix):]
            break

    race_tokens = [x for x in re.split(r"[^a-z0-9]+", race_name_key) if x]
    # Keep lone/star: they distinguish Lone Star Le Mans from Le Mans.
    stop_tokens = {"hours", "hour", "of", "the", "totalenergies", "rolex"}
    useful_tokens = [x for x in race_tokens if x not in stop_tokens]
    return wanted_year, useful_tokens or race_tokens


def video_is_other_series(video):
    """Return True for ELMS/MLMC videos that must not leak into WEC."""
    if not isinstance(video, dict):
        return False
    slug = str(video.get("seo_string") or video.get("slug") or "").lower()
    title = str(video.get("name") or video.get("title") or "").lower()
    channel_path = str(video.get("channelPath") or video.get("channel_path") or "").lower()
    channel_name = str(video.get("channelName") or video.get("channel_name") or "").lower()
    markers = ("elms", "european-le-mans-series", "mlmc", "michelin-le-mans-cup")
    return any(
        marker in haystack
        for haystack in (slug, title, channel_path, channel_name)
        for marker in markers
    )


def session_from_title(title):
    """Return stable ``(key, label)`` for an onboard replay title."""
    text = str(title or "").strip()
    low = text.lower()
    if "hyperpole" in low:
        return "hyperpole", "Hyperpole"
    if "qualifying" in low or "qualification" in low:
        return "qualifying", "Qualifying"
    if "free practice 3" in low or "fp3" in low:
        return "fp3", "Free Practice 3"
    if "free practice 2" in low or "fp2" in low:
        return "fp2", "Free Practice 2"
    if "free practice 1" in low or "fp1" in low:
        return "fp1", "Free Practice 1"
    if "free practice" in low:
        return "fp4", "Free Practice 4"
    if re.search(r"(?:^|\|)\s*race\s*$", text, re.I) or " | race" in low:
        return "race", "Race"
    return "warmup", "Warmup"


def video_matches(video, wanted_class, wanted_year, useful_tokens=None,
                  require_race_tokens=True):
    """Return True when a Staylive video belongs to the requested onboard set."""
    if not isinstance(video, dict) or video_is_other_series(video):
        return False

    wanted_class = str(wanted_class or "").strip().lower()
    wanted_year = str(wanted_year or "").strip()
    tags = [str(tag).strip().lower() for tag in (video.get("tags") or []) if str(tag).strip()]
    if wanted_class and wanted_class not in tags:
        return False
    if wanted_year and wanted_year.lower() not in tags:
        return False

    title = str(video.get("name") or video.get("title") or "").strip()
    if wanted_year and wanted_year not in title:
        return False

    channel_path = str(video.get("channelPath") or video.get("channel_path") or "").strip().lower()
    if "onboard" not in channel_path:
        return False
    if require_race_tokens and useful_tokens and not all(tok in channel_path for tok in useful_tokens):
        return False
    return True


def prepare_video(video, wanted_class, wanted_year, useful_tokens=None,
                  require_race_tokens=True, seen_slugs=None):
    """Validate and normalize one onboard result, returning a copied dict or None."""
    if not video_matches(video, wanted_class, wanted_year, useful_tokens, require_race_tokens):
        return None

    slug = normalize_slug(video.get("seo_string") or video.get("slug") or "")
    title = str(video.get("name") or video.get("title") or slug).strip()
    if not slug or not title:
        return None
    if seen_slugs is not None and slug in seen_slugs:
        return None

    if seen_slugs is not None:
        seen_slugs.add(slug)
    item = dict(video)
    item["_slug"] = slug
    item["_title"] = title
    item["_session_key"], item["_session_label"] = session_from_title(title)
    return item
