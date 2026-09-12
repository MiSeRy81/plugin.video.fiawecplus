# Changelog

## FIA WEC+ v1.7

### WEC

- Added official FIAWEC+ 2026 race posters.
- Uses official WEC race-page Hero/Cover images as fanart backgrounds when available.
- Keeps older WEC seasons on their existing local artwork.
- Includes the corrected Spa-Francorchamps and São Paulo 2026 artwork mappings.
- Keeps the cleaned WEC archive renderer and event information layout.

### ELMS / Michelin Le Mans Cup

- Improved Upcoming Livestreams with chronological sorting and stream-specific artwork.
- Displays `LIVE` for currently running streams and compact date/time prefixes for upcoming sessions.
- Supports `TODAY` / `TOMORROW` labels where the device date can be resolved reliably.
- Keeps ELMS onboard livestreams and replays with compact class, car and session information.
- Limits ELMS/MLMC upcoming video sessions to actual Qualifying and Race feeds.
- Uses deterministic CET/CEST conversion for German local stream times with safe fallbacks.
- Keeps corrected weekend dates and cleaned event information panels.
- Removes the separate Round line from race information.

### General

- Provider name is now `MiSeRy`.
- Visible add-on name remains `FIA WEC+`.
- Keeps email/password and cookie-based sign-in methods.
- Keeps subscription and sign-in checks for protected content.
- Preserves EN, FR and Raw Sound stream variants.
- Preserves WEC/ELMS onboard support and excludes MLMC onboard folders.
- Cleaned release metadata and removed development/test remnants.

## FIA WEC+ v1.6.14

- Added official 2026 WEC race artwork and improved race information panels.
- Improved ELMS/MLMC livestream navigation, sorting, artwork and local time handling.
- Cleaned internal release metadata and legacy rendering code.
