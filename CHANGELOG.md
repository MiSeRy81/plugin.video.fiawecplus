# Changelog

## FIA WEC+ v1.7.5

### UI / Video information

- Added compact three-line information for normal WEC, ELMS and MLMC videos.
- Unified WEC and ELMS onboard information into a clean three-line layout.
- Removed duplicate class information from onboard vehicle lines.
- WEC onboards now use the selected Hypercar/LMGT3 folder as the class source.
- Added Spanish `[ES]` language detection to the compact information view.
- Cleaned WEC archive titles that already contain the session name.

### ELMS Onboards

- Improved ELMS onboard discovery for separate Staylive event channels.
- Added verified Spa-Francorchamps onboard support through channel `7513` (`elms-spa-onboards`).
- Added verified Silverstone onboard support through channel `7614` (`elms-silverstone-onboards`).
- Added a generic fallback for future `elms-<event>-onboards` channels.

### General

- Keeps the existing Upcoming Livestreams layout unchanged.
- Preserves WEC 2026 official artwork, Hero/Cover backgrounds, login methods, subscription checks and existing playback behavior.

## FIA WEC+ v1.7

- Added official FIAWEC+ 2026 race posters and Hero/Cover artwork.
- Improved ELMS/MLMC Upcoming Livestreams with stream-specific artwork, LIVE/TODAY/TOMORROW labels and chronological sorting.
- Improved local CET/CEST handling and ELMS onboard presentation.
- Cleaned event information, dates, naming and release metadata.
- Provider name changed to `MiSeRy`.

## FIA WEC+ v1.6.14

- Added official 2026 WEC race artwork and improved race information panels.
- Improved ELMS/MLMC livestream navigation, sorting, artwork and local time handling.
- Cleaned internal release metadata and legacy rendering code.
