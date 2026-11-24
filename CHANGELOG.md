# Changelog

## 1.3.0

- Reception of Somfy RTS remotes and sensors, with an a-culfw firmware supporting it (a-culfw 1.26.09, command `Ye`):
  - every received command fires the event `somfy_cul_remote` (address, command, rolling code, RSSI)
  - new cover option **Remotes**: commands of linked remotes and sensors update the state and position of the cover.
    Recently received remotes are offered in the cover dialog, and **Search for a remote** waits for a button press
    and selects the remote.
- The reception is enabled (`Ye1`) when the integration connects to the CUL.
- New option **Inverse mode** for awnings and other covers that open when moving down:
  Down opens (extends), Up closes (retracts), and 100 % means fully extended.
  The position in the state file stays in motor terms (100 = fully up).
- Fix: with **Reverse direction**, the state and position were tracked the wrong way round
  (opening was shown as closing/closed), and set position moved the cover in the wrong direction.
  Reverse direction now only swaps Up and Down in the sent frames.
  A position stored by an earlier version may be wrong once; it is corrected by the next full open or close.
- Up and down time are now described as the times for a complete Up/Down movement.

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
