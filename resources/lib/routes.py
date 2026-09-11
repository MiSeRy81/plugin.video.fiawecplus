# -*- coding: utf-8 -*-
from __future__ import annotations

import urllib.parse


def _first(query, key, default=""):
    return query.get(key, [default])[0]


def dispatch(argv, handlers, addon, xbmcplugin, handle):
    """Parse plugin query parameters and dispatch to an action handler.

    `handlers` is supplied by main.py so this module has no dependency on the
    Kodi add-on implementation itself and introduces no circular imports.
    """
    query = urllib.parse.parse_qs(argv[2][1:] if len(argv) > 2 else "")
    action = _first(query, "action")

    def call(name, *args):
        func = handlers.get(name)
        if func is None:
            raise RuntimeError("Missing route handler: {}".format(name))
        return func(*args)

    if not action:
        return call("root")

    if action == "event_group":
        return call(
            "event_group",
            _first(query, "event"),
            _first(query, "main_start"), _first(query, "main_end"), _first(query, "main_channel"),
            _first(query, "onboard_start"), _first(query, "onboard_end"), _first(query, "onboard_channel"),
        )
    if action == "series":
        return call("series", _first(query, "slug"))
    if action in ("elms_series", "mlmc_series", "wec_series", "wec_icons", "fiawec_originals",
                  "oauth_import_token_file", "oauth_browser_refresh_import", "oauth_direct_login",
                  "oauth_cookie_login_file", "oauth_cookie_select_shared", "oauth_cookie_login_shared",
                  "oauth_cookie_login_manual", "oauth_refresh_test", "account_menu",
                  "diagnose_next_sessions", "diagnose_extra_content", "diagnose_onboard_video_fields",
                  "diagnose_tag_structure", "oauth_status", "oauth_logout", "oauth_refresh",
                  "cache_clear_action"):
        return call(action)
    if action == "wec_year":
        return call("wec_year", _first(query, "year"))
    if action == "wec_next_livestreams":
        return call("wec_next_livestreams", _first(query, "year", "2026"))
    if action == "series_next_livestreams":
        return call("series_next_livestreams", _first(query, "series_key"), _first(query, "year", "2026"))
    if action == "wec_onboard_livestreams":
        return call("wec_onboard_livestreams", _first(query, "path"), _first(query, "race_label"), _first(query, "year", "2026"))
    if action == "wec_race":
        return call("wec_race", _first(query, "path"), _first(query, "event_name"), _first(query, "year"))
    if action == "playlist":
        return call("playlist", _first(query, "uid"), _first(query, "playlist_label", "Playlist"))
    if action == "tag_feed":
        return call(
            "tag_feed", _first(query, "tags"), _first(query, "start"), _first(query, "end"),
            _first(query, "page", "1"), _first(query, "all_tags_required", "0"),
            _first(query, "suppress_access", "1"),
        )
    if action == "feed":
        return call(
            "feed", _first(query, "start"), _first(query, "end"), _first(query, "channel"),
            _first(query, "page", "1"), _first(query, "forced_access"), _first(query, "suppress_access", "0"),
        )
    if action == "wec_onboard_replays":
        return call(
            "wec_onboard_replays", _first(query, "path"),
            _first(query, "replay_label", "Replay - Onboards Hypercar"),
            _first(query, "car_class", "hypercar"), _first(query, "session"),
        )
    if action == "play_livestream":
        return call("play_livestream", _first(query, "slug"))
    if action == "play":
        return call("play", _first(query, "slug"))

    if action in ("test_barcelona_feed", "input_slug", "test_manual_token", "refresh_token"):
        call(action)
        return xbmcplugin.endOfDirectory(handle, succeeded=True, updateListing=False)

    if action == "noop":
        return xbmcplugin.endOfDirectory(handle, succeeded=True, updateListing=False)

    if action == "settings":
        addon.openSettings()
        return xbmcplugin.endOfDirectory(handle, succeeded=True, updateListing=False)

    # Keep the historic fallback behaviour for unknown/obsolete URLs.
    return call("root")
