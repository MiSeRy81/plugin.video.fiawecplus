# -*- coding: utf-8 -*-
from __future__ import annotations
import html
import os
import sys
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar
import re
import base64
import secrets
import webbrowser
import math
import struct
import zlib
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib.config import (
    USER_AGENT, PLATFORM_UID, OAUTH_CLIENT_ID, OAUTH_AUTHORIZE_URL,
    OAUTH_TOKEN_URL, OAUTH_REDIRECT_URI, OAUTH_SCOPE, OAUTH_AUDIENCE,
    OAUTH_ORGANIZATION, AUTH0_CLIENT_INFO,
)
from resources.lib.utils import _b64url, _pkce_pair, _message

ADDON = xbmcaddon.Addon()

def L(_de, en):
    return en

def log(msg, level=xbmc.LOGINFO):
    xbmc.log('[FIA WEC+] {}'.format(msg), level)

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stop urllib from silently following redirects.

    oauth_direct_login() needs to read the Location header itself after each
    step of the Auth0 login form (to pull out ?code=... or detect a bounce
    back to /u/login), so returning None here turns every 30x response into
    a normal urllib.error.HTTPError with the Location header intact instead
    of urllib transparently chasing it.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _oauth_post(payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OAUTH_TOKEN_URL,
        data=body,
        headers={
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Origin": "https://plus.fiawec.com",
            "Referer": "https://plus.fiawec.com/",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)

def _store_tokens(data):
    access_token = data.get("access_token") or ""
    refresh_token = data.get("refresh_token") or ""
    id_token = data.get("id_token") or ""
    expires = data.get("expires") or data.get("expires_in") or 0

    ADDON.setSetting("access_token", access_token)
    if refresh_token:
        ADDON.setSetting("refresh_token", refresh_token)
    if id_token:
        ADDON.setSetting("id_token", id_token)

    try:
        expires_num = int(float(expires))
    except Exception:
        expires_num = 0

    # Some APIs return seconds-to-expiry, others an absolute epoch timestamp.
    if expires_num > 2000000000:
        expires_at = expires_num
    elif expires_num > 0:
        expires_at = int(time.time()) + expires_num
    else:
        expires_at = 0
    ADDON.setSetting("expires_at", str(expires_at))

def _parse_cookie_header(raw):
    cookies = {}
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name:
            cookies[name] = value
    return cookies

class _TraceRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, trace):
        super().__init__()
        self.trace = trace

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            self.trace.append((code, newurl))
        except Exception:
            pass
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def _seed_cookiejar_from_header(jar, raw_cookie):
    count = 0
    for name, value in _parse_cookie_header(raw_cookie).items():
        for domain in ("auth.staylive.io", ".staylive.io"):
            try:
                cookie = http.cookiejar.Cookie(
                    version=0,
                    name=name,
                    value=value,
                    port=None,
                    port_specified=False,
                    domain=domain,
                    domain_specified=True,
                    domain_initial_dot=domain.startswith("."),
                    path="/",
                    path_specified=True,
                    secure=True,
                    expires=None,
                    discard=True,
                    comment=None,
                    comment_url=None,
                    rest={"HttpOnly": None},
                    rfc2109=False,
                )
                jar.set_cookie(cookie)
                count += 1
            except Exception as exc:
                log("Cookie seed failed for {}: {}".format(name, exc), xbmc.LOGWARNING)
    return count

def _seed_cookiejar_from_netscape(jar, text):
    count = 0
    names = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        http_only = False
        if line.startswith("#HttpOnly_"):
            http_only = True
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue

        parts = line.split("\t")
        if len(parts) < 7:
            continue

        domain, include_subdomains, path, secure, expires, name, value = parts[:7]
        domain_l = domain.lower()
        if "staylive.io" not in domain_l and "fiawec.com" not in domain_l:
            continue

        try:
            exp = int(expires) if expires and expires != "0" else None
        except Exception:
            exp = None

        rest = {"HttpOnly": None} if http_only else {}
        try:
            cookie = http.cookiejar.Cookie(
                version=0,
                name=name,
                value=value,
                port=None,
                port_specified=False,
                domain=domain,
                domain_specified=True,
                domain_initial_dot=domain.startswith("."),
                path=path or "/",
                path_specified=True,
                secure=(secure.upper() == "TRUE"),
                expires=exp,
                discard=(exp is None),
                comment=None,
                comment_url=None,
                rest=rest,
                rfc2109=False,
            )
            jar.set_cookie(cookie)
            count += 1
            names.append(name)
        except Exception as exc:
            log("Netscape cookie import failed for {}: {}".format(name, exc), xbmc.LOGWARNING)

    return count, names

def _cookie_names_for_log(jar):
    try:
        return sorted(set(c.name for c in jar))
    except Exception:
        return []

def _read_vfs_text(path):
    vfs = xbmcvfs.File(path)
    try:
        raw = vfs.readBytes()
    finally:
        vfs.close()

    if isinstance(raw, str):
        return raw
    raw = bytes(raw)
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")

def _write_vfs_text(path, text):
    vfs = xbmcvfs.File(path, "w")
    try:
        written = vfs.write(text)
    finally:
        vfs.close()
    return written

def _cookiejar_to_netscape(jar):
    """Serialize only Staylive/FIAWEC cookies, including HttpOnly cookies."""
    lines = [
        "# Netscape HTTP Cookie File",
        "# Updated automatically by FIA WEC+ Kodi add-on.",
        "# Do not edit while a Kodi login is running.",
    ]

    now = int(time.time())
    cookies = []
    for cookie in jar:
        domain_l = (cookie.domain or "").lower()
        if "staylive.io" not in domain_l and "fiawec.com" not in domain_l:
            continue
        if cookie.expires and int(cookie.expires) < now:
            continue
        cookies.append(cookie)

    cookies.sort(key=lambda c: (c.domain or "", c.path or "/", c.name or ""))

    for cookie in cookies:
        domain = cookie.domain or ""
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = cookie.path or "/"
        secure = "TRUE" if cookie.secure else "FALSE"
        expires = str(int(cookie.expires)) if cookie.expires else "0"

        rest = getattr(cookie, "_rest", {}) or {}
        is_http_only = any(str(k).lower() == "httponly" for k in rest.keys())
        prefix = "#HttpOnly_" if is_http_only else ""

        # Netscape format uses REAL tab characters and REAL line breaks.
        name = str(cookie.name or "").replace("\t", "").replace("\r", "").replace("\n", "")
        value = str(cookie.value or "").replace("\t", "").replace("\r", "").replace("\n", "")
        lines.append("{}{}\t{}\t{}\t{}\t{}\t{}\t{}".format(
            prefix, domain, include_subdomains, path, secure, expires, name, value
        ))

    return "\n".join(lines) + "\n"

def _shared_cookie_lock(path, wait_seconds=10):
    """Best-effort lock using a directory next to the shared cookie file."""
    lock_path = path + ".lock"
    deadline = time.time() + wait_seconds

    while time.time() < deadline:
        try:
            if xbmcvfs.mkdir(lock_path):
                return lock_path
        except Exception:
            pass
        xbmc.sleep(250)

    return ""

def _shared_cookie_unlock(lock_path):
    if not lock_path:
        return
    try:
        xbmcvfs.rmdir(lock_path)
    except Exception:
        pass

def _save_shared_cookie_file(path, jar):
    """Backup and atomically-ish replace the shared cookie file via Kodi VFS."""
    if not path:
        return False, "No cookie path is stored."

    lock_path = _shared_cookie_lock(path)
    if not lock_path:
        return False, "The shared cookie file is currently being used by another Kodi device."

    try:
        text = _cookiejar_to_netscape(jar)
        if text.count("\\n") <= 3:
            return False, "No Staylive cookies are available to save."

        backup_path = path + ".bak"
        temp_path = path + ".tmp"

        try:
            if xbmcvfs.exists(path):
                # Best effort backup; a failed backup must not destroy the working file.
                try:
                    if xbmcvfs.exists(backup_path):
                        xbmcvfs.delete(backup_path)
                    xbmcvfs.copy(path, backup_path)
                except Exception as exc:
                    log("Cookie file backup failed: {}".format(exc), xbmc.LOGWARNING)

            _write_vfs_text(temp_path, text)

            # Replace destination only after temp write succeeded.
            if xbmcvfs.exists(path):
                if not xbmcvfs.delete(path):
                    try:
                        xbmcvfs.delete(temp_path)
                    except Exception:
                        pass
                    return False, "The cookie file could not be replaced."

            if not xbmcvfs.rename(temp_path, path):
                # Some VFS backends do not support rename reliably; fall back to copy.
                if not xbmcvfs.copy(temp_path, path):
                    return False, "The updated cookie file could not be saved."
                try:
                    xbmcvfs.delete(temp_path)
                except Exception:
                    pass

            return True, ""
        finally:
            try:
                if xbmcvfs.exists(temp_path):
                    xbmcvfs.delete(temp_path)
            except Exception:
                pass
    finally:
        _shared_cookie_unlock(lock_path)

def oauth_cookie_select_shared():
    current = ADDON.getSetting("shared_cookie_path") or ""
    path = xbmcgui.Dialog().browse(
        1,
        "Select FIA WEC+ cookie file",
        "files",
        ".txt|.cookie|.cookies|.json",
        False,
        False,
        current
    )
    if not path:
        return

    ADDON.setSetting("shared_cookie_path", path)
    xbmcgui.Dialog().notification(
        "FIA WEC+",
        "Cookie file saved",
        xbmcgui.NOTIFICATION_INFO,
        3000,
    )

    if xbmcgui.Dialog().yesno(
        "FIA WEC+",
        "Cookie file saved.\\n\\nSign in with it now?"
    ):
        oauth_cookie_login_shared()

def oauth_cookie_login_shared():
    path = ADDON.getSetting("shared_cookie_path") or ""
    if not path:
        oauth_cookie_select_shared()
        return

    if not xbmcvfs.exists(path):
        xbmcgui.Dialog().ok(
            "FIA WEC+",
            "The saved cookie file is not reachable.\\n\\n"
            "Check the file location or select the cookie file again."
        )
        return

    try:
        text = (_read_vfs_text(path) or "").strip()
    except Exception as exc:
        xbmcgui.Dialog().ok(
            "FIA WEC+",
            "The shared cookie file could not be read:\\n\\n{}".format(exc)
        )
        return

    if not text:
        xbmcgui.Dialog().ok("FIA WEC+", "The cookie file is empty.")
        return

    # Repair the malformed Netscape serialization produced by version 1.0.0:
    # that version accidentally stored literal "\\n" / "\\t" sequences.
    # Only apply this to a Netscape file that otherwise consists of one line.
    if (
        "# Netscape HTTP Cookie File" in text
        and "\\n" in text
        and "\\t" in text
        and len(text.splitlines()) <= 1
    ):
        text = text.replace("\\r", "").replace("\\n", "\n").replace("\\t", "\t")

    if "…" in text:
        xbmcgui.Dialog().ok(
            "FIA WEC+",
            "The cookie file contains a truncated cookie (…)."
        )
        return

    # Pass the shared path so a successful Auth0 round-trip can write any
    # newly issued/updated cookies back to the NAS.
    if text.startswith("[") or text.startswith("{"):
        _oauth_cookie_login_with_value("", json_text=text, shared_path=path)
    elif "# Netscape HTTP Cookie File" in text or "\\tTRUE\\t/" in text or "\\tFALSE\\t/" in text or "#HttpOnly_" in text:
        _oauth_cookie_login_with_value("", netscape_text=text, shared_path=path)
    else:
        raw_cookie = text
        if raw_cookie.lower().startswith("cookie:"):
            raw_cookie = raw_cookie.split(":", 1)[1].strip()
        raw_cookie = " ".join(line.strip() for line in raw_cookie.splitlines() if line.strip())
        _oauth_cookie_login_with_value(raw_cookie, shared_path=path)

def _oauth_cookie_login_with_value(raw_cookie, netscape_text=None, json_text=None, shared_path=""):
    raw_cookie = (raw_cookie or "").strip()

    verifier, challenge = _pkce_pair()
    state = _b64url(secrets.token_bytes(32))
    nonce = _b64url(secrets.token_bytes(32))

    params = {
        "client_id": OAUTH_CLIENT_ID,
        "scope": OAUTH_SCOPE,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "audience": OAUTH_AUDIENCE,
        "response_type": "code",
        "response_mode": "query",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = OAUTH_AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)

    jar = http.cookiejar.CookieJar()
    trace = []
    imported = 0

    if json_text:
        imported, _ = _seed_cookiejar_from_json(jar, json_text)
    elif netscape_text:
        imported, _ = _seed_cookiejar_from_netscape(jar, netscape_text)
    elif raw_cookie:
        imported = _seed_cookiejar_from_header(jar, raw_cookie)

    if imported == 0:
        xbmcgui.Dialog().ok(
            "FIA WEC+ Cookie Sign-in",
            "No Staylive cookies could be imported from the file."
        )
        return

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        _TraceRedirect(trace),
    )

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://plus.fiawec.com/",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": USER_AGENT,
        }
    )

    try:
        resp = opener.open(req, timeout=30)
        final_url = resp.geturl()
        body = resp.read().decode("utf-8", "replace")

        parsed = urllib.parse.urlparse(final_url)
        q = urllib.parse.parse_qs(parsed.query)
        returned_state = (q.get("state") or [""])[0]
        code = (q.get("code") or [""])[0]
        error = (q.get("error") or [""])[0]
        error_desc = (q.get("error_description") or [""])[0]

        if error:
            xbmcgui.Dialog().ok(
                "FIA WEC+ Cookie Sign-in",
                "OAuth error:\n\n{}{}".format(
                    error,
                    ("\n" + error_desc) if error_desc else ""
                )
            )
            return

        if code:
            if returned_state != state:
                xbmcgui.Dialog().ok(
                    "FIA WEC+ Cookie Sign-in",
                    "OAuth state does not match. Sign-in was cancelled."
                )
                return

            payload = {
                "client_id": OAUTH_CLIENT_ID,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OAUTH_REDIRECT_URI,
            }
            data = _oauth_post(payload)
            _store_tokens(data)
            ADDON.setSetting("login_method", "cookie")

            shared_note = ""
            if shared_path:
                shared_note = (
                    "\n\nThe cookie file was read only "
                    "and remains unchanged."
                )

            xbmcgui.Dialog().ok(
                "FIA WEC+",
                "Cookie sign-in successful.\n\n"
                "Kodi stored its own access/refresh tokens via the browser session."
                + shared_note
            )
            xbmc.executebuiltin("Container.Refresh")
            return

        # Non-secret diagnostics only: cookie names and redirect hosts/paths.
        names = _cookie_names_for_log(jar)
        safe_trace = []
        for status, loc in trace[-6:]:
            try:
                p = urllib.parse.urlparse(loc)
                safe_trace.append("{} {}{}".format(status, p.netloc, p.path))
            except Exception:
                pass

        lower_url = (final_url or "").lower()
        lower_body = (body or "").lower()

        if (
            "login" in lower_url
            or "/u/login" in lower_url
            or "authorize/resume" in lower_url
            or "username" in lower_body
            or "password" in lower_body
        ):
            xbmcgui.Dialog().ok(
                "FIA WEC+ Cookie Sign-in",
                "The Staylive cookies were imported, but Auth0 still requires "
                "an interactive sign-in.\n\n"
                "Importierte Cookie-Namen:\n{}\n\n"
                "Letzte Redirects:\n{}".format(
                    ", ".join(names) if names else "keine",
                    "\n".join(safe_trace) if safe_trace else "keine"
                )
            )
            return

        xbmcgui.Dialog().ok(
            "FIA WEC+ Cookie Sign-in",
            "Kein Authorization Code received.\n\n"
            "Cookie-Namen: {}\n\n"
            "Letzte Redirects:\n{}".format(
                ", ".join(names) if names else "keine",
                "\n".join(safe_trace) if safe_trace else "keine"
            )
        )

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        xbmcgui.Dialog().ok(
            "FIA WEC+ Cookie Sign-in",
            "HTTP {} beim Cookie-Login.\n\n{}".format(exc.code, detail[:500])
        )
    except Exception as exc:
        log("Cookie login failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            "FIA WEC+ Cookie Sign-in",
            "Cookie sign-in failed:\n\n{}".format(exc)
        )

def _seed_cookiejar_from_json(jar, text):
    """Import common browser-extension JSON cookie exports."""
    try:
        data = json.loads(text)
    except Exception:
        return 0, []

    if isinstance(data, dict):
        # Common export wrappers.
        for key in ("cookies", "data", "items"):
            if isinstance(data.get(key), list):
                data = data.get(key)
                break

    if not isinstance(data, list):
        return 0, []

    count = 0
    names = []
    for item in data:
        if not isinstance(item, dict):
            continue

        name = item.get("name") or ""
        value = item.get("value") or ""
        domain = item.get("domain") or item.get("host") or ""
        path = item.get("path") or "/"

        if not name or not domain:
            continue

        domain_l = str(domain).lower()
        if "staylive.io" not in domain_l and "fiawec.com" not in domain_l:
            continue

        secure = bool(item.get("secure", True))
        expires = (
            item.get("expirationDate")
            if item.get("expirationDate") is not None
            else item.get("expires")
        )
        try:
            expires = int(float(expires)) if expires not in (None, "", 0, "0") else None
        except Exception:
            expires = None

        rest = {}
        if item.get("httpOnly") or item.get("httponly"):
            rest["HttpOnly"] = None

        try:
            cookie = http.cookiejar.Cookie(
                version=0,
                name=str(name),
                value=str(value),
                port=None,
                port_specified=False,
                domain=str(domain),
                domain_specified=True,
                domain_initial_dot=str(domain).startswith("."),
                path=str(path),
                path_specified=True,
                secure=secure,
                expires=expires,
                discard=(expires is None),
                comment=None,
                comment_url=None,
                rest=rest,
                rfc2109=False,
            )
            jar.set_cookie(cookie)
            count += 1
            names.append(str(name))
        except Exception as exc:
            log("JSON cookie import failed for {}: {}".format(name, exc), xbmc.LOGWARNING)

    return count, names

def oauth_cookie_login_file():
    path = xbmcgui.Dialog().browse(
        1,
        "Select FIA WEC+ cookie file",
        "files",
        ".json|.txt|.cookie|.cookies",
        False,
        False,
        ""
    )
    if not path:
        return

    try:
        vfs = xbmcvfs.File(path)
        try:
            raw = vfs.readBytes()
        finally:
            vfs.close()

        if isinstance(raw, str):
            text = raw
        else:
            raw = bytes(raw)
            if raw.startswith(b"\xef\xbb\xbf"):
                text = raw.decode("utf-8-sig")
            elif raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
                text = raw.decode("utf-16")
            else:
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("cp1252", "replace")

        text = (text or "").strip()
        if not text:
            xbmcgui.Dialog().ok(
                "FIA WEC+ Cookie Sign-in",
                "The selected file is empty."
            )
            return

        if "…" in text:
            xbmcgui.Dialog().ok(
                "FIA WEC+ Cookie Sign-in",
                "The cookie file contains a truncated cookie (…).\n\n"
                "Export the cookies completely and use the file again."
            )
            return

        # JSON exports from common browser cookie extensions.
        if text.startswith("[") or text.startswith("{"):
            try:
                probe_jar = http.cookiejar.CookieJar()
                imported, _ = _seed_cookiejar_from_json(probe_jar, text)
                if imported:
                    _oauth_cookie_login_with_value("", json_text=text)
                    return
            except Exception:
                pass

        # Netscape cookies.txt export.
        if "# Netscape HTTP Cookie File" in text or "\tTRUE\t/" in text or "\tFALSE\t/" in text:
            _oauth_cookie_login_with_value("", netscape_text=text)
            return

        # Raw Cookie request header.
        raw_cookie = text
        if raw_cookie.lower().startswith("cookie:"):
            raw_cookie = raw_cookie.split(":", 1)[1].strip()

        raw_cookie = " ".join(
            line.strip() for line in raw_cookie.splitlines() if line.strip()
        )

        if "=" not in raw_cookie:
            xbmcgui.Dialog().ok(
                "FIA WEC+ Cookie Sign-in",
                "No supported cookie format was detected.\n\n"
                "Supported formats are JSON export, Netscape cookies.txt "
                "or a complete Cookie header."
            )
            return

        _oauth_cookie_login_with_value(raw_cookie)

    except Exception as exc:
        log("Cookie file read failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            "FIA WEC+ Cookie Sign-in",
            "The cookie file could not be read:\n\n{}".format(exc)
        )

def oauth_cookie_login_manual():
    raw_cookie = xbmcgui.Dialog().input(
        "Paste Staylive/Auth0 cookie",
        defaultt="",
        type=xbmcgui.INPUT_ALPHANUM,
        option=xbmcgui.ALPHANUM_HIDE_INPUT
    )
    if not raw_cookie:
        return
    _oauth_cookie_login_with_value(raw_cookie)

def oauth_import_token_file():
    path = xbmcgui.Dialog().browse(
        1,
        "Select FIA WEC+ token file",
        "files",
        ".json|.txt",
        False,
        False,
        ""
    )
    if not path:
        return

    try:
        vfs = xbmcvfs.File(path)
        try:
            raw = vfs.readBytes()
        finally:
            vfs.close()

        if isinstance(raw, str):
            text = raw
        else:
            raw = bytes(raw)
            if raw.startswith(b"\xef\xbb\xbf"):
                text = raw.decode("utf-8-sig")
            elif raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
                text = raw.decode("utf-16")
            else:
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("cp1252", "replace")

        text = (text or "").strip()
        if not text:
            xbmcgui.Dialog().ok("FIA WEC+ Token Import", "The selected file is empty.")
            return

        # Accept either raw JSON or text where the JSON object was copied with
        # surrounding whitespace/log text. Prefer strict JSON first.
        try:
            data = json.loads(text)
        except Exception:
            first = text.find("{")
            last = text.rfind("}")
            if first >= 0 and last > first:
                data = json.loads(text[first:last + 1])
            else:
                raise ValueError("No JSON object was found in the file.")

        if not isinstance(data, dict):
            raise ValueError("The file does not contain a JSON object.")

        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        if not access_token or not refresh_token:
            xbmcgui.Dialog().ok(
                "FIA WEC+ Token Import",
                "The file must contain at least access_token and refresh_token."
            )
            return

        # Reuse the add-on's existing token storage logic, including expiry handling.
        _store_tokens(data)
        ADDON.setSetting("login_method", "token_import")

        xbmcgui.Dialog().notification(
            "FIA WEC+",
            "Token file imported successfully",
            xbmcgui.NOTIFICATION_INFO,
            4000
        )
        xbmc.executebuiltin("Container.Refresh")

    except Exception as exc:
        log("Token file import failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            "FIA WEC+ Token Import",
            "The token file could not be imported:\n\n{}".format(exc)
        )

def oauth_browser_refresh_import():
    """Official browser sign-in with one-time refresh-token handoff.

    Authentication (including any CAPTCHA) stays entirely in the official
    FIA WEC+/Staylive browser flow. Kodi only receives the resulting refresh
    token and immediately validates it by requesting a fresh access token.
    """
    login_url = "https://plus.fiawec.com/en/app/login"
    opened = False
    try:
        if sys.platform.startswith("win") and hasattr(os, "startfile"):
            os.startfile(login_url)
            opened = True
        else:
            opened = bool(webbrowser.open(login_url, new=2))
    except Exception as exc:
        log("Browser sign-in: primary browser open failed: {}".format(exc), xbmc.LOGWARNING)
        try:
            opened = bool(webbrowser.open(login_url, new=2))
        except Exception as exc2:
            log("Browser sign-in: fallback browser open failed: {}".format(exc2), xbmc.LOGWARNING)

    if not opened:
        xbmcgui.Dialog().ok(
            "FIA WEC+ Browser Sign-in",
            "Kodi could not open the browser automatically.\n\n"
            "Open this address in your browser:\n"
            "https://plus.fiawec.com/en/app/login"
        )

    xbmcgui.Dialog().ok(
        "FIA WEC+ Browser Sign-in",
        "Sign in on the official FIA WEC+ browser page. Complete a CAPTCHA if Staylive asks for one.\n\n"
        "After sign-in, open the browser Network tools, find the successful oauth/token request and copy ONLY the refresh_token value from its response.\n\n"
        "Return to Kodi and paste the refresh token in the next box."
    )

    token = xbmcgui.Dialog().input(
        "Paste refresh_token",
        defaultt="",
        type=xbmcgui.INPUT_ALPHANUM,
    ).strip()
    if not token:
        return

    # Refresh tokens observed from Staylive are opaque strings. Reject obvious
    # accidental pastes (entire JSON objects / URLs) before touching settings.
    if token.startswith("{") or token.startswith("http://") or token.startswith("https://") or "access_token" in token:
        xbmcgui.Dialog().ok(
            "FIA WEC+ Browser Sign-in",
            "Please paste ONLY the refresh_token value, not the complete JSON response or a URL."
        )
        return

    old_refresh = ADDON.getSetting("refresh_token")
    old_access = ADDON.getSetting("access_token")
    old_id = ADDON.getSetting("id_token")
    old_expiry = ADDON.getSetting("expires_at")

    try:
        ADDON.setSetting("refresh_token", token)
        ADDON.setSetting("access_token", "")
        ADDON.setSetting("id_token", "")
        ADDON.setSetting("expires_at", "")

        if not _refresh_access_token_silent():
            raise RuntimeError("Staylive rejected the refresh token")

        access = ADDON.getSetting("access_token")
        refresh = ADDON.getSetting("refresh_token")
        if not access or not refresh:
            raise RuntimeError("Token refresh did not produce a complete login session")

        ADDON.setSetting("login_method", "browser")
        xbmcgui.Dialog().notification(
            "FIA WEC+",
            "Browser sign-in imported successfully",
            xbmcgui.NOTIFICATION_INFO,
            5000,
        )
        xbmc.executebuiltin("Container.Refresh")
    except Exception as exc:
        # Restore any previously working login rather than leaving a bad token behind.
        ADDON.setSetting("refresh_token", old_refresh)
        ADDON.setSetting("access_token", old_access)
        ADDON.setSetting("id_token", old_id)
        ADDON.setSetting("expires_at", old_expiry)
        log("Browser sign-in token import failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            "FIA WEC+ Browser Sign-in",
            "The refresh token could not be validated:\n\n{}".format(exc)
        )

def _captcha_image_meta(raw, content_type=""):
    """Return (extension, mime, width, height) for common image types."""
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    width = height = 0
    ext = ""
    mime = ctype
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        ext, mime = ".png", "image/png"
        if len(raw) >= 24:
            width = int.from_bytes(raw[16:20], "big")
            height = int.from_bytes(raw[20:24], "big")
    elif raw[:3] == b"\xff\xd8\xff":
        ext, mime = ".jpg", "image/jpeg"
    elif raw[:6] in (b"GIF87a", b"GIF89a"):
        ext, mime = ".gif", "image/gif"
        if len(raw) >= 10:
            width = int.from_bytes(raw[6:8], "little")
            height = int.from_bytes(raw[8:10], "little")
    elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        ext, mime = ".webp", "image/webp"
    else:
        stripped = raw.lstrip()[:300].lower()
        if stripped.startswith(b"<svg") or b"<svg" in stripped:
            ext, mime = ".svg", "image/svg+xml"
    if not ext:
        ext = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/svg+xml": ".svg",
        }.get(ctype, "")
    return ext, mime, width, height

def _svg_num(value, default=0.0):
    """Parse the numeric part of a simple SVG length."""
    if value is None:
        return default
    m = re.search(r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?', str(value))
    try:
        return float(m.group(0)) if m else default
    except Exception:
        return default

def _svg_matrix_mul(a, b):
    """Return affine matrix a*b for SVG 2D matrices (a,b,c,d,e,f)."""
    a0,b0,c0,d0,e0,f0 = a
    a1,b1,c1,d1,e1,f1 = b
    return (
        a0*a1 + c0*b1,
        b0*a1 + d0*b1,
        a0*c1 + c0*d1,
        b0*c1 + d0*d1,
        a0*e1 + c0*f1 + e0,
        b0*e1 + d0*f1 + f0,
    )

def _svg_transform_matrix(text):
    """Parse the common SVG transform functions into one affine matrix."""
    out = (1.0,0.0,0.0,1.0,0.0,0.0)
    if not text:
        return out
    for name, raw in re.findall(r'([A-Za-z]+)\s*\(([^)]*)\)', text):
        vals = []
        for token in re.findall(r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?', raw):
            try: vals.append(float(token))
            except Exception: pass
        name = name.lower()
        m = (1.0,0.0,0.0,1.0,0.0,0.0)
        if name == 'matrix' and len(vals) >= 6:
            m = tuple(vals[:6])
        elif name == 'translate' and vals:
            m = (1.0,0.0,0.0,1.0,vals[0],vals[1] if len(vals)>1 else 0.0)
        elif name == 'scale' and vals:
            m = (vals[0],0.0,0.0,vals[1] if len(vals)>1 else vals[0],0.0,0.0)
        elif name == 'rotate' and vals:
            ang = math.radians(vals[0]); c=math.cos(ang); sn=math.sin(ang)
            r=(c,sn,-sn,c,0.0,0.0)
            if len(vals)>=3:
                cx,cy=vals[1],vals[2]
                m=_svg_matrix_mul((1,0,0,1,cx,cy), _svg_matrix_mul(r,(1,0,0,1,-cx,-cy)))
            else:
                m=r
        elif name == 'skewx' and vals:
            m=(1.0,0.0,math.tan(math.radians(vals[0])),1.0,0.0,0.0)
        elif name == 'skewy' and vals:
            m=(1.0,math.tan(math.radians(vals[0])),0.0,1.0,0.0,0.0)
        out = _svg_matrix_mul(out, m)
    return out

def _svg_apply(m, pt):
    x,y=pt; a,b,c,d,e,f=m
    return (a*x+c*y+e, b*x+d*y+f)

def _svg_arc_points(p0, rx, ry, phi_deg, large_arc, sweep, p1, steps=16):
    """Approximate an SVG elliptical arc with points (SVG 1.1 endpoint form)."""
    x1,y1=p0; x2,y2=p1
    rx,ry=abs(rx),abs(ry)
    if rx < 1e-9 or ry < 1e-9 or (abs(x1-x2)<1e-9 and abs(y1-y2)<1e-9):
        return [p1]
    phi=math.radians(phi_deg % 360.0); cp=math.cos(phi); sp=math.sin(phi)
    dx=(x1-x2)/2.0; dy=(y1-y2)/2.0
    xp=cp*dx + sp*dy; yp=-sp*dx + cp*dy
    lam=(xp*xp)/(rx*rx)+(yp*yp)/(ry*ry)
    if lam>1:
        scale=math.sqrt(lam); rx*=scale; ry*=scale
    num=max(0.0, (rx*rx*ry*ry-rx*rx*yp*yp-ry*ry*xp*xp))
    den=max(1e-20, rx*rx*yp*yp+ry*ry*xp*xp)
    coef=math.sqrt(num/den)
    if bool(large_arc)==bool(sweep): coef=-coef
    cxp=coef*(rx*yp/ry); cyp=coef*(-ry*xp/rx)
    cx=cp*cxp-sp*cyp+(x1+x2)/2.0
    cy=sp*cxp+cp*cyp+(y1+y2)/2.0
    def vang(ux,uy,vx,vy):
        dot=ux*vx+uy*vy; den2=max(1e-20,math.hypot(ux,uy)*math.hypot(vx,vy))
        ang=math.acos(max(-1.0,min(1.0,dot/den2)))
        if ux*vy-uy*vx<0: ang=-ang
        return ang
    ux=(xp-cxp)/rx; uy=(yp-cyp)/ry
    vx=(-xp-cxp)/rx; vy=(-yp-cyp)/ry
    th1=vang(1,0,ux,uy); dth=vang(ux,uy,vx,vy)
    if not sweep and dth>0: dth-=2*math.pi
    if sweep and dth<0: dth+=2*math.pi
    n=max(4,int(abs(dth)/(2*math.pi)*steps)+1)
    out=[]
    for i in range(1,n+1):
        th=th1+dth*(i/n)
        ct,st=math.cos(th),math.sin(th)
        x=cx+cp*rx*ct-sp*ry*st; y=cy+sp*rx*ct+cp*ry*st
        out.append((x,y))
    return out

def _svg_path_subpaths(d):
    """Flatten an SVG path into polylines; supports all common path commands."""
    toks=re.findall(r'[AaCcHhLlMmQqSsTtVvZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?', d or '')
    i=0; cmd=None; cur=(0.0,0.0); start=(0.0,0.0); sub=[]; paths=[]
    last_c=None; last_q=None
    def num():
        nonlocal i
        v=float(toks[i]); i+=1; return v
    def add(pt):
        nonlocal cur,sub
        cur=pt
        if not sub: sub=[pt]
        elif abs(sub[-1][0]-pt[0])>1e-9 or abs(sub[-1][1]-pt[1])>1e-9: sub.append(pt)
    while i<len(toks):
        if re.match(r'^[A-Za-z]$', toks[i]): cmd=toks[i]; i+=1
        if not cmd: break
        rel=cmd.islower(); c=cmd.upper()
        try:
            if c=='M':
                x,y=num(),num(); pt=(x+(cur[0] if rel else 0),y+(cur[1] if rel else 0))
                if sub: paths.append((sub,False))
                sub=[]; add(pt); start=pt; last_c=last_q=None
                cmd='l' if rel else 'L'
            elif c=='L':
                x,y=num(),num(); add((x+(cur[0] if rel else 0),y+(cur[1] if rel else 0))); last_c=last_q=None
            elif c=='H':
                x=num(); add((x+(cur[0] if rel else 0),cur[1])); last_c=last_q=None
            elif c=='V':
                y=num(); add((cur[0],y+(cur[1] if rel else 0))); last_c=last_q=None
            elif c=='C':
                x1,y1,x2,y2,x,y=[num() for _ in range(6)]
                p0=cur; p1=(x1+(p0[0] if rel else 0),y1+(p0[1] if rel else 0)); p2=(x2+(p0[0] if rel else 0),y2+(p0[1] if rel else 0)); p3=(x+(p0[0] if rel else 0),y+(p0[1] if rel else 0))
                for k in range(1,13):
                    t=k/12.0; u=1-t
                    add((u*u*u*p0[0]+3*u*u*t*p1[0]+3*u*t*t*p2[0]+t*t*t*p3[0], u*u*u*p0[1]+3*u*u*t*p1[1]+3*u*t*t*p2[1]+t*t*t*p3[1]))
                last_c=p2; last_q=None
            elif c=='S':
                x2,y2,x,y=[num() for _ in range(4)]; p0=cur
                p1=(2*p0[0]-last_c[0],2*p0[1]-last_c[1]) if last_c is not None else p0
                p2=(x2+(p0[0] if rel else 0),y2+(p0[1] if rel else 0)); p3=(x+(p0[0] if rel else 0),y+(p0[1] if rel else 0))
                for k in range(1,13):
                    t=k/12.0; u=1-t
                    add((u*u*u*p0[0]+3*u*u*t*p1[0]+3*u*t*t*p2[0]+t*t*t*p3[0], u*u*u*p0[1]+3*u*u*t*p1[1]+3*u*t*t*p2[1]+t*t*t*p3[1]))
                last_c=p2; last_q=None
            elif c=='Q':
                x1,y1,x,y=[num() for _ in range(4)]; p0=cur
                p1=(x1+(p0[0] if rel else 0),y1+(p0[1] if rel else 0)); p2=(x+(p0[0] if rel else 0),y+(p0[1] if rel else 0))
                for k in range(1,11):
                    t=k/10.0; u=1-t
                    add((u*u*p0[0]+2*u*t*p1[0]+t*t*p2[0],u*u*p0[1]+2*u*t*p1[1]+t*t*p2[1]))
                last_q=p1; last_c=None
            elif c=='T':
                x,y=num(),num(); p0=cur; p1=(2*p0[0]-last_q[0],2*p0[1]-last_q[1]) if last_q is not None else p0; p2=(x+(p0[0] if rel else 0),y+(p0[1] if rel else 0))
                for k in range(1,11):
                    t=k/10.0; u=1-t; add((u*u*p0[0]+2*u*t*p1[0]+t*t*p2[0],u*u*p0[1]+2*u*t*p1[1]+t*t*p2[1]))
                last_q=p1; last_c=None
            elif c=='A':
                rx,ry,phi,laf,sf,x,y=[num() for _ in range(7)]; p0=cur; p1=(x+(p0[0] if rel else 0),y+(p0[1] if rel else 0))
                for pt in _svg_arc_points(p0,rx,ry,phi,int(laf)!=0,int(sf)!=0,p1,24): add(pt)
                last_c=last_q=None
            elif c=='Z':
                if sub:
                    if abs(cur[0]-start[0])>1e-9 or abs(cur[1]-start[1])>1e-9: sub.append(start)
                    paths.append((sub,True)); sub=[]
                cur=start; last_c=last_q=None; cmd=None
            else:
                break
        except (ValueError,IndexError):
            break
    if sub: paths.append((sub,False))
    return paths

def _svg_style(el):
    st={}
    for piece in (el.attrib.get('style') or '').split(';'):
        if ':' in piece:
            k,v=piece.split(':',1); st[k.strip().lower()]=v.strip()
    for k in ('fill','stroke','stroke-width','fill-rule','opacity','fill-opacity','stroke-opacity'):
        if k in el.attrib: st[k]=el.attrib[k]
    return st

def _svg_put_px(buf,w,h,x,y,gray=0):
    if 0<=x<w and 0<=y<h:
        idx=(y*w+x)*4
        # White background, dark challenge graphics. Keep the darkest sample.
        v=max(0,min(255,int(gray)))
        if v < buf[idx]:
            buf[idx]=buf[idx+1]=buf[idx+2]=v; buf[idx+3]=255

def _svg_line(buf,w,h,p0,p1,width=2,gray=0):
    x0,y0=p0; x1,y1=p1; dx=x1-x0; dy=y1-y0
    steps=max(1,int(max(abs(dx),abs(dy))*1.5)); rad=max(0,int(width/2))
    for i in range(steps+1):
        t=i/steps; x=int(round(x0+dx*t)); y=int(round(y0+dy*t))
        for yy in range(y-rad,y+rad+1):
            for xx in range(x-rad,x+rad+1):
                if (xx-x)*(xx-x)+(yy-y)*(yy-y) <= (rad+0.7)*(rad+0.7):
                    _svg_put_px(buf,w,h,xx,yy,gray)

def _svg_fill_evenodd(buf,w,h,polys,gray=0):
    if not polys: return
    miny=max(0,int(math.floor(min(p[1] for poly in polys for p in poly))))
    maxy=min(h-1,int(math.ceil(max(p[1] for poly in polys for p in poly))))
    for y in range(miny,maxy+1):
        sy=y+0.5; xs=[]
        for poly in polys:
            if len(poly)<3: continue
            pts=poly if poly[0]==poly[-1] else poly+[poly[0]]
            for p0,p1 in zip(pts,pts[1:]):
                x0,y0=p0; x1,y1=p1
                if (y0<=sy<y1) or (y1<=sy<y0):
                    if abs(y1-y0)>1e-12: xs.append(x0+(sy-y0)*(x1-x0)/(y1-y0))
        xs.sort()
        for j in range(0,len(xs)-1,2):
            a=max(0,int(math.ceil(xs[j]))); b=min(w-1,int(math.floor(xs[j+1])))
            if b>=a:
                off=(y*w+a)*4
                for x in range(a,b+1):
                    idx=off+(x-a)*4
                    if gray < buf[idx]:
                        buf[idx]=buf[idx+1]=buf[idx+2]=gray; buf[idx+3]=255

def _write_rgba_png(path,w,h,buf):
    raw=bytearray()
    stride=w*4
    for y in range(h):
        raw.append(0); raw.extend(buf[y*stride:(y+1)*stride])
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(bytes(raw),9))+chunk(b'IEND',b'')
    with open(path,'wb') as fh: fh.write(png)

def _svg_to_png_pure(svg_bytes, out_path):
    """Rasterize the CAPTCHA SVG with stdlib only for Kodi/Android TV.

    This is deliberately a renderer, not a CAPTCHA solver: it reproduces the
    vector challenge so the user can read and enter it manually.
    """
    try:
        root=ET.fromstring(svg_bytes.decode('utf-8','replace'))
    except Exception:
        return False
    vb=root.attrib.get('viewBox') or root.attrib.get('viewbox')
    if vb:
        vals=[_svg_num(v) for v in re.split(r'[ ,]+',vb.strip()) if v]
        if len(vals)>=4: vx,vy,vw,vh=vals[:4]
        else: vx=vy=0; vw=_svg_num(root.attrib.get('width'),300); vh=_svg_num(root.attrib.get('height'),100)
    else:
        vx=vy=0; vw=_svg_num(root.attrib.get('width'),300); vh=_svg_num(root.attrib.get('height'),100)
    if vw<=0: vw=300
    if vh<=0: vh=100
    # Large enough to be readable on TV, but still cheap for pure Python.
    out_w=1000; out_h=max(220,min(420,int(round(out_w*vh/vw))))
    margin=24.0
    scale=min((out_w-2*margin)/vw,(out_h-2*margin)/vh)
    base=(scale,0,0,scale,margin-vx*scale,margin-vy*scale)
    buf=bytearray([255])*(out_w*out_h*4)
    for i in range(3,len(buf),4): buf[i]=255

    def render(el,parent_m):
        local=_svg_matrix_mul(parent_m,_svg_transform_matrix(el.attrib.get('transform')))
        tag=el.tag.split('}')[-1].lower(); st=_svg_style(el)
        fill=(st.get('fill') or ('none' if tag in ('line','polyline') else 'black')).lower()
        stroke=(st.get('stroke') or ('black' if tag in ('line','polyline') else 'none')).lower()
        sw=max(1.0,_svg_num(st.get('stroke-width'),1.3)*scale)
        paths=[]
        if tag=='path':
            paths=_svg_path_subpaths(el.attrib.get('d',''))
        elif tag in ('polygon','polyline'):
            nums=[_svg_num(x) for x in re.findall(r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?',el.attrib.get('points',''))]
            pts=list(zip(nums[0::2],nums[1::2])); paths=[(pts,tag=='polygon')]
        elif tag=='line':
            paths=[([(_svg_num(el.attrib.get('x1')),_svg_num(el.attrib.get('y1'))),(_svg_num(el.attrib.get('x2')),_svg_num(el.attrib.get('y2')))],False)]
        elif tag=='rect':
            x=_svg_num(el.attrib.get('x')); y=_svg_num(el.attrib.get('y')); ww=_svg_num(el.attrib.get('width')); hh=_svg_num(el.attrib.get('height'))
            paths=[([(x,y),(x+ww,y),(x+ww,y+hh),(x,y+hh),(x,y)],True)]
        elif tag=='circle':
            cx=_svg_num(el.attrib.get('cx')); cy=_svg_num(el.attrib.get('cy')); r=_svg_num(el.attrib.get('r')); pts=[(cx+math.cos(2*math.pi*k/48)*r,cy+math.sin(2*math.pi*k/48)*r) for k in range(49)]; paths=[(pts,True)]
        elif tag=='ellipse':
            cx=_svg_num(el.attrib.get('cx')); cy=_svg_num(el.attrib.get('cy')); rx=_svg_num(el.attrib.get('rx')); ry=_svg_num(el.attrib.get('ry')); pts=[(cx+math.cos(2*math.pi*k/48)*rx,cy+math.sin(2*math.pi*k/48)*ry) for k in range(49)]; paths=[(pts,True)]
        if paths:
            tpaths=[]
            for pts,closed in paths:
                tp=[_svg_apply(_svg_matrix_mul(base,local),p) for p in pts]
                tpaths.append((tp,closed))
            if fill not in ('none','transparent'):
                closed_polys=[p for p,c in tpaths if c and len(p)>=3]
                _svg_fill_evenodd(buf,out_w,out_h,closed_polys,0)
            if stroke not in ('none','transparent'):
                for pts,closed in tpaths:
                    q=pts+([pts[0]] if closed and pts and pts[-1]!=pts[0] else [])
                    for a,b in zip(q,q[1:]): _svg_line(buf,out_w,out_h,a,b,sw,0)
        for child in list(el): render(child,local)
    render(root,(1,0,0,1,0,0))
    try:
        _write_rgba_png(out_path,out_w,out_h,buf)
        return os.path.exists(out_path) and os.path.getsize(out_path)>100
    except Exception:
        return False

def _decode_json_string_token(token):
    """Decode a JSON-style quoted string token without interpreting CAPTCHA contents."""
    try:
        return json.loads(token)
    except Exception:
        return html.unescape(token.strip('"\''))

def _captcha_sources_from_html(body):
    """Return likely CAPTCHA image sources from Auth0 Universal Login HTML.

    Auth0 can expose the visual challenge either as a rendered <img> or in the
    Universal Login screen context as captchaImage / captcha.image. We only
    render the challenge for the user; we never attempt to solve it.
    """
    if not body:
        return []

    sources = []
    seen = set()

    def add(src, score):
        if not src:
            return
        src = html.unescape(src.strip())
        # Undo the most common JSON/JS escaping used in embedded screen state.
        src = src.replace('\\u002F', '/').replace('\\/', '/')
        if src not in seen:
            seen.add(src)
            sources.append((score, src))

    # 1) Auth0 ACUL / Universal Login screen context.
    # Example: "captchaImage":"data:image/..."
    for pat, score in (
        (r'"captchaImage"\s*:\s*("(?:\\.|[^"\\])*")', 1000),
        (r'"captcha_image"\s*:\s*("(?:\\.|[^"\\])*")', 950),
    ):
        for m in re.finditer(pat, body, re.I | re.S):
            add(_decode_json_string_token(m.group(1)), score)

    # Auth0 also exposes screen.captcha.image.
    for m in re.finditer(
        r'"captcha"\s*:\s*\{.{0,2000}?"image"\s*:\s*("(?:\\.|[^"\\])*")',
        body, re.I | re.S
    ):
        add(_decode_json_string_token(m.group(1)), 980)

    # 2) Explicit CAPTCHA <img> tags, independent of attribute order.
    for tag in re.findall(r'<img\b[^>]*>', body, re.I | re.S):
        low = tag.lower()
        if not any(k in low for k in ('captcha', 'challenge', 'verification', 'security')):
            continue
        m = re.search(r'\bsrc=["\']([^"\']+)["\']', tag, re.I | re.S)
        if m:
            add(m.group(1), 900)

    # 3) Any data:image close to the visible CAPTCHA prompt/input.
    positions = []
    for pat in (r'name=["\']captcha["\']', r'id=["\']captcha["\']', r'enter the code shown above'):
        positions.extend(m.start() for m in re.finditer(pat, body, re.I))
    for pos in positions:
        region = body[max(0, pos - 12000):min(len(body), pos + 4000)]
        for m in re.finditer(r'(data:image/[a-zA-Z0-9.+-]+(?:;[^,]*)?,[^"\'\s<]+)', region, re.I):
            add(m.group(1), 850)
        for m in re.finditer(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>', region, re.I | re.S):
            src = m.group(1)
            low = m.group(0).lower()
            score = 800 if any(k in low for k in ('captcha', 'challenge')) else 500
            add(src, score)

    # 4) CSS background URL around the challenge.
    for pos in positions:
        region = body[max(0, pos - 12000):min(len(body), pos + 4000)]
        for src in re.findall(r'url\(["\']?([^\)"\']+)["\']?\)', region, re.I):
            if 'captcha' in src.lower() or src.startswith('data:image/'):
                add(src, 700)

    sources.sort(key=lambda item: item[0], reverse=True)
    return sources

def _captcha_image_from_html(body, base_url, opener):
    """Extract and save the visual Auth0 CAPTCHA challenge for manual solving."""
    candidates = _captcha_sources_from_html(body)
    if not candidates:
        log('No CAPTCHA image source found in Auth0 HTML', xbmc.LOGWARNING)
        return ''

    profile_dir = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    try:
        os.makedirs(profile_dir, exist_ok=True)
    except Exception:
        pass

    for score, src in candidates:
        try:
            content_type = ''
            if src.startswith('data:image/'):
                header, payload = src.split(',', 1)
                content_type = header[5:].split(';', 1)[0]
                if ';base64' in header.lower():
                    raw = base64.b64decode(re.sub(r'\s+', '', payload))
                else:
                    raw = urllib.parse.unquote_to_bytes(payload)
            else:
                url = urllib.parse.urljoin(base_url, src)
                req = urllib.request.Request(
                    url,
                    headers={
                        'User-Agent': USER_AGENT,
                        'Referer': base_url,
                        'Accept': 'image/avif,image/webp,image/png,image/svg+xml,image/*,*/*;q=0.8',
                    },
                )
                resp = opener.open(req, timeout=30)
                content_type = resp.headers.get('Content-Type', '')
                raw = resp.read()

            ext, mime, width, height = _captcha_image_meta(raw, content_type)
            if not raw or not ext:
                log('CAPTCHA source was not a supported image (score {}, type {}, {} bytes)'.format(
                    score, content_type, len(raw) if raw else 0), xbmc.LOGDEBUG)
                continue
            if width and height and (width < 80 or height < 25):
                log('Ignoring tiny CAPTCHA image candidate {}x{}'.format(width, height), xbmc.LOGDEBUG)
                continue

            for old_ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'):
                old_path = os.path.join(profile_dir, 'fiawec_captcha' + old_ext)
                try:
                    if os.path.exists(old_path):
                        os.remove(old_path)
                except Exception:
                    pass

            out_path = os.path.join(profile_dir, 'fiawec_captcha' + ext)
            with open(out_path, 'wb') as fh:
                fh.write(raw)

            # Kodi's image control does not reliably render arbitrary SVG files
            # (confirmed on Windows and relevant to Android TV). Rasterize the
            # vector challenge locally to PNG with a small stdlib-only renderer.
            # This only displays the challenge; the user still solves it manually.
            if ext == '.svg':
                png_path = os.path.join(profile_dir, 'fiawec_captcha.png')
                try:
                    if os.path.exists(png_path):
                        os.remove(png_path)
                except Exception:
                    pass
                if _svg_to_png_pure(raw, png_path):
                    log('CAPTCHA SVG rasterized to PNG for Kodi: {}'.format(png_path), xbmc.LOGINFO)
                    return png_path
                log('CAPTCHA SVG rasterization failed', xbmc.LOGWARNING)

            log('CAPTCHA image saved: {} ({} bytes, {}, {}x{}, score {})'.format(
                out_path, len(raw), mime or content_type, width or '?', height or '?', score), xbmc.LOGINFO)
            return out_path
        except Exception as exc:
            log('CAPTCHA image source failed: {}'.format(exc), xbmc.LOGDEBUG)
    return ''

class _CaptchaDialog(xbmcgui.WindowDialog):
    """Programmatic modal CAPTCHA dialog.

     keeps the working programmatic dialog approach but shows the CAPTCHA smaller and centered for better readability on Android TV. The
    image control is created with the final local file path before the dialog
    is shown, which is more reliable across Windows and Android TV.
    """
    def __init__(self, image_path):
        super().__init__()
        self.image_path = (xbmcvfs.translatePath(image_path) or image_path).replace('\\', '/')
        self.ext = os.path.splitext(self.image_path)[1].lower() or 'unknown'

        self.title = xbmcgui.ControlLabel(
            140, 90, 1400, 70,
            'Staylive CAPTCHA — memorize the code  [{}]'.format(self.ext),
            font='font30', textColor='0xFFFFFFFF', alignment=0x00000002
        )
        # Deliberately smaller than before: centered and roughly half the previous
        # size so the challenge remains readable without overwhelming the TV UI.
        self.image = xbmcgui.ControlImage(
            515, 220, 650, 300, self.image_path,
            aspectRatio=2
        )
        self.button = xbmcgui.ControlButton(
            540, 590, 600, 80,
            'I have memorized the code'
        )
        self.addControl(self.title)
        self.addControl(self.image)
        self.addControl(self.button)
        try:
            self.image.setImage(self.image_path, False)
        except Exception as exc:
            log('Could not set CAPTCHA image in : {}'.format(exc), xbmc.LOGERROR)
        try:
            self.setFocus(self.button)
        except Exception:
            pass

    def onControl(self, control):
        if control == self.button:
            self.close()

    def onClick(self, control_id):
        try:
            if control_id == self.button.getId():
                self.close()
        except Exception:
            pass

    def onAction(self, action):
        try:
            aid = action.getId()
        except Exception:
            aid = -1
        if aid in (9, 10, 92, 216):
            self.close()

def _show_captcha_window(image_path):
    """Show the CAPTCHA using a programmatic Kodi image control."""
    dlg = _CaptchaDialog(image_path)
    try:
        dlg.doModal()
    finally:
        try:
            dlg.close()
        except Exception:
            pass
        del dlg

def _native_follow_oauth_redirects(current_url, no_redirect_opener, login_url, common_headers, oauth_state, verifier):
    """Follow Auth0 resume redirects until the FIA WEC+ authorization code appears."""
    for _ in range(10):
        parsed = urllib.parse.urlparse(current_url)
        q = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        code = (q.get("code") or [""])[0]
        returned_state = (q.get("state") or [""])[0]
        error = (q.get("error") or [""])[0]
        error_desc = (q.get("error_description") or [""])[0]

        if error:
            raise RuntimeError("{}{}".format(error, (": " + error_desc) if error_desc else ""))
        if code:
            if not returned_state or not secrets.compare_digest(returned_state, oauth_state):
                raise RuntimeError("OAuth state mismatch")
            data = _oauth_post({
                "client_id": OAUTH_CLIENT_ID,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OAUTH_REDIRECT_URI,
            })
            if not data.get("access_token"):
                raise RuntimeError("Staylive returned no access token")
            _store_tokens(data)
            return True

        req = urllib.request.Request(
            current_url,
            headers=dict(common_headers, **{
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": login_url,
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Upgrade-Insecure-Requests": "1",
            })
        )
        try:
            resp = no_redirect_opener.open(req, timeout=30)
            loc = resp.headers.get("Location", "")
            resp.read()
            if loc:
                current_url = urllib.parse.urljoin(current_url, loc)
                continue
            current_url = resp.geturl()
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                loc = exc.headers.get("Location", "")
                if loc:
                    current_url = urllib.parse.urljoin(current_url, loc)
                    continue
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError("HTTP {} during OAuth resume: {}".format(exc.code, re.sub(r"\\s+", " ", re.sub(r"<[^>]+>", " ", detail))[:250]))
    raise RuntimeError("The OAuth redirect chain ended without an authorization code")

def oauth_direct_login():
    """Native email/password sign-in prototype for Kodi / Android TV.

    This reproduces the observed FIA WEC+/Staylive Auth0 transaction with a
    cookie jar. If Staylive requests a CAPTCHA, Kodi displays the image and the
    user solves it manually. CAPTCHA solving is never automated.
    """
    username = xbmcgui.Dialog().input(
        "FIA WEC+ email",
        defaultt="",
        type=xbmcgui.INPUT_ALPHANUM,
    ).strip()
    if not username:
        return

    password = xbmcgui.Dialog().input(
        "FIA WEC+ password",
        defaultt="",
        type=xbmcgui.INPUT_ALPHANUM,
        option=xbmcgui.ALPHANUM_HIDE_INPUT,
    )
    if not password:
        return

    verifier, challenge = _pkce_pair()
    # Match the web client's padded URL-safe state/nonce style.
    oauth_state = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    nonce = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")

    params = {
        "client_id": OAUTH_CLIENT_ID,
        "scope": OAUTH_SCOPE,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "audience": OAUTH_AUDIENCE,
        "organization": OAUTH_ORGANIZATION,
        "prompt": "login",
        "login_hint": username,
        "response_type": "code",
        "response_mode": "query",
        "state": oauth_state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "auth0Client": AUTH0_CLIENT_INFO,
    }
    authorize_url = OAUTH_AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    no_redirect_opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), _NoRedirect()
    )
    auth_browser_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) "
        "Gecko/20100101 Firefox/155.0"
    )
    common_headers = {
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "User-Agent": auth_browser_ua,
    }

    try:
        # Seed the same FIA WEC+ site context used by the official login page.
        try:
            seed = urllib.request.Request(
                "https://plus.fiawec.com/en/app/login",
                headers={"User-Agent": auth_browser_ua, "Accept": "text/html,*/*"},
            )
            r = opener.open(seed, timeout=30)
            r.read()
        except Exception as exc:
            log("FIA WEC+ native sign-in seed request failed: {}".format(exc), xbmc.LOGDEBUG)

        # Start the exact observed Auth0 Authorization Code + PKCE transaction.
        req = urllib.request.Request(
            authorize_url,
            headers=dict(common_headers, **{
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://plus.fiawec.com/",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-site",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            })
        )
        resp = opener.open(req, timeout=30)
        login_url = resp.geturl()
        login_html = resp.read().decode("utf-8", "replace")
        parsed_login = urllib.parse.urlparse(login_url)
        login_q = urllib.parse.parse_qs(parsed_login.query)
        transaction_state = (login_q.get("state") or [""])[0]
        if not transaction_state or "/u/login" not in parsed_login.path:
            raise RuntimeError("Staylive did not start the expected /u/login transaction")

        def submit(extra=None):
            fields = {
                "state": transaction_state,
                "username": username,
                "password": password,
            }
            if extra:
                fields.update(extra)
            form = urllib.parse.urlencode(fields).encode("utf-8")
            post_req = urllib.request.Request(
                login_url,
                data=form,
                headers=dict(common_headers, **{
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://auth.staylive.io",
                    "Referer": login_url,
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "same-origin",
                    "Sec-Fetch-User": "?1",
                    "Upgrade-Insecure-Requests": "1",
                }),
                method="POST",
            )
            try:
                r = no_redirect_opener.open(post_req, timeout=30)
                return getattr(r, "status", 200), r.headers.get("Location", ""), r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                return exc.code, exc.headers.get("Location", ""), body

        status, location, body = submit()

        # Staylive may enable CAPTCHA after failed/repeated sign-in attempts.
        # Important: the Auth0 HTML/JS contains the word "captcha" even when no
        # CAPTCHA is actually rendered. Only treat it as a challenge when the
        # returned form contains a real CAPTCHA input (or the visible prompt).
        captcha_required = False
        if status == 400:
            low_body = (body or "").lower()
            captcha_required = bool(
                re.search(r'<input[^>]+name=["\']captcha["\']', body or "", re.I)
                or re.search(r'<input[^>]+id=["\']captcha["\']', body or "", re.I)
                or ("enter the code shown above" in low_body)
            )

        if status == 400 and captcha_required:
            captcha_path = _captcha_image_from_html(body, login_url, opener)
            if captcha_path:
                xbmcgui.Dialog().ok(
                    "FIA WEC+ CAPTCHA",
                    "Staylive requires a CAPTCHA.\n\n"
                    "The CAPTCHA image will now be shown in a Kodi window for 20 seconds. "
                    "Please memorize the code. Afterwards Kodi will open the input box."
                )
                _show_captcha_window(captcha_path)
            else:
                xbmcgui.Dialog().ok(
                    "FIA WEC+ CAPTCHA",
                    "Staylive requires a CAPTCHA, but this test could not extract the CAPTCHA image from the login page."
                )
                return

            captcha = xbmcgui.Dialog().input(
                "Enter CAPTCHA code",
                defaultt="",
                type=xbmcgui.INPUT_ALPHANUM,
            ).strip()
            if not captcha:
                return
            status, location, body = submit({"captcha": captcha})

        if status in (301, 302, 303, 307, 308) and location:
            current_url = urllib.parse.urljoin(login_url, location)
            _native_follow_oauth_redirects(
                current_url, no_redirect_opener, login_url, common_headers, oauth_state, verifier
            )
            ADDON.setSetting("login_method", "email_password")
            xbmcgui.Dialog().notification(
                "FIA WEC+", "Email/password sign-in successful", xbmcgui.NOTIFICATION_INFO, 5000
            )
            xbmc.executebuiltin("Container.Refresh")
            return

        # A 400 with a rendered login page normally means Staylive rejected the
        # credentials or the CAPTCHA. Do not expose form values in logs/dialogs.
        text = re.sub(r"\\s+", " ", re.sub(r"<[^>]+>", " ", body or "")).strip()
        if "wrong email or password" in text.lower():
            msg = (
                "Staylive did not accept the email/password for this native login transaction.\n\n"
                "No actual CAPTCHA field was present in the returned form."
            )
        elif captcha_required:
            msg = "Staylive did not accept the CAPTCHA code."
        else:
            msg = "Staylive returned HTTP {} instead of the expected login redirect.".format(status)
        xbmcgui.Dialog().ok("FIA WEC+ Email/Password", msg)

    except Exception as exc:
        log("Native email/password login failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            "FIA WEC+ Email/Password",
            "Native sign-in failed:\n\n{}".format(exc),
        )
    finally:
        password = None

def _refresh_access_token_silent():
    refresh_token = ADDON.getSetting("refresh_token")
    if not refresh_token:
        return False

    try:
        data = _oauth_post({
            "client_id": OAUTH_CLIENT_ID,
            "prompt": "select_account",
            "redirect_uri": OAUTH_REDIRECT_URI,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })
        if not data.get("access_token"):
            return False

        # Auth0/Staylive may rotate refresh tokens. _store_tokens() already
        # stores a newly returned refresh_token. If the response omits one,
        # it deliberately keeps the current token.
        returned_refresh = data.get("refresh_token") or ""
        rotated = bool(returned_refresh and returned_refresh != refresh_token)
        _store_tokens(data)

        if rotated:
            log("OAuth refresh successful; rotated refresh token stored.", xbmc.LOGINFO)
        else:
            log("OAuth refresh successful; refresh token unchanged/not returned.", xbmc.LOGINFO)
        return True
    except Exception as exc:
        log("Silent OAuth refresh failed: {}".format(exc), xbmc.LOGERROR)
        return False

def _ensure_access_token():
    access_token = ADDON.getSetting("access_token")
    refresh_token = ADDON.getSetting("refresh_token")
    expires_at = ADDON.getSetting("expires_at")

    # Refresh five minutes before expiry.
    needs_refresh = not access_token
    if expires_at:
        try:
            needs_refresh = needs_refresh or (int(expires_at) - int(time.time()) <= 300)
        except Exception:
            pass

    if needs_refresh and refresh_token:
        if _refresh_access_token_silent():
            access_token = ADDON.getSetting("access_token")

    return access_token

def oauth_refresh():
    if _refresh_access_token_silent():
        xbmcgui.Dialog().notification(
            "FIA WEC+",
            "Access token refreshed successfully",
            xbmcgui.NOTIFICATION_INFO,
            4000,
        )
    else:
        xbmcgui.Dialog().ok(
            "FIA WEC+ Login",
            "Token refresh failed. Please sign in again."
        )

def oauth_refresh_test():
    refresh_token = ADDON.getSetting("refresh_token")
    if not refresh_token:
        xbmcgui.Dialog().ok(
            "FIA WEC+ Token Test",
            "No refresh token is available."
        )
        return

    try:
        old_access = ADDON.getSetting("access_token")
        if not _refresh_access_token_silent():
            xbmcgui.Dialog().ok(
                "FIA WEC+ Token Test",
                "Token refresh failed."
            )
            return

        new_access = ADDON.getSetting("access_token")
        try:
            expires_at = int(ADDON.getSetting("expires_at") or "0")
        except Exception:
            expires_at = 0
        remaining = max(0, int((expires_at - time.time()) / 60)) if expires_at else 0

        changed = bool(new_access and new_access != old_access)
        xbmcgui.Dialog().ok(
            "FIA WEC+ Token Test",
            "Refresh successful.\n\n"
            "New access token: {}\n"
            "Valid for about {} minutes\n"
            "Automatic renewal: active".format(
                "received" if new_access else "not available",
                remaining
            )
        )
        xbmc.executebuiltin("Container.Refresh")
    except Exception as exc:
        log("Refresh test failed: {}".format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            "FIA WEC+ Token Test",
            "Token refresh failed:\n\n{}".format(exc)
        )


def _account_access_status(request_json, api_headers):
    """Return FREE/PAY from Staylive's platform user entitlement response."""
    logged_in = bool(ADDON.getSetting("refresh_token") or ADDON.getSetting("access_token"))
    if not logged_in:
        return "NOT SIGNED IN"
    try:
        url = "https://api.staylive.tv/user?platform_uid={}".format(
            urllib.parse.quote(PLATFORM_UID, safe="")
        )
        user = _message(request_json(url, headers=api_headers()))
        if not isinstance(user, dict):
            return "UNKNOWN"
        subscriptions = user.get("subscriptions") or []
        external = user.get("external_subscriptions") or []
        packages = user.get("packages") or []
        return "PAY" if (subscriptions or external or packages) else "FREE"
    except Exception as exc:
        log("Account access status failed: {}".format(exc), xbmc.LOGWARNING)
        return "UNKNOWN"


def _login_method_label():
    method = (ADDON.getSetting("login_method") or "").strip().lower()
    labels = {
        "email_password": "Email & password",
        "nas_cookie": "Cookie",
        "cookie": "Cookie",
        "browser": "Browser",
        "token_import": "Imported token",
    }
    return labels.get(method, "Existing session" if method == "" else "Other")


def account_menu(add_item, folder_art, request_json, api_headers, handle):
    logged_in = bool(ADDON.getSetting("refresh_token") or ADDON.getSetting("access_token"))
    status = _account_access_status(request_json, api_headers)
    if status == "PAY":
        access_label, access_plain = "[COLOR lime]PAY[/COLOR]", "PAY"
    elif status == "FREE":
        access_label, access_plain = "[COLOR deepskyblue]FREE[/COLOR]", "FREE"
    elif status == "NOT SIGNED IN":
        access_label = access_plain = "Not signed in"
    else:
        access_label = access_plain = "Unknown"
    login_method = _login_method_label() if logged_in else "Not signed in"
    auto_login = "active" if bool(ADDON.getSetting("refresh_token")) else "not available"
    status_plot = (
        "FIA WEC+ Account\nSigned in: {}\nSign-in method: {}\nAccess: {}\nAutomatic sign-in: {}"
    ).format("yes" if logged_in else "no", login_method, access_plain, auto_login)
    add_item("Account · {}".format(access_label), "oauth_status", art=folder_art(), plot=status_plot)
    if logged_in:
        add_item("Signed in with · {}".format(login_method), "oauth_status", art=folder_art(), plot=status_plot)
        add_item("Check token", "oauth_refresh_test", art=folder_art())
        add_item("Sign out", "oauth_logout", art=folder_art())
    else:
        add_item("Sign in with email & password", "oauth_direct_login", art=folder_art())
        add_item("Sign in with cookie", "oauth_cookie_login_shared", art=folder_art())
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.setContent(handle, "videos")
    xbmcplugin.endOfDirectory(handle)


def oauth_status():
    access_token = ADDON.getSetting("access_token")
    refresh_token = ADDON.getSetting("refresh_token")
    expires_at = ADDON.getSetting("expires_at")
    if refresh_token:
        lines = ["Signed in", "Sign-in method: {}".format(_login_method_label()), "Automatic renewal: active"]
    elif access_token:
        lines = ["Signed in", "Sign-in method: {}".format(_login_method_label()), "Automatic renewal: not available"]
    else:
        lines = ["Not signed in"]
    if expires_at and access_token:
        try:
            remain = int(expires_at) - int(time.time())
            if remain > 0:
                lines.append("Access token valid for about {} more minutes".format(remain // 60))
        except Exception:
            pass
    xbmcgui.Dialog().ok("FIA WEC+ Account", "\n".join(lines))


def oauth_logout():
    confirmed = xbmcgui.Dialog().yesno("FIA WEC+", "Do you really want to sign out on this Kodi device?")
    if not confirmed:
        return
    for key in (
        "access_token", "refresh_token", "id_token", "expires_at",
        "access_token_expires", "manual_access_token", "pkce_verifier",
        "oauth_state", "last_authorize_url", "login_method",
    ):
        ADDON.setSetting(key, "")
    xbmcgui.Dialog().notification("FIA WEC+", "Signed out", xbmcgui.NOTIFICATION_INFO, 3000)
    xbmc.executebuiltin("Container.Refresh")
