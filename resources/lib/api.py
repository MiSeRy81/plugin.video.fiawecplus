# -*- coding: utf-8 -*-
"""Low-level Staylive/FIA WEC+ API helpers.

Internal refactor module.  This module deliberately has no Kodi dependency;
main.py remains responsible for authentication state, cache storage and UI.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from resources.lib.config import USER_AGENT
from resources.lib.utils import _message, _video_object_from_response, normalize_slug


def request_json(url, method="GET", data=None, headers=None, cache_ttl=0,
                 cache_key=None, cache_get=None, cache_set=None):
    """Perform a JSON request with optional caller-provided cache callbacks."""
    use_cache = bool(cache_ttl) and method == "GET" and data is None
    key = cache_key or url
    if use_cache and cache_get is not None:
        cached = cache_get(key)
        if cached is not None:
            return cached

    payload = None
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if headers:
        req_headers.update(headers)

    if data is not None:
        payload = urllib.parse.urlencode(data).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

    req = urllib.request.Request(url, data=payload, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            result = json.loads(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError("HTTP {}: {}".format(exc.code, body[:500]))
    except urllib.error.URLError as exc:
        raise RuntimeError("Netzwerkfehler: {}".format(exc.reason))

    if use_cache and cache_set is not None:
        cache_set(key, result, cache_ttl)
    return result


def api_headers(token, referer=None):
    return {
        "Authorization": "Bearer {}".format(token),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://plus.fiawec.com",
        "Referer": referer or "https://plus.fiawec.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "TE": "trailers",
    }


def feed_headers(channel_id):
    return {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Language": "en",
        "X-STAYLIVE-CHANNELS": str(channel_id),
        "Origin": "https://plus.fiawec.com",
        "Referer": "https://plus.fiawec.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Priority": "u=4",
        "TE": "trailers",
    }


def get_video(slug, token, request_func):
    """Fetch one authenticated Staylive video object."""
    slug = normalize_slug(slug)
    template = "https://api.staylive.tv/videos/{slug}"
    url = template.replace("{slug}", urllib.parse.quote(slug, safe=""))
    headers = {
        "Authorization": "Bearer {}".format(token),
        "Accept": "*/*",
        "Accept-Language": "en",
        "Content-Type": "application/json",
        "Origin": "https://plus.fiawec.com",
        "Referer": "https://plus.fiawec.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    return _video_object_from_response(request_func(url, headers=headers))


def get_livestream(slug, token, request_func):
    """Fetch one authenticated Staylive livestream object."""
    slug = normalize_slug(slug)
    url = "https://api.staylive.tv/livestreams/{}".format(
        urllib.parse.quote(slug, safe="")
    )
    data = _message(request_func(url, headers=api_headers(token)))
    if not isinstance(data, dict):
        raise RuntimeError("Invalid livestream response")
    return data
