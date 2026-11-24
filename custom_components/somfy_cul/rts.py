"""Parsing of Somfy RTS frames received by the CUL."""

from __future__ import annotations

from dataclasses import dataclass
import re

# a-culfw reports a received frame as Ys<14 hex digits>, followed by the
# RSSI (2 hex digits) if enabled with X2x. CULs with several transceivers
# (e.g. MapleCUN) prefix the line with '*' per transceiver.
_FRAME_PATTERN = re.compile(r"\**Ys([0-9A-Fa-f]{14})([0-9A-Fa-f]{2})?")

# command nibble of a frame
COMMAND_NAMES: dict[int, str] = {
    0x1: "my",
    0x2: "up",
    0x3: "my_up",
    0x4: "down",
    0x5: "my_down",
    0x6: "up_down",
    0x7: "my_up_down",
    0x8: "prog",
    0x9: "sun_flag",
    0xA: "flag",
}

CMD_MY = 0x1
CMD_UP = 0x2
CMD_DOWN = 0x4


@dataclass(frozen=True, slots=True)
class RtsFrame:
    """A received (decrypted) Somfy RTS frame."""

    key: int
    command_code: int
    rolling_code: int
    address: str
    rssi: float | None = None

    @property
    def command(self) -> str:
        """Return the name of the command, e.g. "up"."""
        return COMMAND_NAMES.get(self.command_code, f"unknown_{self.command_code:X}")


def rssi_to_dbm(raw: int) -> float:
    """Convert the RSSI register value of the CC1101 to dBm."""
    if raw >= 128:
        raw -= 256
    return raw / 2 - 74


def parse_frame(line: str) -> RtsFrame | None:
    """Return the frame of a line received from the CUL, None for other lines.

    Frames with a wrong checksum are ignored (the firmware does not report
    them, but the line may be garbled on the serial line).
    """
    match = _FRAME_PATTERN.fullmatch(line.strip())
    if not match:
        return None
    data = bytes.fromhex(match.group(1))

    cks = 0
    for byte in data:
        cks ^= byte ^ (byte >> 4)
    if cks & 0xF:
        return None

    rssi = rssi_to_dbm(int(match.group(2), 16)) if match.group(2) else None
    return RtsFrame(
        key=data[0],
        command_code=data[1] >> 4,
        rolling_code=(data[2] << 8) | data[3],
        address=data[4:7].hex().upper(),
        rssi=rssi,
    )
