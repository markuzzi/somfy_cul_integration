"""The Somfy CUL integration."""

from __future__ import annotations

import logging

from collections import deque
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers.dispatcher import dispatcher_send

from .const import CONF_BAUD_RATE, CONF_CUL_PATH, DATA_SOMFY_CUL, DOMAIN, SIGNAL_SOMFY_CUL_FRAME, CONF_DEBUG_RX, DATA_RX_BUFFER
from .cul import Cul


_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.COVER]

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
    hass.data[DOMAIN][DATA_SOMFY_CUL] = cul

    def _on_rx(line: str) -> None:
        rx_buffer.append(line)

        if debug_rx and _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("SOMFY CUL RX: %s", line)

        # entities could subscribe on this:
        dispatcher_send(hass, SIGNAL_SOMFY_CUL_FRAME, line)

    cul.start_listen(_on_rx)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
