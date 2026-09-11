# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sqlite3
import time

import xbmc
import xbmcvfs

ADDON = None
LOG = None
_CACHE_CONN = None
CACHE_DB_PATH = None

CACHE_TTL_PAGE = 900
CACHE_TTL_PREVIEW_ART = 21600
CACHE_TTL_TAG_FEED = 300

def configure(addon, logger):
    global ADDON, LOG, CACHE_DB_PATH
    ADDON = addon
    LOG = logger
    CACHE_DB_PATH = os.path.join(
        xbmcvfs.translatePath(ADDON.getAddonInfo("profile")), "cache.db"
    )

def _log(message, level=xbmc.LOGDEBUG):
    if LOG:
        LOG(message, level)

def _cache_connect():
    global _CACHE_CONN
    if _CACHE_CONN is not None:
        return _CACHE_CONN
    if not CACHE_DB_PATH:
        raise RuntimeError("cache module not configured")
    profile_dir = os.path.dirname(CACHE_DB_PATH)
    if not xbmcvfs.exists(profile_dir + os.sep):
        xbmcvfs.mkdirs(profile_dir)
    conn = sqlite3.connect(CACHE_DB_PATH, timeout=5, check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL, expires INTEGER NOT NULL)"
    )
    _CACHE_CONN = conn
    return conn

def cache_get(key):
    try:
        conn = _cache_connect()
        row = conn.execute(
            "SELECT value, expires FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        value, expires = row
        if expires and expires < int(time.time()):
            return None
        return json.loads(value)
    except Exception as exc:
        _log("Cache read failed: {}".format(exc), xbmc.LOGDEBUG)
        return None

def cache_set(key, value, ttl_seconds):
    if not ttl_seconds:
        return
    try:
        conn = _cache_connect()
        expires = int(time.time()) + int(ttl_seconds)
        conn.execute(
            "INSERT INTO cache (key, value, expires) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "expires = excluded.expires",
            (key, json.dumps(value), expires),
        )
        conn.commit()
    except Exception as exc:
        _log("Cache write failed: {}".format(exc), xbmc.LOGDEBUG)

def cache_clear():
    try:
        conn = _cache_connect()
        conn.execute("DELETE FROM cache")
        conn.commit()
        return True
    except Exception as exc:
        _log("Cache clear failed: {}".format(exc), xbmc.LOGWARNING)
        return False
