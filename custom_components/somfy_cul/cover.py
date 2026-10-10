"""Cover Platform for the Somfy CUL component."""

import asyncio
from enum import Enum
import logging
import os
import re
import time
from typing import Any

import voluptuous as vol
import yaml

from homeassistant.components.cover import (
    ATTR_POSITION,
    PLATFORM_SCHEMA as COVER_PLATFORM_SCHEMA,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
    CoverState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.event import async_call_later

from .const import (
    ATTR_CURRENT_POS,
    ATTR_DOWN_TIME,
    ATTR_ENC_KEY,
    ATTR_ROLLING_CODE,
    ATTR_UP_TIME,
    CONF_ADDRESS,
    CONF_NAME,
    CONF_REVERSED,
    CONF_TYPE,
    DATA_SOMFY_CUL,
    DOMAIN,
    SERVICE_CLOSE,
    SERVICE_OPEN,
    SERVICE_PROG,
    SERVICE_RELOAD,
    SERVICE_STOP,
)
from .cul import Cul


class Command(Enum):
    """Available SOMFY commands."""

    MY = "10"
    STOP = "10"  # alias of MY
    OPEN = "20"
    MY_UP = "30"
    CLOSE = "40"
    MY_DOWN = "50"
    UP_DOWN = "60"
    MY_UP_DOWN = "70"
    PROG = "80"
    WIND_SUN = "90"
    WIND_ONLY = "A0"

    POS = "POS"  # custom


CONFIG_FILE = "somfy_cover_state.yaml"

_LOGGER = logging.getLogger(__name__)
_STATE_FILE_LOCK = asyncio.Lock()


def _read_state_file(path: str) -> dict | None:
    """Read the state file (runs in the executor).

    Returns None if the file exists but cannot be read.
    """
    if not os.path.exists(path):  # noqa: PTH110
        return {}
    try:
        with open(path, encoding="utf-8") as file:  # noqa: PTH123
            state_data = yaml.safe_load(file) or {}
    except (OSError, yaml.YAMLError) as e:
        _LOGGER.error("Error reading state file %s: %s", path, e)
        return None
    if not isinstance(state_data, dict):
        _LOGGER.error("Invalid content in state file %s", path)
        return None
    return state_data


def _write_state_file(path: str, state_data: dict) -> None:
    """Write the state file (runs in the executor)."""
    try:
        with open(path, mode="w", encoding="utf-8") as file:  # noqa: PTH123
            file.write(yaml.safe_dump(state_data, default_flow_style=False))
    except OSError as e:
        _LOGGER.error("Error writing state file %s: %s", path, e)


PLATFORM_SCHEMA = COVER_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ADDRESS): cv.string,
        vol.Optional(CONF_TYPE, default=CoverDeviceClass.SHUTTER): cv.string,
        vol.Optional(CONF_REVERSED, default=False): cv.boolean,
        vol.Optional(ATTR_UP_TIME): vol.Coerce(int),
        vol.Optional(ATTR_DOWN_TIME): vol.Coerce(int),
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Discover and configure Somfy covers."""
    somfy_cul = hass.data.get(DOMAIN, {}).get(DATA_SOMFY_CUL)

    if not somfy_cul:
        _LOGGER.warning("SOMFY CUL device is not available")

    cover_config = {
        "name": config.get(CONF_NAME),
        "device_class": config.get(CONF_TYPE, CoverDeviceClass.SHUTTER),
        "address": config.get(CONF_ADDRESS),
        "up_time": config.get(ATTR_UP_TIME),
        "down_time": config.get(ATTR_DOWN_TIME),
        "reverse": config.get(CONF_REVERSED, False),
    }

    cover = SomfyCulShade(hass, somfy_cul, **cover_config)

    _LOGGER.debug(
        "Adding Somfy Cover: %s with address %s",
        cover_config["name"],
        cover_config["address"],
    )

    async_add_entities([cover])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_PROG, {}, "async_prog_cover")
    platform.async_register_entity_service(SERVICE_OPEN, {}, "async_open_cover")
    platform.async_register_entity_service(SERVICE_CLOSE, {}, "async_close_cover")
    platform.async_register_entity_service(SERVICE_STOP, {}, "async_stop_cover")
    platform.async_register_entity_service(SERVICE_RELOAD, {}, "async_reload_state")


class SomfyCulShade(RestoreEntity, CoverEntity):
    """Object for controlling a Somfy cover."""

    _attr_should_poll = False
    _attr_assumed_state = True
    _attr_has_entity_name = True
    _attr_name = None
    _attr_unique_id = None

    _enc_key: int = 1
    _rolling_code: int = 0
    _up_time = None
    _down_time = None

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Flag supported features."""
        supported_features = CoverEntityFeature(0)
        if self._up_time is not None and self._down_time is not None:
            supported_features |= (
                CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP
                | CoverEntityFeature.SET_POSITION
            )
        else:
            supported_features |= (
                CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP
            )

        return supported_features

    def __init__(
        self,
        hass: HomeAssistant,
        somfy_cul: Cul,
        address: str,
        up_time: int | None = None,
        down_time: int | None = None,
        name="SomfyCover",
        reverse=False,
        device_class=CoverDeviceClass.SHADE,
    ) -> None:
        """Initialize the cover."""
        self._hass = hass
        self._somfy_cul = somfy_cul

        self._attr_name = name
        self._address = address
        self._reverse = reverse
        self._up_time = up_time
        self._down_time = down_time

        self._cancel_drv_timer = None
        self._cancel_stop_timer = None
        self._cmd_time = 0

        self._attr_unique_id = address
        self._attr_device_class = device_class
        self._attr_is_closed = True
        self._attr_is_opening = False
        self._attr_is_closing = False

        self._attr_extra_state_attributes = {
            "enc_key": self._enc_key,
            "rolling_code": self._rolling_code,
        }

        self._pending_saves: set[asyncio.Task] = set()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        cmd = Command.CLOSE if not self._reverse else Command.OPEN
        await self.async_send_command(cmd)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        cmd = Command.CLOSE if self._reverse else Command.OPEN
        await self.async_send_command(cmd)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self.async_send_command(Command.STOP)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        if (position := kwargs.get(ATTR_POSITION)) is None:
            _LOGGER.debug("Argument `position` is missing in set_cover_position")
            return

        await self.async_send_command(Command.POS, int(position))

    async def async_send_command(self, cmd: Command, target_pos=None) -> None:
        """Update the state and send a command to the CUL."""

        cmd, time_to_stop = self._update_state(cmd, target_pos)
        if cmd is None:
            return

        # a new command replaces a pending stop of a previous positioning move
        self._cancel_pending_stop()

        if not await self._async_transmit(cmd):
            return

        if time_to_stop and time_to_stop > 0:
            self._cancel_stop_timer = async_call_later(
                self.hass, time_to_stop, self._async_stop_timer_fired
            )

    def _cancel_pending_stop(self) -> None:
        if self._cancel_stop_timer:
            self._cancel_stop_timer()
            self._cancel_stop_timer = None

    async def _async_stop_timer_fired(self, _now) -> None:
        self._cancel_stop_timer = None
        await self._async_transmit(Command.STOP)

    async def _async_transmit(self, cmd: Command) -> bool:
        """Send a single frame and consume a rolling code."""
        if not self._somfy_cul:
            _LOGGER.error("CUL handle missing; command %s dropped", cmd)
            return False

        frame = self._command_string(cmd)
        # consume the rolling code before awaiting so that concurrent
        # commands never reuse the same code
        self._increase_rolling_code()

        try:
            sent = await self.hass.async_add_executor_job(
                self._somfy_cul.send_command, frame
            )
        except Exception:
            _LOGGER.exception("Failed to send Somfy frame %r", frame)
            return False

        if not sent:
            _LOGGER.error("Failed to send Somfy frame %r", frame)
        return sent

    async def async_prog_cover(self, **kwargs: Any) -> None:
        """Handle the async_prog_cover service."""
        await self._async_transmit(Command.PROG)

    async def async_added_to_hass(self) -> None:
        """Complete the initialization."""
        await super().async_added_to_hass()
        # Restore the last state
        last_state = await self.async_get_last_state()

        if last_state is not None and last_state.state in (
            CoverState.OPEN,
            CoverState.CLOSED,
        ):
            self._attr_is_closed = last_state.state == CoverState.CLOSED

        await self._load_state_from_yaml()
        # save the initial state or migrate the entry to the current format
        await self._save_state_to_yaml()

    async def async_reload_state(self, **kwargs: Any) -> None:
        """Reload the state from the YAML file."""
        # let pending writes finish, otherwise an outdated rolling code is loaded
        if self._pending_saves:
            await asyncio.gather(*self._pending_saves)
        await self._load_state_from_yaml()

    async def _save_state_to_yaml(self):
        """Save the current state to the file using the address as the key."""
        async with _STATE_FILE_LOCK:
            state_data = await self._read_state_yaml()
            if state_data is None:
                # do not overwrite the rolling codes of all other covers
                _LOGGER.error("State of %s not saved", self.entity_id)
                return

            # Remove entries of this cover stored under another key, e.g. the
            # entity id used by older versions
            for key in self._find_state_keys(state_data):
                del state_data[key]

            # Update state for the current address
            state_data[self._state_key] = self._get_state()

            # Save updated state back to the file
            await self.hass.async_add_executor_job(
                _write_state_file, self._get_state_file_path(), state_data
            )

    async def _load_state_from_yaml(self):
        """Load the state of this cover from the file, if it exists."""
        state_data = await self._read_state_yaml()
        if not state_data:
            return False

        keys = self._find_state_keys(state_data)
        if not keys:
            return False

        self._set_state(state_data[keys[0]])
        return True

    @property
    def _state_key(self) -> str:
        """Key of this cover in the state file.

        The address is used since the entity id may be changed by the user.
        """
        return str(self._address).upper()

    def _find_state_keys(self, state_data: dict) -> list:
        """Return the keys of this cover in the state file, preferred first."""
        address = self._state_key.zfill(6)
        keys = [
            key
            for key in state_data
            if str(key).upper().zfill(6) == address
        ]
        # fallback for state files written by versions 1.0.x
        if self.entity_id in state_data:
            keys.append(self.entity_id)
        return keys

    async def _read_state_yaml(self):
        """Load the state from the file, if it exists."""
        return await self.hass.async_add_executor_job(
            _read_state_file, self._get_state_file_path()
        )

    def _get_state_file_path(self):
        """Get the full path to the state file."""
        return self._hass.config.path(CONFIG_FILE)

    def _get_state(self):
        return {
            ATTR_ENC_KEY: self._enc_key,
            ATTR_ROLLING_CODE: self._rolling_code,
            ATTR_CURRENT_POS: self._attr_current_cover_position,
        }

    def _set_state(self, state):
        """Set the object's state from a dictionary."""
        self._enc_key = state.get(ATTR_ENC_KEY, self._enc_key)
        self._rolling_code = state.get(ATTR_ROLLING_CODE, self._rolling_code)
        self._attr_current_cover_position = state.get(
            ATTR_CURRENT_POS, self._attr_current_cover_position
        )
        self._attr_extra_state_attributes = {
            "enc_key": self._enc_key,
            "rolling_code": self._rolling_code,
        }
        self.async_write_ha_state()

    def _async_save_state(self):
        self._attr_extra_state_attributes = {
            "enc_key": self._enc_key,
            "rolling_code": self._rolling_code,
        }
        self.async_write_ha_state()
        task = self.hass.async_create_task(self._save_state_to_yaml())
        self._pending_saves.add(task)
        task.add_done_callback(self._pending_saves.discard)

    def _increase_rolling_code(self):
        """Increment rolling_code, roll over when crossing the 16 bit boundary.

        Increment enc_key, roll over when crossing the 4 bit boundary.
        """

        self._rolling_code = (self._rolling_code + 1) % 0x10000
        self._enc_key = (self._enc_key + 1) % 0x10
        self._async_save_state()

        _LOGGER.debug(
            "Next rolling code for device %s is %d, encryption key is %d",
            self._address,
            self._rolling_code,
            self._enc_key,
        )

    def _reset_timer(self):
        """Reset timer functions."""
        if getattr(self, "_cancel_drv_timer", None):
            _LOGGER.debug("Resetting timer")
            try:
                self._cancel_drv_timer()
            finally:
                self._cancel_drv_timer = None

    def _write_state(self, cmd: Command, position=None):
        if cmd == Command.OPEN:
            self._write_state_open()
        elif cmd == Command.CLOSE:
            self._write_state_closed()
        elif cmd == Command.POS:
            self._write_state_pos(position)
        else:
            _LOGGER.error("Wrong command %s to write the device state", cmd)

    def _write_state_pos(self, position):
        """Timer function called when shutter has been set to position."""
        _LOGGER.debug("Write state position for device: %s", self._attr_name)
        self._attr_is_opening = False
        self._attr_is_closing = False
        self._attr_is_closed = position <= 0
        self._attr_current_cover_position = position
        self._async_save_state()

    def _write_state_open(self):
        """Timer function called when shutter has been opened."""
        _LOGGER.debug("Write state open for device: %s", self._attr_name)
        self._attr_is_opening = False
        self._attr_is_closing = False
        self._attr_is_closed = False
        self._attr_current_cover_position = 100
        self._async_save_state()

    def _write_state_closed(self):
        """Timer function called when shutter has been closed."""
        _LOGGER.debug("Write state closed for device: %s", self._attr_name)
        self._attr_is_opening = False
        self._attr_is_closing = False
        self._attr_is_closed = True
        self._attr_current_cover_position = 0
        self._async_save_state()

    def _write_state_stopped(self, position=0):
        """Timer function called when shutter has been closed."""
        _LOGGER.debug("Write state stopped for device: %s", self._attr_name)
        self._attr_is_opening = False
        self._attr_is_closing = False
        self._attr_is_closed = False
        self._attr_current_cover_position = position
        self._async_save_state()

    def _calculate_position_command(
        self, target_position: int | None = None
    ) -> tuple[Command, float]:
        cur = self._attr_current_cover_position or 0
        target = 100 if target_position is None else target_position

        if target > cur:
            cmd = Command.OPEN
            time_per_step = self._up_time / 100
            time_to_stop = time_per_step * (target - cur)
        elif target < cur:
            cmd = Command.CLOSE
            time_per_step = self._down_time / 100
            time_to_stop = time_per_step * (cur - target)
        else:
            _LOGGER.debug("Already at position")
            return None, None

        return cmd, time_to_stop

    def _start_update_state_timer(
        self, cmd: Command, target_position=None
    ) -> tuple[Command, float]:
        """Start the timer when moving the shutter. Resets the time, when cmd is STOP.

        Returns the time after which the cover must be stoppped in case of a target position
        """
        _LOGGER.debug("Starting a timer for device: %s", self._attr_name)
        self._reset_timer()
        self._cmd_time = time.time()

        # This is the time, after which the cover must be stoppped in case of a target position
        time_to_stop = None

        if cmd == Command.POS:
            cmd, time_to_stop = self._calculate_position_command(target_position)
            if cmd is None or time_to_stop is None:
                _LOGGER.debug("Position cannot be set")
                return None, None

            self._attr_is_opening = cmd == Command.OPEN
            self._attr_is_closing = cmd == Command.CLOSE
            self.async_write_ha_state()

            async def _handle_timer(_now):
                self._write_state_pos(target_position)
            self._cancel_drv_timer = async_call_later(self.hass, time_to_stop, _handle_timer)
            # self._cancel_drv_timer = Timer( time_to_stop, self._write_state_pos, args=(target_position,) )

            _LOGGER.debug("POS timer with timeout: %s", time_to_stop)

        elif cmd == Command.OPEN:
            self._attr_is_opening = True
            self._attr_is_closing = False
            self._async_save_state()

            timeout = self._up_time
            if self._attr_current_cover_position is not None:
                cur = self._attr_current_cover_position / 100
                timeout = timeout * (1 - cur) + 1

            async def _cb(_now):
                self._write_state_open()
            self._cancel_drv_timer = async_call_later(self.hass, timeout, _cb)
            # self._cancel_drv_timer = Timer(timeout, self._write_state_open)
            _LOGGER.debug("OPEN timer with timeout: %s", timeout)

        elif cmd == Command.CLOSE:
            self._attr_is_opening = False
            self._attr_is_closing = True
            self._async_save_state()

            timeout = self._down_time
            if self._attr_current_cover_position is not None:
                cur = self._attr_current_cover_position / 100
                timeout = timeout * (cur) + 1

            async def _cb(_now):
                self._write_state_closed()
            self._cancel_drv_timer = async_call_later(self.hass, timeout, _cb)
            # self._cancel_drv_timer = Timer(timeout, self._write_state_closed)
            _LOGGER.debug("CLOSE timer with timeout: %s", timeout)

        else:
            _LOGGER.warning(
                "Timer can only be started for commands OPEN, CLOSE, and POS, but not for %s",
                cmd,
            )
            return None, None

        return cmd, time_to_stop

    def _update_state(
        self, cmd: Command, target_position=None
    ) -> tuple[Command, float]:
        """Calculate position, publish state and position.

        Returns the time after which the cover must be stoppped in case of a target position
        """
        _LOGGER.debug("Updating state for command: %s", cmd)
        _move_time = None
        if cmd == Command.OPEN:
            _move_time = self._up_time
        elif cmd == Command.CLOSE:
            _move_time = self._down_time
        elif cmd == Command.POS:
            _move_time = min(self._up_time or 0, self._down_time or 0)

        _LOGGER.debug("Move time: %s", _move_time)

        time_to_stop = None

        if cmd in (Command.OPEN, Command.CLOSE, Command.POS):
            if _move_time and _move_time > 0:
                cmd, time_to_stop = self._start_update_state_timer(cmd, target_position)
            else:
                if cmd == Command.POS:
                    _LOGGER.error("Position cannot be set. Did you set up up_time and down_time?")
                    return None, None
                else:
                    self._write_state(cmd)

        elif cmd == Command.STOP:
            current_pos = (
                50
                if self._attr_current_cover_position is None
                else self._attr_current_cover_position
            )
            current_time = time.time()

            if self._cancel_drv_timer is not None and (
                self._attr_is_closing or self._attr_is_opening
            ):
                self._reset_timer()
                if self._cmd_time > 0:
                    ti = current_time - self._cmd_time
                    dt = self._up_time if self._attr_is_opening else self._down_time
                    current_pos += round(ti / dt * 100) * (
                        1 if self._attr_is_opening else -1
                    )

            # Make sure that pos is in range 0..100
            current_pos = max(min(current_pos, 100), 0)

            # publish stopped state and calculated position
            self._write_state_stopped(current_pos)
            self._cmd_time = 0

        return cmd, time_to_stop


    def _calculate_checksum(self, frame_hex: str) -> str:
        """Calculate checksum for command string.

        From https://pushstack.wordpress.com/somfy-rts-protocol/ :

        Somfy-Checksumme über die 7 Frame-Bytes (14 Hex-Nibbles) berechnen.
        Erwartet eine 14-stellige Hex-Zeichenkette ohne 'Ys' und ohne '\n'.
        Vor der Berechnung wird das cks-Nibble (Index 3) auf '0' gesetzt.
        """
        if not isinstance(frame_hex, str):
            _LOGGER.error("Checksum: frame must be str, got %r", type(frame_hex))
            raise ValueError("frame_hex must be str")

        frame_hex = frame_hex.upper()
        if not re.fullmatch(r"[0-9A-F]{14}", frame_hex or ""):
            _LOGGER.error("Checksum: invalid frame '%s' (need 14 hex nibbles)", frame_hex)
            raise ValueError(f"Somfy frame must be 14 hex digits, got: {frame_hex!r}")

        # cks-Nibble to 0 for calculation
        frame0 = frame_hex[:3] + "0" + frame_hex[4:]

        cks = 0

        debug = _LOGGER.isEnabledFor(logging.DEBUG)
        if debug:
            bytes_list = []

        for i in range(0, 14, 2):
            b = int(frame0[i:i+2], 16)     # 2 Hex chars -> 1 Byte
            if debug:
                bytes_list.append(b)
            cks ^= (b ^ (b >> 4))

        cks &= 0xF
        if debug:
            _LOGGER.debug(
                "Checksum calc: frame0=%s bytes=%s -> cks=%X",
                frame0, " ".join(f"{b:02X}" for b in bytes_list), cks
            )
        return f"{cks:X}"

    def _command_string(self, cmd: Command):
        """Generate command string.

        A Somfy command is a hex string of the following form: KKC0RRRRSSSSSS.

        KK - Encryption key: First byte always 'A', second byte varies
        C - Command (1 = My, 2 = Up, 4 = Down, 8 = Prog)
        0 - Checksum (set to 0 for calculating checksum)
        RRRR - Rolling code
        SSSSSS - Address (= remote channel)
        """

        addr = str(self._address).upper()
        if not re.fullmatch(r"[0-9A-F]{1,6}", addr or ""):
            raise ValueError(f"invalid Somfy address: {self._address!r}")
        address = addr.zfill(6)

        enc = f"{(int(self._enc_key) & 0xF):X}"
        cval = cmd.value # f"{(int(cmd.value) & 0xF):X}"
        roll = f"{(int(self._rolling_code) & 0xFFFF):04X}"

        raw = f"A{enc}{cval}{roll}{address}"
        if len(raw) != 14:
            _LOGGER.error("Command build: invalid raw length %d (raw=%s)", len(raw), raw)
            raise ValueError("raw Somfy frame must be 14 hex nibbles")

        chksum = self._calculate_checksum(raw)
        frame  = raw[:3] + chksum + raw[4:]

        _LOGGER.debug(
            "Generated string %s from command %s for device %s",
            frame,
            cmd.value,
            self.name,
        )

        # Verification: XOR of all Nibbles (over 7 Bytes) must be 0
        test = 0
        for i in range(0, 14, 2):
            b = int(frame[i:i+2], 16)
            test ^= (b ^ (b >> 4))
        if (test & 0xF) != 0:
            _LOGGER.warning(
                "Checksum verify failed: frame=%s residual=%X (raw=%s, cks=%s)",
                frame, test & 0xF, raw, chksum
            )
        else:
            _LOGGER.debug("Checksum OK for frame=%s", frame)

        _LOGGER.debug(
            "ENC Key: %s, CMD: %s, CHKSUM: %s, Rolling Code: %s, Address: %s",
            self._enc_key,
            cmd.value,
            chksum,
            self._rolling_code,
            self._address,
        )

        wire = ("Ys" + frame + "\n").encode("ascii", "strict")
        _LOGGER.debug("Wire command: %r", wire)
        return wire
