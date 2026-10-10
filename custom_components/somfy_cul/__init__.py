"""The Somfy CUL integration."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_IMPORT,
    ConfigEntry,
    ConfigEntryState,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_BAUD_RATE,
    CONF_CUL_PATH,
    CONF_DEBUG_RX,
    DEFAULT_BAUD_RATE,
    DEFAULT_CUL_PATH,
    DOMAIN,
    PLATFORMS,
    SERVICE_RELOAD_PLATFORM,
    SERVICE_SEND_RAW_COMMAND,
    SIGNAL_SOMFY_CUL_FRAME,
)
from .cul import Cul

_LOGGER = logging.getLogger(__name__)

RAW_COMMAND_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("command"): cv.string,
        vol.Optional("timeout", default=2.0): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)

# YAML configuration is still supported; it is imported into a config entry.
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: {
            vol.Optional(CONF_CUL_PATH, default=DEFAULT_CUL_PATH): cv.string,
            vol.Optional(CONF_BAUD_RATE, default=DEFAULT_BAUD_RATE): vol.Coerce(int),
            vol.Optional(CONF_DEBUG_RX, default=False): cv.boolean,
        }
    },
    extra=vol.ALLOW_EXTRA,
)


@dataclass
class SomfyCulData:
    """Runtime data of a config entry."""

    cul: Cul
    rx_buffer: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    # total number of received lines; the buffer length stops growing at maxlen
    rx_count: int = 0
    rx_callback: Any = None


type SomfyCulConfigEntry = ConfigEntry[SomfyCulData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the services and import the YAML configuration."""
    _async_register_services(hass)

    if DOMAIN not in config:
        return True

    hass.async_create_task(_async_import_yaml(hass, config))
    return True


async def _async_import_yaml(hass: HomeAssistant, config: ConfigType) -> None:
    """Import the hub and the covers configured in YAML."""
    # Platform imports here to avoid a circular import
    from .cover import async_get_yaml_covers  # noqa: PLC0415

    import_data = {
        "hub": dict(config[DOMAIN]),
        "covers": async_get_yaml_covers(config),
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=import_data
    )

    if result.get("type") is FlowResultType.ABORT and result.get("reason") not in (
        "already_configured",
        "single_instance_allowed",
    ):
        async_create_issue(
            hass,
            DOMAIN,
            f"yaml_import_failed_{result.get('reason')}",
            is_fixable=False,
            issue_domain=DOMAIN,
            severity=IssueSeverity.ERROR,
            translation_key="yaml_import_failed",
            translation_placeholders={
                "reason": str(result.get("reason")),
                "cul_path": str(import_data["hub"].get(CONF_CUL_PATH)),
            },
        )
        return

    async_create_issue(
        hass,
        DOMAIN,
        "yaml_imported",
        is_fixable=False,
        issue_domain=DOMAIN,
        severity=IssueSeverity.WARNING,
        translation_key="yaml_imported",
    )


async def async_setup_entry(hass: HomeAssistant, entry: SomfyCulConfigEntry) -> bool:
    """Set up the CUL from a config entry."""
    cul_path: str = entry.data[CONF_CUL_PATH]
    baud_rate = int(entry.data.get(CONF_BAUD_RATE, DEFAULT_BAUD_RATE))
    debug_rx = bool(entry.options.get(CONF_DEBUG_RX, False))

    try:
        cul = await hass.async_add_executor_job(Cul, cul_path, baud_rate)
    except ValueError as e:
        raise ConfigEntryNotReady(f"Could not connect to CUL at {cul_path}: {e}") from e

    version = await hass.async_add_executor_job(cul.get_cul_version)
    if version:
        _LOGGER.info(
            "SOMFY CUL connected (%s) at %s, baud %d", version, cul_path, baud_rate
        )
    else:
        # Do not fail the setup. Sending may work anyway and the listener
        # reconnects in the background. Use somfy_cul.reload_platform to retry.
        _LOGGER.warning("Could not read CUL version at %s; continuing anyway", cul_path)

    data = SomfyCulData(cul=cul)

    def _on_rx(line: str) -> None:
        data.rx_buffer.append(line)
        data.rx_count += 1

        if debug_rx and _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("SOMFY CUL RX: %s", line)

        # entities could subscribe on this:
        dispatcher_send(hass, SIGNAL_SOMFY_CUL_FRAME, line)

    data.rx_callback = _on_rx
    cul.start_listen(_on_rx)
    entry.runtime_data = data

    async def _on_ha_stop(_event) -> None:
        await _async_close(hass, cul, cul_path)

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_ha_stop))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SomfyCulConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await _async_close(hass, entry.runtime_data.cul, entry.data[CONF_CUL_PATH])
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: SomfyCulConfigEntry) -> None:
    """Reload the entry when the options changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_close(hass: HomeAssistant, cul: Cul, cul_path: str) -> None:
    try:
        await hass.async_add_executor_job(cul.close)
        _LOGGER.info("SOMFY CUL at %s closed.", cul_path)
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("Error while closing CUL: %s", e)


def _get_loaded_entry(hass: HomeAssistant) -> SomfyCulConfigEntry:
    """Return the loaded config entry or raise a service error."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="not_initialized"
    )


async def _async_reconnect(hass: HomeAssistant, data: SomfyCulData) -> bool:
    """Reopen the connection and restart the listener."""
    reopened = await hass.async_add_executor_job(data.cul.reload_connection)
    if reopened and data.rx_callback:
        await hass.async_add_executor_job(data.cul.start_listen, data.rx_callback)
    return reopened


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the hub services."""
    if hass.services.has_service(DOMAIN, SERVICE_RELOAD_PLATFORM):
        return

    async def async_reload_platform_service(_call: ServiceCall) -> None:
        data = _get_loaded_entry(hass).runtime_data

        if not await _async_reconnect(hass, data):
            _LOGGER.error("Could not reopen SOMFY CUL connection")
            return

        version = await hass.async_add_executor_job(data.cul.get_cul_version)
        if version:
            _LOGGER.info("SOMFY CUL reloaded (%s)", version)
        else:
            _LOGGER.warning("SOMFY CUL reloaded but version could not be read")

    async def async_send_raw_service(call: ServiceCall) -> None:
        data = _get_loaded_entry(hass).runtime_data

        if not data.cul.is_open() and not await _async_reconnect(hass, data):
            _LOGGER.error("Cannot send raw command; CUL connection closed")
            return

        command: str = call.data["command"]
        timeout: float = call.data.get("timeout", 2.0)

        rx_count_before = data.rx_count

        success = await hass.async_add_executor_job(data.cul.send_line, command)
        if not success:
            _LOGGER.error("Sending raw command failed: %s", command)
            return

        if timeout > 0:
            deadline = time.monotonic() + timeout
            while data.rx_count == rx_count_before and time.monotonic() < deadline:  # noqa: ASYNC110
                await asyncio.sleep(0.1)

        new_count = min(data.rx_count - rx_count_before, len(data.rx_buffer))
        new_messages = list(data.rx_buffer)[-new_count:] if new_count else []

        if new_messages:
            for msg in new_messages:
                _LOGGER.info("SOMFY CUL raw response: %s", msg)
        else:
            _LOGGER.info("SOMFY CUL raw command sent without immediate response: %s", command)

    hass.services.async_register(DOMAIN, SERVICE_RELOAD_PLATFORM, async_reload_platform_service)
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_RAW_COMMAND,
        async_send_raw_service,
        schema=RAW_COMMAND_SERVICE_SCHEMA,
    )
