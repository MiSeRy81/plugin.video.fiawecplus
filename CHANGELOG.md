\# Changelog – FIAWEC+



\## 1.6.10



\### Repository / source code



\- Added the GitHub source URL to the add-on metadata.

\- Full source code is now directly available in the repository for reviews and pull requests.



\---



\## 1.6.9



\### Source code refactor



\- Split the previously large `main.py` into focused modules for API access, authentication, caching, routing, event logic, menus, onboard handling, playback and shared Kodi UI helpers.

\- Improved readability, reviewability and pull-request workflows without intended user-facing changes.

\- Full source code is now maintained directly in the GitHub repository, while the installable Kodi ZIP remains available as a separate Release asset.



\### ELMS / MLMC upcoming livestreams



\- Added "Next livestreams" sections for ELMS 2026 and MLMC 2026.

\- Upcoming and currently running sessions are detected automatically from the Staylive livestream catalogue.

\- Local date/time display and LIVE indicators for active sessions.

\- No hardcoded event URLs required, allowing future events to appear automatically when published.



\---



\## 1.6.8



\### WEC onboard improvements



\- Faster onboard replay loading by prioritizing race-specific `VIDEO\_CHANNEL\_TAGS` feeds.

\- Platform-wide season search is now used only as a fallback.

\- Multi-page onboard queries are loaded in parallel for improved performance.



\### Fixes



\- Prevented ELMS and MLMC vehicles from appearing in WEC onboard folders.

\- Improved race-name matching to correctly distinguish "Lone Star Le Mans" from "24 Hours of Le Mans".

\- Fixed empty Hypercar/LMGT3 onboard folders caused by overly strict filtering.



\### Miscellaneous



\- Reduced package size by removing unnecessary cache files.



\---



\## 1.6.7 and earlier



\- No detailed change history available.

