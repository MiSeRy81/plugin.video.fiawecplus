# Changelog – FIAWEC+

## 1.6.9

**Source code / repository**
- The previously very large `main.py` was split into focused modules for API access, authentication, caching, routing, WEC event logic, ELMS/MLMC menus, onboard handling, playback and shared Kodi UI helpers.
- The refactor is intended to improve readability, reviewability and pull-request workflows without changing the visible add-on behavior.
- The complete source is now suitable for keeping directly in the GitHub repository, while the installable Kodi ZIP can remain a separate Release asset.

**ELMS / Michelin Le Mans Cup – kommende Livestreams**
- Unter ELMS → 2026 und MLMC → 2026 gibt es jetzt jeweils **„Nächste Livestreams“**.
- Kommende und aktuell laufende Sessions werden automatisch aus dem plattformweiten Staylive-Livestream-Katalog geladen.
- Datum und Uhrzeit werden lokal angezeigt; bereits laufende Sessions erhalten einen roten **LIVE**-Hinweis.
- Die Erkennung ist serienbasiert und benötigt keine fest hinterlegten Silverstone-URLs. Dadurch können auch spätere Events automatisch erscheinen, sobald Staylive sie veröffentlicht.

---

## 1.6.8

**Performance – WEC-Onboard-Replays laden schneller**
- Der Ladepfad für "Replay - Onboards Hypercar/LMGT3" nutzt jetzt primär die
  eigenen `VIDEO_CHANNEL_TAGS`-Feeds der jeweiligen Rennseite (channel-gebunden,
  wie bei den normalen Replays). Die teure, plattformweite Suche über die
  komplette Saison läuft nur noch als Fallback, wenn die Rennseite selbst
  keinen passenden Onboard-Feed liefert.
- Mehrseitige Onboard-/Tag-Abfragen holen alle Seiten nach der ersten jetzt
  **parallel** ab (kleiner Thread-Pool) statt strikt nacheinander. Das
  verkürzt vor allem das erste (kalte) Öffnen eines Onboard-Ordners deutlich.

**Bugfix – falsche Fahrzeuge in WEC-Onboard-Ordnern**
- ELMS- und Michelin-Le-Mans-Cup-Fahrzeuge tauchten in WEC-Onboard-Ordnern auf,
  wenn beide Serien am selben Wochenende/Ort fahren (z. B. WEC "6 Hours of
  Imola" vs. ELMS "4 Hours of Imola"). Videos werden jetzt anhand ihres
  eigenen Slugs/Titels/Channel-Namens als andere Serie erkannt und
  ausgeschlossen, unabhängig vom Streckennamen.
- "Lone Star Le Mans" (Circuit of the Americas) zeigte fälschlich Onboards der
  echten "24 Hours of Le Mans", weil beide Rennnamen die Wörter "Le"/"Mans"
  teilen und die Namens-Filterung nur eines der Wörter verlangte (ODER statt
  UND). Der Abgleich verlangt jetzt alle unterscheidenden Wörter gemeinsam.
- Als Folge dieser Verschärfung waren Hypercar/LMGT3 bei Lone Star Le Mans
  zwischenzeitlich komplett leer, weil der Namens-Check unnötig auch auf den
  bereits korrekt eingegrenzten (channel-gebundenen) Pfad angewendet wurde.
  Der Check läuft jetzt nur noch dort, wo er wirklich nötig ist – im
  plattformweiten Fallback.

**Sonstiges**
- Paketgröße reduziert (u. a. `__pycache__` entfernt, ca. 852 KB → 728 KB).

---

## 1.6.7 und früher

Keine Änderungshistorie vorhanden – dies ist der Startpunkt der Aufzeichnung.
