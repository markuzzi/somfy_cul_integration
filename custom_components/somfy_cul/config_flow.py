"""Config flow for the Somfy CUL integration."""

from __future__ import annotations

import glob
import logging
import re
from types import MappingProxyType
from typing import Any

import voluptuous as vol

from homeassistant.components.cover import CoverDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryData,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    ATTR_DOWN_TIME,
    ATTR_UP_TIME,
    CONF_ADDRESS,
    CONF_BAUD_RATE,
    CONF_CUL_PATH,
    CONF_DEBUG_RX,
    CONF_DEVICE_CLASS,
    CONF_NAME,
    CONF_REVERSED,
    DEFAULT_BAUD_RATE,
    DEFAULT_CUL_PATH,
    DOMAIN,
    SUBENTRY_TYPE_COVER,
)
from .cul import Cul

_LOGGER = logging.getLogger(__name__)

ADDRESS_PATTERN = re.compile(r"[0-9A-F]{1,6}")
BAUD_RATES = [9600, 19200, 38400, 57600, 115200]


def _list_serial_ports() -> list[str]:
    """Return the serial ports of this machine (runs in the executor)."""
    ports: list[str] = sorted(glob.glob("/dev/serial/by-id/*"))
    try:
        from serial.tools import list_ports  # noqa: PLC0415

        ports.extend(p.device for p in list_ports.comports() if p.device not in ports)
    except Exception:  # noqa: BLE001
        pass
    for default in (DEFAULT_CUL_PATH, "/dev/ttyUSB0"):
        if default not in ports:
            ports.append(default)
    return ports


def _probe_cul(cul_path: str, baud_rate: int) -> str | None:
    """Open the CUL and query its version (runs in the executor).

    Raises ValueError if the port cannot be opened.
    """
    cul = Cul(cul_path, baud_rate)
    try:
        if not cul.is_open():
            raise ValueError(f"Cannot open {cul_path}")
        return cul.get_cul_version(attempts=3)
    finally:
        cul.close()


def normalize_address(address: str) -> str:
    """Return the address in upper case without whitespace.

    Raises ValueError for invalid addresses.
    """
    address = str(address).strip().upper()
    if not ADDRESS_PATTERN.fullmatch(address):
        raise ValueError(f"invalid Somfy address: {address!r}")
    return address


def cover_unique_id(address: str) -> str:
    """Return the unique id of a cover subentry (padded address)."""
    return normalize_address(address).zfill(6)


def _hub_schema(ports: list[str], defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_CUL_PATH, default=defaults.get(CONF_CUL_PATH, DEFAULT_CUL_PATH)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=ports,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_BAUD_RATE, default=defaults.get(CONF_BAUD_RATE, DEFAULT_BAUD_RATE)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[str(b) for b in BAUD_RATES],
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


COVER_OPTIONS_SCHEMA = {
    vol.Required(CONF_NAME): selector.TextSelector(),
    vol.Required(CONF_DEVICE_CLASS, default=CoverDeviceClass.SHUTTER): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[cls.value for cls in CoverDeviceClass],
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="cover_device_class",
            sort=True,
        )
    ),
    vol.Optional(ATTR_UP_TIME): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1, max=600, step=1, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX
        )
    ),
    vol.Optional(ATTR_DOWN_TIME): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1, max=600, step=1, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX
        )
    ),
    vol.Required(CONF_REVERSED, default=False): selector.BooleanSelector(),
}

COVER_SCHEMA = vol.Schema(
    {vol.Required(CONF_ADDRESS): selector.TextSelector(), **COVER_OPTIONS_SCHEMA}
)


def _clean_cover_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalize the cover data entered by the user."""
    data = dict(user_input)
    data[CONF_ADDRESS] = normalize_address(data[CONF_ADDRESS])
    data[CONF_NAME] = str(data[CONF_NAME]).strip()
    for key in (ATTR_UP_TIME, ATTR_DOWN_TIME):
        if data.get(key) is None:
            data.pop(key, None)
        else:
            data[key] = int(data[key])
    return data


def cover_subentry_data(cover: dict[str, Any]) -> ConfigSubentryData:
    """Build the subentry data of a cover."""
    data = _clean_cover_data(cover)
    return {
        "subentry_type": SUBENTRY_TYPE_COVER,
        "title": data[CONF_NAME],
        "unique_id": cover_unique_id(data[CONF_ADDRESS]),
        "data": MappingProxyType(data),
    }


class SomfyCulConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow of the CUL hub."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry flows."""
        return {SUBENTRY_TYPE_COVER: CoverSubentryFlowHandler}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return SomfyCulOptionsFlowHandler()

    async def _async_validate_hub(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Try to connect to the CUL. Return the errors, if any."""
        cul_path = str(user_input[CONF_CUL_PATH]).strip()
        try:
            baud_rate = int(user_input[CONF_BAUD_RATE])
        except (TypeError, ValueError):
            return {CONF_BAUD_RATE: "invalid_baud_rate"}
        user_input[CONF_CUL_PATH] = cul_path
        user_input[CONF_BAUD_RATE] = baud_rate

        try:
            version = await self.hass.async_add_executor_job(_probe_cul, cul_path, baud_rate)
        except ValueError:
            return {CONF_CUL_PATH: "cannot_connect"}
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error while probing CUL at %s", cul_path)
            return {"base": "unknown"}

        if version:
            _LOGGER.debug("Found CUL %s at %s", version, cul_path)
        else:
            # The port exists but the CUL did not answer. Sending may work
            # anyway (see issue #5), so this is not an error.
            _LOGGER.warning("CUL at %s did not answer the version query", cul_path)
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up the hub."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_validate_hub(user_input)
            if not errors:
                return self.async_create_entry(
                    title=f"Somfy CUL ({user_input[CONF_CUL_PATH]})", data=user_input
                )

        ports = await self.hass.async_add_executor_job(_list_serial_ports)
        return self.async_show_form(
            step_id="user", data_schema=_hub_schema(ports, user_input), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the serial port of the hub."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_validate_hub(user_input)
            if not errors:
                return self.async_update_and_abort(
                    entry,
                    title=f"Somfy CUL ({user_input[CONF_CUL_PATH]})",
                    data_updates=user_input,
                )

        ports = await self.hass.async_add_executor_job(_list_serial_ports)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_hub_schema(ports, user_input or dict(entry.data)),
            errors=errors,
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Import the YAML configuration.

        The hub is imported once. Covers that are not configured yet are
        added to the existing entry, so covers can still be added in YAML.
        Existing covers are not changed, since they may have been edited
        in the UI.
        """
        hub: dict[str, Any] = import_data["hub"]
        covers: list[dict[str, Any]] = import_data["covers"]

        subentries: list[ConfigSubentryData] = []
        for cover in covers:
            try:
                subentries.append(cover_subentry_data(cover))
            except ValueError as e:
                _LOGGER.error("Cover %s not imported: %s", cover.get(CONF_NAME), e)

        if entries := self._async_current_entries():
            entry = entries[0]
            existing = {s.unique_id for s in entry.subentries.values()}
            for subentry in subentries:
                if subentry["unique_id"] in existing:
                    continue
                _LOGGER.info("Adding cover %s from YAML", subentry["title"])
                self.hass.config_entries.async_add_subentry(
                    entry,
                    ConfigSubentry(
                        data=subentry["data"],
                        subentry_type=subentry["subentry_type"],
                        title=subentry["title"],
                        unique_id=subentry["unique_id"],
                    ),
                )
                existing.add(subentry["unique_id"])
            return self.async_abort(reason="already_configured")

        cul_path = str(hub.get(CONF_CUL_PATH, DEFAULT_CUL_PATH))
        return self.async_create_entry(
            title=f"Somfy CUL ({cul_path})",
            data={
                CONF_CUL_PATH: cul_path,
                CONF_BAUD_RATE: int(hub.get(CONF_BAUD_RATE, DEFAULT_BAUD_RATE)),
            },
            options={CONF_DEBUG_RX: bool(hub.get(CONF_DEBUG_RX, False))},
            subentries=subentries,
        )


class SomfyCulOptionsFlowHandler(OptionsFlow):
    """Handle the options of the hub."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_DEBUG_RX, default=False): bool}),
                self.config_entry.options,
            ),
        )


class CoverSubentryFlowHandler(ConfigSubentryFlow):
    """Handle adding and reconfiguring a cover."""

    def _validate(
        self, user_input: dict[str, Any], current: ConfigSubentry | None = None
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Validate the cover data. Return the cleaned data and the errors."""
        try:
            data = _clean_cover_data(user_input)
        except ValueError:
            return None, {CONF_ADDRESS: "invalid_address"}

        if not data[CONF_NAME]:
            return None, {CONF_NAME: "invalid_name"}

        unique_id = cover_unique_id(data[CONF_ADDRESS])
        for subentry in self._get_entry().subentries.values():
            if subentry is current:
                continue
            if subentry.unique_id == unique_id:
                return None, {CONF_ADDRESS: "already_configured"}

        return data, {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a cover."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = self._validate(user_input)
            if data is not None:
                return self.async_create_entry(
                    title=data[CONF_NAME],
                    data=data,
                    unique_id=cover_unique_id(data[CONF_ADDRESS]),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(COVER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change a cover."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = self._validate(user_input, subentry)
            if data is not None:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=data[CONF_NAME],
                    data=data,
                    unique_id=cover_unique_id(data[CONF_ADDRESS]),
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                COVER_SCHEMA, user_input or dict(subentry.data)
            ),
            errors=errors,
            description_placeholders={CONF_ADDRESS: subentry.data[CONF_ADDRESS]},
        )

