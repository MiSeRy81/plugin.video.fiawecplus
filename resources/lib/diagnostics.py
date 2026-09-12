# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

import xbmc
import xbmcgui

# Runtime dependencies are injected by main.py after all handlers/helpers exist.
def configure(**dependencies):
    globals().update(dependencies)

_DIAG_SENSITIVE_KEYS = {
    "access_token", "accessToken", "refresh_token", "refreshToken", "id_token",
    "idToken", "authorization", "Authorization", "cookie", "Cookie",
    "playback_url", "playbackUrl", "manifest", "manifest_url", "manifestUrl",
    "stream_url", "streamUrl"
}

def _diag_sanitize(value, depth=0):
    if depth > 5:
        return "…"
    if isinstance(value, dict):
        return {
            str(k): ("<redacted>" if str(k) in _DIAG_SENSITIVE_KEYS
                     else _diag_sanitize(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_diag_sanitize(v, depth + 1) for v in value[:30]]
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "…"
    return value


def _diag_find_matches(value, path="$", matches=None):
    if matches is None:
        matches = []

    if isinstance(value, dict):
        for key, child in value.items():
            child_path = "{}.{}".format(path, key)
            key_text = str(key).lower()
            if any(term in key_text for term in ("next", "session", "live", "stream")):
                matches.append({
                    "path": child_path,
                    "value": _diag_sanitize(child)
                })
            _diag_find_matches(child, child_path, matches)

    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _diag_find_matches(child, "{}[{}]".format(path, idx), matches)

    elif isinstance(value, str):
        text = value.lower()
        if (
            "next sessions" in text
            or "/livestream/" in text
            or "livestream/" in text
            or "session" in text
        ):
            matches.append({
                "path": path,
                "value": _diag_sanitize(value)
            })

    return matches


def diagnose_next_sessions():
    """Inspect the Imola 2026 WEC race page for onboard replay feeds/videos."""
    try:
        clean_path = "race/6-hours-of-imola"
        page_url = "https://api.staylive.tv/platforms/{}/pages/path/{}".format(
            PLATFORM_UID, urllib.parse.quote(clean_path, safe="")
        )
        page = _message(request_json(page_url, headers=_api_headers()))
        if not isinstance(page, dict):
            raise RuntimeError("Invalid Imola page response")

        feeds = _collect_video_channel_feeds(page)
        result = {
            "target": "Find Imola 2026 onboard replays on the race page",
            "seite": clean_path,
            "feeds": [],
        }

        def safe_video(v):
            return {
                "id": v.get("id") or v.get("uid"),
                "name": v.get("name") or v.get("title"),
                "seo_string": v.get("seo_string") or v.get("slug"),
                "duration": v.get("duration"),
            }

        for f in feeds:
            channel = str(f.get("channel") or "")
            start = f.get("start") or ""
            end = f.get("end") or ""
            title = f.get("title") or "Videos"

            row = {
                "title": title,
                "channel": channel,
                "start": start,
                "end": end,
                "videos": [],
                "onboard_treffer": [],
            }

            url = (
                "https://api.staylive.tv/videos/feed"
                "?limit=100&page=1&categories=false"
            )
            if start and end:
                url += "&date_range_start={}&date_range_end={}".format(
                    urllib.parse.quote(start, safe=":-."),
                    urllib.parse.quote(end, safe=":-.")
                )

            try:
                videos = _message(request_json(url, headers=_feed_headers(channel)))
                if isinstance(videos, list):
                    row["anzahl"] = len(videos)
                    row["videos"] = [
                        safe_video(v) for v in videos[:25] if isinstance(v, dict)
                    ]
                    row["onboard_treffer"] = [
                        safe_video(v)
                        for v in videos
                        if isinstance(v, dict)
                        and any(term in str(v.get("name") or v.get("title") or "").lower()
                                for term in ("onboard", "on board", "camera"))
                    ][:50]
                else:
                    row["antwort_typ"] = type(videos).__name__
            except Exception as exc:
                row["fehler"] = str(exc)[:300]

            result["feeds"].append(row)

        # Also surface all ContentFeed titles/types so hidden onboard sections
        # that are not VIDEO_CHANNELS become visible in the diagnostic.
        all_contentfeeds = []
        def walk(value):
            if isinstance(value, dict):
                if value.get("name") == "ContentFeed":
                    props = value.get("props") or {}
                    if isinstance(props, dict):
                        all_contentfeeds.append({
                            "type": props.get("type"),
                            "title": _text_value(props.get("title")) or "",
                            "id": props.get("id"),
                            "dateRangeFilter": props.get("dateRangeFilter"),
                        })
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(page)
        result["alle_contentfeeds"] = all_contentfeeds

        text = json.dumps(result, ensure_ascii=False, indent=2)
        log("IMOLA ONBOARD DIAG: {}".format(text), xbmc.LOGINFO)
        xbmcgui.Dialog().textviewer(
            "FIA WEC+ Diagnostics – Imola Onboard Replays",
            text
        )

    except Exception as exc:
        xbmcgui.Dialog().ok(
            "FIA WEC+ Diagnostics",
            "Imola onboard diagnostics failed:\n\n{}".format(str(exc)[:900])
        )


def diagnose_extra_content():
    """Probe candidates for content the addon does not surface yet.

    Three things in one pass:
    1. Dump every ContentFeed block (type/title/id) on the ELMS and MLMC
       landing pages, so an Insider/Originals/Icons-style feed (if one
       exists there, like WEC already has) becomes visible.
    2. Try a handful of likely slugs for seasons older than the ones we
       hardcode (WEC/ELMS/MLMC 2023/2024) and report which ones actually
       resolve instead of 404ing.
    3. List every year currently discoverable on the main "fia-wec" page,
       so we can see whether older seasons are already reachable there
       under a label we're not recognizing yet.
    """
    result = {
        "note": "Inventory only - nothing will be changed.",
        "elms_mlmc_feeds": {},
        "aeltere_saisons_test": {},
        "wec_main_page_years": {},
    }

    def dump_feeds(slug):
        url = "https://api.staylive.tv/platforms/{}/pages/path/{}".format(
            PLATFORM_UID, urllib.parse.quote(slug, safe="")
        )
        try:
            page = _message(request_json(url, headers=_api_headers()))
        except Exception as exc:
            return {"fehler": str(exc)[:300]}
        if not isinstance(page, dict):
            return {"fehler": "unerwartetes Seitenformat"}

        feeds = []
        def walk(value):
            if isinstance(value, dict):
                if value.get("name") == "ContentFeed":
                    props = value.get("props") or {}
                    if isinstance(props, dict):
                        feeds.append({
                            "type": props.get("type"),
                            "title": _text_value(props.get("title")) or "",
                            "id": props.get("id"),
                            "tags": props.get("tags"),
                        })
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(page)
        return {"anzahl_feeds": len(feeds), "feeds": feeds}

    for label, slug in (
        ("ELMS", "european-le-mans-series"),
        ("MLMC", "michelin-le-mans-cup"),
    ):
        result["elms_mlmc_feeds"][label] = dump_feeds(slug)

    candidate_slugs = [
        "fia-wec-2024", "fia-wec-2023",
        "european-le-mans-series-2023", "european-le-mans-series-2022",
        "michelin-le-mans-cup-2023", "michelin-le-mans-cup-2022",
    ]
    for slug in candidate_slugs:
        url = "https://api.staylive.tv/platforms/{}/pages/path/{}".format(
            PLATFORM_UID, urllib.parse.quote(slug, safe="")
        )
        try:
            page = _message(request_json(url, headers=_api_headers()))
            result["aeltere_saisons_test"][slug] = (
                "found" if isinstance(page, dict) else "unexpected format"
            )
        except Exception as exc:
            result["aeltere_saisons_test"][slug] = "fehler: {}".format(str(exc)[:150])

    try:
        url = "https://api.staylive.tv/platforms/{}/pages/path/fia-wec".format(PLATFORM_UID)
        page = _message(request_json(url, headers=_api_headers()))
        races = _discover_wec_races(page) if isinstance(page, dict) else []
        years = sorted(set(r.get("year") for r in races if r.get("year")), reverse=True)
        result["wec_main_page_years"]["founde_yeshre"] = years
        result["wec_main_page_years"]["anzahl_rennen"] = len(races)
    except Exception as exc:
        result["wec_main_page_years"]["fehler"] = str(exc)[:300]

    text = json.dumps(result, ensure_ascii=False, indent=2)
    log("EXTRA CONTENT DIAG: {}".format(text), xbmc.LOGINFO)
    xbmcgui.Dialog().textviewer(
        "FIA WEC+ Diagnostics – Extra Content",
        text
    )



    import urllib.error

    base = "https://api.staylive.tv/platforms/{}/videos-by-tag".format(PLATFORM_UID)
    tests = [
        ("tags=2026&tags=hypercar",
         base + "?limit=5&page=1&tags=2026&tags=hypercar"),
        ("tags=2026&tags=hypercar&channelId=6973",
         base + "?limit=5&page=1&tags=2026&tags=hypercar&channelId=6973"),
        ("tags=2026&tags=hypercar&channel_id=6973",
         base + "?limit=5&page=1&tags=2026&tags=hypercar&channel_id=6973"),
        ("tags=2026&tags=hypercar&channel=6973",
         base + "?limit=5&page=1&tags=2026&tags=hypercar&channel=6973"),
        ("tags=2026,hypercar&channelId=6973",
         base + "?limit=5&page=1&tags=2026%2Chypercar&channelId=6973"),
        ("tags=hypercar&channelId=6973",
         base + "?limit=5&page=1&tags=hypercar&channelId=6973"),
        ("tags=2026&channelId=6973",
         base + "?limit=5&page=1&tags=2026&channelId=6973"),
    ]

    headers = _api_headers()
    rows = []
    for label, url in tests:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    obj = json.loads(raw)
                    payload = _message(obj)
                    videos = _extract_video_list(obj)
                    names = []
                    for v in videos[:5]:
                        if isinstance(v, dict):
                            names.append(str(v.get("name") or v.get("title") or v.get("seo_string") or "")[:160])
                    summary = {
                        "status": getattr(resp, "status", 200),
                        "video_count": len(videos),
                        "sample_titles": names,
                    }
                    if isinstance(payload, dict):
                        summary["keys"] = sorted(str(k) for k in payload.keys())[:30]
                except Exception:
                    summary = {
                        "status": getattr(resp, "status", 200),
                        "body": raw[:700],
                    }
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            summary = {"status": exc.code, "body": body[:700]}
        except Exception as exc:
            summary = {"error": str(exc)[:700]}

        rows.append({"variante": label, "ergebnis": summary})

    text = json.dumps({
        "target": "Imola videos-by-tag mit Channel 6973 + Tags 2026/hypercar",
        "note": "Gesucht ist die Variante mit HTTP 200 und video_count > 0.",
        "tests": rows,
    }, ensure_ascii=False, indent=2)

    log("TAG ROUTE DIAG 1.5.14: {}".format(text), xbmc.LOGINFO)
    xbmcgui.Dialog().textviewer(
        "FIA WEC+ Diagnostics – Imola Tag Query",
        text
    )



def diagnose_onboard_video_fields():
    """Show the exact keys/values needed to turn a videos-by-tag result into a Kodi item."""
    import urllib.error
    url = (
        "https://api.staylive.tv/platforms/{}/videos-by-tag"
        "?limit=1&page=1&tags=2026%2Chypercar&channelId=6973"
    ).format(PLATFORM_UID)
    try:
        obj = request_json(url, headers=_api_headers())
        videos = _extract_video_list(obj)
        if not videos:
            raise RuntimeError("API liefert kein Testvideo")
        v = videos[0]
        safe = {}
        if isinstance(v, dict):
            for k, val in v.items():
                lk=str(k).lower()
                if lk in ("authorization","access_token","refresh_token","id_token","cookie","playback_url"):
                    continue
                if isinstance(val, (str,int,float,bool)) or val is None:
                    safe[str(k)] = val
                elif isinstance(val, dict):
                    # Only shallow scalar metadata; enough to locate slug/id/title.
                    safe[str(k)] = {
                        str(sk): sv for sk,sv in val.items()
                        if isinstance(sv,(str,int,float,bool)) or sv is None
                    }
        text=json.dumps({
            "status":"Treffer",
            "video_keys":sorted(str(k) for k in v.keys()) if isinstance(v,dict) else [],
            "erstes_video":safe,
        },ensure_ascii=False,indent=2)
        xbmcgui.Dialog().textviewer("FIA WEC+ Diagnostics – Onboard Video Fields", text)
    except Exception as exc:
        xbmcgui.Dialog().ok("FIA WEC+ Diagnostics", str(exc)[:900])


def diagnose_tag_structure():
    """Compact diagnostic for WEC VIDEO_CHANNEL_TAGS feeds."""
    try:
        clean_path = "race/6-hours-of-imola"
        page_url = "https://api.staylive.tv/platforms/{}/pages/path/{}".format(
            PLATFORM_UID, urllib.parse.quote(clean_path, safe="")
        )
        page = _message(request_json(page_url, headers=_api_headers()))
        if not isinstance(page, dict):
            raise RuntimeError("Invalid Imola page response")

        rows = []

        def compact(value):
            if not isinstance(value, dict):
                return value
            out = {}
            # Only fields potentially relevant to retrieving the tagged videos.
            wanted_exact = {
                "type", "id", "uid", "channel", "channelId", "channel_id",
                "channelUid", "channel_uid", "videoChannel", "videoChannelId",
                "video_channel", "video_channel_id", "container", "containerId",
                "playlist", "playlistId", "tag", "tags", "tagIds", "tag_ids",
                "allTagsRequired", "dateRangeFilter"
            }
            for k, v in value.items():
                if k in wanted_exact:
                    out[k] = v
            return out

        def walk(value, path="$"):
            if isinstance(value, dict):
                if value.get("name") == "ContentFeed":
                    props=value.get("props") or {}
                    if isinstance(props,dict) and props.get("type")=="VIDEO_CHANNEL_TAGS":
                        row={
                            "path": path,
                            "title": _text_value(props.get("title")) or "",
                        }
                        row.update(compact(props))
                        # Also inspect immediate ContentFeed siblings for IDs.
                        siblings=compact(value)
                        if siblings:
                            row["contentfeed_fields"]=siblings
                        rows.append(row)
                for k,v in value.items():
                    walk(v, "{}.{}".format(path,k))
            elif isinstance(value,list):
                for i,v in enumerate(value):
                    walk(v, "{}[{}]".format(path,i))

        walk(page)

        result={
            "target":"Imola VIDEO_CHANNEL_TAGS kompakt",
            "anzahl":len(rows),
            "feeds":rows,
        }
        text=json.dumps(result,ensure_ascii=False,indent=2)
        log("COMPACT TAG STRUCTURE DIAG: {}".format(text),xbmc.LOGINFO)
        xbmcgui.Dialog().textviewer(
            "FIA WEC+ Diagnostics – Compact Onboard Feeds",
            text
        )
    except Exception as exc:
        xbmcgui.Dialog().ok(
            "FIA WEC+ Diagnostics",
            "Compact tag diagnostics failed:\n\n{}".format(str(exc)[:900])
        )
