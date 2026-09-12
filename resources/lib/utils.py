# -*- coding: utf-8 -*-
"""Small dependency-free helpers shared by the Kodi add-on.

Keeping these functions outside main.py makes them independently testable.
"""
from __future__ import annotations

import base64
import hashlib
import html
import re
import secrets
import urllib.parse
from datetime import datetime, timezone, timedelta

def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _pkce_pair():
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _looks_like_image_url(value):
    if not isinstance(value, str):
        return False
    v = value.strip()
    if not v.startswith(("http://", "https://")):
        return False
    low = v.lower().split("?", 1)[0]
    return low.endswith((".jpg", ".jpeg", ".png", ".webp", ".avif")) or any(
        token in low for token in ("/image/", "/images/", "/media/", "/uploads/", "cloudinary")
    )


def _de_date(value):
    try:
        parts = (value or "")[:10].split("-")
        if len(parts) == 3:
            return "{}.{}.{}".format(parts[2], parts[1], parts[0])
    except Exception:
        pass
    return ""


def _parse_staylive_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _last_sunday(year, month):
    """Return the day number of the last Sunday in a month."""
    if month == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    last_day = next_month - timedelta(days=1)
    return last_day.day - ((last_day.weekday() + 1) % 7)


def _berlin_utc_offset(dt_utc):
    """CET/CEST offset using the EU DST rule, independent of system tzdata."""
    year = dt_utc.year
    # EU DST: last Sunday in March at 01:00 UTC until
    # last Sunday in October at 01:00 UTC.
    march_day = _last_sunday(year, 3)
    october_day = _last_sunday(year, 10)
    dst_start = datetime(year, 3, march_day, 1, 0, tzinfo=timezone.utc)
    dst_end = datetime(year, 10, october_day, 1, 0, tzinfo=timezone.utc)
    return timedelta(hours=2 if dst_start <= dt_utc < dst_end else 1)


def _berlin_datetime(value):
    """Return German local wall-clock time without depending on Kodi tzdata.

    Staylive timestamps are normalized to UTC first. The CET/CEST offset is
    then added directly. A naive datetime is intentional here: callers only
    use date()/strftime() for labels, so no further timezone conversion is
    required.
    """
    try:
        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_utc = dt.astimezone(timezone.utc)
        else:
            dt_utc = _parse_staylive_datetime(value)

        if not dt_utc:
            return None

        return (dt_utc + _berlin_utc_offset(dt_utc)).replace(tzinfo=None)
    except Exception:
        return None


def _berlin_datetime_label(value):
    dt = _berlin_datetime(value)
    if not dt:
        return ""
    return dt.strftime("%d.%m. %H:%M")


def normalize_slug(value):
    value = (value or "").strip()
    if not value:
        return ""

    if "://" in value:
        parsed = urllib.parse.urlparse(value)
        parts = [p for p in parsed.path.split("/") if p]
        if not parts:
            return ""
        return parts[-1]

    return value.strip("/")


def _video_object_from_response(response):
    """
    Staylive responses have appeared both as a top-level video object and as
    {"message": {...}, "statuscode": 200, "success": true}.
    Accept both forms.
    """
    if not isinstance(response, dict):
        raise RuntimeError("Unerwartete Video-API-Antwort.")

    message = response.get("message")
    if isinstance(message, dict):
        obj = dict(message)
        # keep status fields only if they are useful and not already present
        for key in ("statuscode", "success"):
            if key in response and key not in obj:
                obj[key] = response[key]
        return obj

    return response


def _find_playback_url(video):
    if not isinstance(video, dict):
        return None

    # Known field from FIA WEC+/Staylive
    url = video.get("playback_url")
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        return url

    # Defensive fallback in case Staylive nests the field later.
    for key, value in video.items():
        if isinstance(value, dict):
            found = _find_playback_url(value)
            if found:
                return found
    return None


def _message(response):
    if isinstance(response, dict) and isinstance(response.get("message"), (dict, list)):
        return response["message"]
    return response


def _text_value(value):
    if isinstance(value, str):
        value = value.strip()
        return value if value else ""

    if isinstance(value, dict):
        # Prefer semantic text/name/title fields first.
        for key in ("text", "title", "label", "name", "displayName"):
            if key in value:
                found = _text_value(value.get(key))
                if found:
                    return found

        # Then search recursively through remaining values.
        for child in value.values():
            found = _text_value(child)
            if found:
                return found

    if isinstance(value, list):
        for child in value:
            found = _text_value(child)
            if found:
                return found

    return ""


def _channel_value(value):
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if str(v).strip()]
        return ",".join(parts)
    if value is None:
        return ""
    return str(value).strip()


def _clean_text(value):
    """Convert Staylive HTML/escaped-HTML descriptions into clean Kodi text."""
    if value is None:
        return ""

    text = str(value)

    # Some Staylive descriptions contain escaped HTML such as &lt;p&gt;...&lt;/p&gt;.
    # Decode entities first so the following tag removal catches both forms.
    text = html.unescape(text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"(?i)<p(?:\s+[^>]*)?>", "", text)
    text = re.sub(r"<[^>]+>", "", text)

    # A second pass also catches doubly escaped entities.
    text = html.unescape(text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"(?i)<p(?:\s+[^>]*)?>", "", text)
    text = re.sub(r"<[^>]+>", "", text)

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _duration_seconds(value):
    if not value:
        return 0
    try:
        parts = [int(x) for x in str(value).split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
    except Exception:
        pass
    return 0

