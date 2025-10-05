"""The Somfy CUL integration."""

from __future__ import annotations

import logging

import asyncio
import time
from collections import deque
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers.dispatcher import dispatcher_send

from .const import (
    CONF_BAUD_RATE,
    CONF_CUL_PATH,
    CONF_DEBUG_RX,
    DATA_RX_BUFFER,
    DATA_RX_CALLBACK,
    DATA_SOMFY_CUL,
    DOMAIN,
    SERVICE_RELOAD_PLATFORM,
    SERVICE_SEND_RAW_COMMAND,
    SIGNAL_SOMFY_CUL_FRAME,
)
from .cul import Cul


_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.COVER]

RAW_COMMAND_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("command"): cv.string,
        vol.Optional("timeout", default=2.0): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: {
            vol.Optional(CONF_CUL_PATH, default="/dev/ttyAMA0"): cv.string,
            vol.Optional(CONF_BAUD_RATE, default=38400): vol.Coerce(int),
        }
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    conf = config.get(DOMAIN)
    if not conf:
        _LOGGER.error(
            "SOMFY CUL configuration is missing. "
            "Add a '%s:' section to your configuration.yaml.", DOMAIN
        )
        return False

    cul_path = conf.get(CONF_CUL_PATH)
    if not cul_path:
        _LOGGER.error("Missing required option '%s' in %s config.", CONF_CUL_PATH, DOMAIN)
        return False

    baud_rate = int(conf.get(CONF_BAUD_RATE, 38400))
    debug_rx: bool = bool(conf.get(CONF_DEBUG_RX, False))
    cul = None

    try:
        cul = Cul(cul_path, baud_rate)
    except ValueError as e:
        _LOGGER.error("Could not connect to CUL at %s: %s", cul_path, e)
        return False

    version = cul.get_cul_version()
    if not version:
        _LOGGER.error("Could not read CUL version at %s", cul_path)
        cul.close()
        return False

    _LOGGER.info("SOMFY CUL connected (%s) at %s, baud %d", version, cul_path, baud_rate)

    async def _on_ha_stop(_event) -> None:
        try:
            cul.close()
            _LOGGER.info("SOMFY CUL at %s closed on shutdown.", cul_path)
        except Exception as e:
            _LOGGER.debug("Error while closing CUL at shutdown: %s", e)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_ha_stop)

    rx_buffer = deque(maxlen=200)  # <—
    hass.data.setdefault(DOMAIN, {})[DATA_RX_BUFFER] = rx_buffer
    hass.data[DOMAIN][DATA_RX_CALLBACK] = _on_rx
    hass.data[DOMAIN][DATA_SOMFY_CUL] = cul

    def _on_rx(line: str) -> None:
        rx_buffer.append(line)

        if debug_rx and _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("SOMFY CUL RX: %s", line)

        # entities could subscribe on this:
        dispatcher_send(hass, SIGNAL_SOMFY_CUL_FRAME, line)

    cul.start_listen(_on_rx)

    async def async_reload_platform_service(_call) -> None:
        somfy_cul = hass.data.get(DOMAIN, {}).get(DATA_SOMFY_CUL)
        if not somfy_cul:
            _LOGGER.error("Reload requested but SOMFY CUL is not initialized")
            return

        success = await hass.async_add_executor_job(somfy_cul.reload_connection)
        if not success:
            _LOGGER.error("Could not reopen SOMFY CUL connection")
            return

        version = await hass.async_add_executor_job(somfy_cul.get_cul_version)
        if version:
            _LOGGER.info("SOMFY CUL reloaded (%s)", version)
        else:
            _LOGGER.warning("SOMFY CUL reloaded but version could not be read")

        callback = hass.data.get(DOMAIN, {}).get(DATA_RX_CALLBACK)
        if callback:
            await hass.async_add_executor_job(somfy_cul.start_listen, callback)

    async def async_send_raw_service(call) -> None:
        somfy_cul = hass.data.get(DOMAIN, {}).get(DATA_SOMFY_CUL)
        if not somfy_cul:
            _LOGGER.error("Raw command requested but SOMFY CUL is not initialized")
            return

        if not somfy_cul.is_open():
            reopened = await hass.async_add_executor_job(somfy_cul.reload_connection)
            if not reopened:
                _LOGGER.error("Cannot send raw command; CUL connection closed")
                return
            callback = hass.data.get(DOMAIN, {}).get(DATA_RX_CALLBACK)
            if callback:
                await hass.async_add_executor_job(somfy_cul.start_listen, callback)

        command: str = call.data["command"]
        timeout: float = call.data.get("timeout", 2.0)

        rx_buffer_snapshot_index = len(rx_buffer)

        success = await hass.async_add_executor_job(somfy_cul.send_line, command)
        if not success:
            _LOGGER.error("Sending raw command failed: %s", command)
            return

        if timeout > 0:
            deadline = time.monotonic() + timeout
            while len(rx_buffer) == rx_buffer_snapshot_index and time.monotonic() < deadline:
                await asyncio.sleep(0.1)

        new_messages = []
        current_len = len(rx_buffer)
        if current_len > rx_buffer_snapshot_index:
            # copy to avoid holding reference while buffer mutates
            buffer_copy = list(rx_buffer)
            new_messages = buffer_copy[rx_buffer_snapshot_index:current_len]

        if new_messages:
            for msg in new_messages:
                _LOGGER.info("SOMFY CUL raw response: %s", msg)
        else:
            _LOGGER.info("SOMFY CUL raw command sent without immediate response: %s", command)

    hass.services.async_register(
        DOMAIN,
        SERVICE_RELOAD_PLATFORM,
        async_reload_platform_service,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_RAW_COMMAND,
        async_send_raw_service,
        schema=RAW_COMMAND_SERVICE_SCHEMA,
    )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
