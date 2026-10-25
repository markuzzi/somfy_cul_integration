# Changelog

## 1.2.1

- Fix: `set_cover_position` 0/100 sends a plain CLOSE/OPEN without a trailing STOP.
  The STOP is the RTS MY command and drove covers that had already reached the end stop
  to their MY position (seen with Alexa via Matter, which uses `set_cover_position` for open/close).

## 1.2.0

- The CUL and the covers can be set up and changed in the UI; the YAML configuration is imported automatically.
- Each cover is a device again.
- English and German translations.
- Requires Home Assistant 2025.3 or later.

## 1.1.0

- Fixes loading on Home Assistant 2026.9 and later (#6).
- The CUL is detected reliably after a power loss (#5).
- Rolling codes are kept when an entity is renamed; the state file uses the address as key (#4).
- Hex values from FHEM are accepted in the state file (#1).
- Several fixes for positions, stopping, raw commands and blocking I/O.
- Requires Home Assistant 2024.11 or later.
