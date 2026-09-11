# FIAWEC+ for Kodi

Unofficial Kodi video add-on for **FIA World Endurance Championship (WEC)**, **European Le Mans Series (ELMS)** and **Michelin Le Mans Cup (MLMC)** content published through FIAWEC+/Staylive.

## Features

- WEC, ELMS and MLMC navigation by season and event
- Races, qualifying, practice sessions, highlights and replays where available
- WEC onboard replays where provided by FIAWEC+/Staylive
- Upcoming and live WEC, ELMS and MLMC sessions where available
- Free and subscription-protected content handling
- Cookie-based FIAWEC+/Staylive authentication
- Cookie-file sign-in support, including shared cookie files
- OAuth access/refresh-token handling with automatic token renewal
- Internal caching for faster navigation

## Installation

1. Download the current `plugin.video.fiawecplus-<version>.zip` from the GitHub Releases page.
2. In Kodi, open **Add-ons → Install from ZIP file**.
3. Select the downloaded ZIP package.
4. Open **Add-ons → Video add-ons → FIAWEC+**.
5. Configure sign-in from the **Account** menu if required.

## Authentication

The add-on supports FIAWEC+/Staylive authentication for protected content. Cookie-based sign-in and cookie-file sign-in are available, and access tokens are renewed automatically when possible.

Some FIA WEC content requires an active WEC+ subscription. ELMS and Michelin Le Mans Cup content may be available free of charge depending on what the service publishes.

## Source layout

The source is intentionally split into focused modules instead of keeping the complete add-on in one large Python file:

```text
main.py                         Kodi entry point / compatibility handlers
resources/lib/api.py            HTTP and Staylive API helpers
resources/lib/auth.py           Cookie, account and token handling
resources/lib/cache.py          Internal response cache
resources/lib/config.py         Shared configuration/constants
resources/lib/diagnostics.py    Diagnostics helpers
resources/lib/onboard.py        WEC onboard detection/filtering
resources/lib/playback.py       Kodi playback handling
resources/lib/routes.py         Action routing
resources/lib/series_data.py    Shared WEC/ELMS/MLMC event data logic
resources/lib/series_menu.py    ELMS/MLMC season and event menus
resources/lib/ui.py             Shared Kodi UI/list item helpers
resources/lib/utils.py          General utility helpers
resources/lib/video_menu.py     Video/feed/playlist presentation
resources/lib/wec_events.py     WEC season, race and event logic
```

`main.py` remains the Kodi plug-in entry point, while API access, authentication, event matching, menus, playback and other responsibilities live in separate modules.

## Development and pull requests

The complete Python source is kept directly in the repository so changes can be reviewed without downloading and unpacking a release ZIP.

For contributions:

1. Fork the repository and create a branch for your change.
2. Keep changes focused and avoid unrelated formatting rewrites.
3. Test navigation and playback in Kodi before opening a pull request.
4. For event-matching changes, check WEC, ELMS and MLMC and pay particular attention to similarly named events such as **24 Hours of Le Mans** and **Lone Star Le Mans**.
5. Describe the behavior change and the Kodi version/platform used for testing in the pull request.

## Releases

The repository contains the readable source code. Installable Kodi packages are published separately as ZIP files under **GitHub Releases**.

## Disclaimer

This is an unofficial Kodi add-on and is not affiliated with, endorsed by, or associated with FIA, FIA WEC, ACO, ELMS, Michelin Le Mans Cup or Staylive. The add-on does not host video content. Users are responsible for having the appropriate access rights or subscription for protected content.
