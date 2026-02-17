"""Config flow for RO Auto."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (BooleanSelector, NumberSelector,
                                            NumberSelectorConfig,
                                            NumberSelectorMode, SelectSelector,
                                            SelectSelectorConfig,
                                            SelectSelectorMode, TextSelector,
                                            TextSelectorConfig)

from .const import (CONF_ACTION, CONF_ADD_ANOTHER, CONF_ENABLE_ITP,
                    CONF_ENABLE_RCA, CONF_FLEET_NAME, CONF_ITP_API_URL,
                    CONF_ITP_PASSWORD, CONF_ITP_USERNAME, CONF_MAKE,
                    CONF_MODEL, CONF_RCA_API_URL, CONF_RCA_PASSWORD,
                    CONF_RCA_USERNAME, CONF_REGISTRATION_NUMBER, CONF_VEHICLES,
                    CONF_VIN, CONF_YEAR, DEFAULT_NAME, DOMAIN)
from .helpers import get_vehicles_for_entry

ACTIONS_ADD_VEHICLE = "add_vehicle"
ACTIONS_REMOVE_VEHICLE = "remove_vehicle"

_LOGGER = logging.getLogger(__name__)


def _year_max() -> int:
    """Return a reasonable max year."""
    return datetime.now(tz=UTC).year + 1


def _vehicle_schema(*, include_add_another: bool) -> vol.Schema:
    """Create a schema for collecting one vehicle."""
    schema: dict[vol.Marker, Any] = {
        vol.Required(CONF_NAME): TextSelector(
            TextSelectorConfig(autocomplete="name", type="text")
        ),
        vol.Required(CONF_MAKE): TextSelector(
            TextSelectorConfig(autocomplete="organization-title", type="text")
        ),
        vol.Required(CONF_MODEL): TextSelector(TextSelectorConfig(type="text")),
        vol.Required(CONF_YEAR): NumberSelector(
            NumberSelectorConfig(
                min=1950,
                max=_year_max(),
                step=1,
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_VIN): TextSelector(
            TextSelectorConfig(autocomplete="off", type="text")
        ),
        vol.Required(CONF_REGISTRATION_NUMBER): TextSelector(
            TextSelectorConfig(autocomplete="off", type="text")
        ),
    }
    if include_add_another:
        schema[vol.Optional(CONF_ADD_ANOTHER, default=False)] = BooleanSelector()
    return vol.Schema(schema)


def _initial_schema() -> vol.Schema:
    """Create a schema for initial flow step."""
    schema: dict[vol.Marker, Any] = {
        vol.Optional(CONF_FLEET_NAME, default=DEFAULT_NAME): TextSelector(
            TextSelectorConfig(type="text")
        ),
        vol.Optional(CONF_ENABLE_RCA, default=False): BooleanSelector(),
        vol.Optional(CONF_RCA_API_URL): TextSelector(TextSelectorConfig(type="text")),
        vol.Optional(CONF_RCA_USERNAME): TextSelector(TextSelectorConfig(type="text")),
        vol.Optional(CONF_RCA_PASSWORD): TextSelector(TextSelectorConfig(type="password")),
        vol.Optional(CONF_ENABLE_ITP, default=False): BooleanSelector(),
        vol.Optional(CONF_ITP_API_URL): TextSelector(TextSelectorConfig(type="text")),
        vol.Optional(CONF_ITP_USERNAME): TextSelector(TextSelectorConfig(type="text")),
        vol.Optional(CONF_ITP_PASSWORD): TextSelector(TextSelectorConfig(type="password")),
    }
    schema.update(_vehicle_schema(include_add_another=True).schema)
    return vol.Schema(schema)


def _normalize_vehicle(vehicle: dict[str, Any]) -> dict[str, Any]:
    """Normalize one vehicle payload."""
    normalized = {
        CONF_NAME: str(vehicle[CONF_NAME]).strip(),
        CONF_MAKE: str(vehicle[CONF_MAKE]).strip(),
        CONF_MODEL: str(vehicle[CONF_MODEL]).strip(),
        CONF_YEAR: int(vehicle[CONF_YEAR]),
        CONF_VIN: str(vehicle[CONF_VIN]).strip().upper(),
        CONF_REGISTRATION_NUMBER: str(vehicle[CONF_REGISTRATION_NUMBER]).strip().upper(),
    }
    return normalized


class RoAutoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for RO Auto."""

    VERSION = 1
    MINOR_VERSION = 0

    def __init__(self) -> None:
        """Initialize flow."""
        self._vehicles: list[dict[str, Any]] = []
        self._fleet_name = DEFAULT_NAME
        self._rca_settings: dict[str, Any] = {}
        self._itp_settings: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the first step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._fleet_name = str(user_input.pop(CONF_FLEET_NAME, DEFAULT_NAME)).strip()
            enable_rca = bool(user_input.pop(CONF_ENABLE_RCA, False))
            rca_api_url = str(user_input.pop(CONF_RCA_API_URL, "")).strip()
            rca_username = str(user_input.pop(CONF_RCA_USERNAME, "")).strip()
            rca_password = str(user_input.pop(CONF_RCA_PASSWORD, "")).strip()

            enable_itp = bool(user_input.pop(CONF_ENABLE_ITP, False))
            itp_api_url = str(user_input.pop(CONF_ITP_API_URL, "")).strip()
            itp_username = str(user_input.pop(CONF_ITP_USERNAME, "")).strip()
            itp_password = str(user_input.pop(CONF_ITP_PASSWORD, "")).strip()

            if enable_rca and (not rca_api_url or not rca_username or not rca_password):
                errors["base"] = "missing_rca_settings"
            elif enable_itp and (not itp_api_url or not itp_username or not itp_password):
                errors["base"] = "missing_itp_settings"
            else:
                self._rca_settings = {
                    CONF_ENABLE_RCA: enable_rca,
                    CONF_RCA_API_URL: rca_api_url,
                    CONF_RCA_USERNAME: rca_username,
                    CONF_RCA_PASSWORD: rca_password,
                }
                self._itp_settings = {
                    CONF_ENABLE_ITP: enable_itp,
                    CONF_ITP_API_URL: itp_api_url,
                    CONF_ITP_USERNAME: itp_username,
                    CONF_ITP_PASSWORD: itp_password,
                }
            vehicle = _normalize_vehicle(user_input)
            duplicate_vin = any(existing[CONF_VIN] == vehicle[CONF_VIN] for existing in self._vehicles)

            if errors:
                pass
            elif duplicate_vin:
                errors["base"] = "duplicate_vehicle"
            else:
                self._vehicles.append(vehicle)
                if user_input.get(CONF_ADD_ANOTHER):
                    return await self.async_step_add_vehicle()
                return self._async_create_entry()

        return self.async_show_form(
            step_id="user",
            data_schema=_initial_schema(),
            errors=errors,
        )

    async def async_step_add_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle adding additional vehicles."""
        errors: dict[str, str] = {}

        if user_input is not None:
            vehicle = _normalize_vehicle(user_input)
            duplicate_vin = any(existing[CONF_VIN] == vehicle[CONF_VIN] for existing in self._vehicles)

            if duplicate_vin:
                errors["base"] = "duplicate_vehicle"
            else:
                self._vehicles.append(vehicle)
                if user_input.get(CONF_ADD_ANOTHER):
                    return await self.async_step_add_vehicle()
                return self._async_create_entry()

        return self.async_show_form(
            step_id="add_vehicle",
            data_schema=_vehicle_schema(include_add_another=True),
            errors=errors,
        )

    def _async_create_entry(self) -> config_entries.ConfigFlowResult:
        """Create the config entry."""
        title = self._fleet_name or (self._vehicles[0][CONF_NAME] if self._vehicles else DEFAULT_NAME)
        return self.async_create_entry(
            title=title,
            data={
                CONF_VEHICLES: self._vehicles,
                **self._rca_settings,
                **self._itp_settings,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "RoAutoOptionsFlow":
        """Get the options flow for this handler."""
        return RoAutoOptionsFlow(config_entry)


class RoAutoOptionsFlow(config_entries.OptionsFlow):
    """Handle RO Auto options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage vehicle actions."""
        vehicles = get_vehicles_for_entry(self._config_entry)
        menu_options = [ACTIONS_ADD_VEHICLE]
        if vehicles:
            menu_options.append(ACTIONS_REMOVE_VEHICLE)
        menu_options.append("rca_settings")
        menu_options.append("trigger_rca_refresh")
        menu_options.append("itp_settings")
        menu_options.append("trigger_itp_refresh")

        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_itp_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure ITP settings from options flow."""
        return await self._async_step_api_settings(
            step_id="itp_settings",
            user_input=user_input,
            enable_key=CONF_ENABLE_ITP,
            url_key=CONF_ITP_API_URL,
            username_key=CONF_ITP_USERNAME,
            password_key=CONF_ITP_PASSWORD,
            missing_error="missing_itp_settings",
        )

    async def async_step_rca_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure RCA settings from options flow."""
        return await self._async_step_api_settings(
            step_id="rca_settings",
            user_input=user_input,
            enable_key=CONF_ENABLE_RCA,
            url_key=CONF_RCA_API_URL,
            username_key=CONF_RCA_USERNAME,
            password_key=CONF_RCA_PASSWORD,
            missing_error="missing_rca_settings",
        )

    async def _async_step_api_settings(
        self,
        *,
        step_id: str,
        user_input: dict[str, Any] | None,
        enable_key: str,
        url_key: str,
        username_key: str,
        password_key: str,
        missing_error: str,
    ) -> config_entries.ConfigFlowResult:
        """Generic API settings handler for options flow (RCA/ITP)."""
        schema = self._api_settings_schema(
            enable_key=enable_key,
            url_key=url_key,
            username_key=username_key,
            password_key=password_key,
        )

        if user_input is None:
            return self.async_show_form(step_id=step_id, data_schema=schema)

        current = self._config_entry.options | self._config_entry.data
        enabled = bool(user_input.get(enable_key, current.get(enable_key, False)))
        api_url = str(user_input.get(url_key, current.get(url_key, "")) or "").strip()
        username = str(user_input.get(username_key, current.get(username_key, "")) or "").strip()
        password = str(user_input.get(password_key, "") or "").strip() or str(
            current.get(password_key, "") or ""
        )

        errors: dict[str, str] = {}
        if enabled and (not api_url or not username or not password):
            errors["base"] = missing_error
        if errors:
            return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

        return self.async_create_entry(
            title="",
            data={
                **self._config_entry.options,
                enable_key: enabled,
                url_key: api_url,
                username_key: username,
                password_key: password,
            },
        )

    def _api_settings_schema(
        self,
        *,
        enable_key: str,
        url_key: str,
        username_key: str,
        password_key: str,
    ) -> vol.Schema:
        """Build a schema for a Basic-auth API settings step."""
        current = self._config_entry.options | self._config_entry.data
        return vol.Schema(
            {
                vol.Optional(enable_key, default=bool(current.get(enable_key, False))): BooleanSelector(),
                vol.Optional(url_key, default=str(current.get(url_key, "") or "")): TextSelector(
                    TextSelectorConfig(type="text")
                ),
                vol.Optional(username_key, default=str(current.get(username_key, "") or "")): TextSelector(
                    TextSelectorConfig(type="text")
                ),
                # We cannot safely show the existing password; user can re-enter to change it.
                vol.Optional(password_key): TextSelector(TextSelectorConfig(type="password")),
            }
        )

    async def async_step_trigger_rca_refresh(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Trigger a manual RCA refresh from options menu."""
        await self._async_trigger_manual_refresh(source="RCA")
        return self.async_create_entry(title="", data={**self._config_entry.options})

    async def async_step_trigger_itp_refresh(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Trigger a manual ITP refresh from options menu."""
        await self._async_trigger_manual_refresh(source="ITP")
        return self.async_create_entry(title="", data={**self._config_entry.options})

    async def _async_trigger_manual_refresh(self, *, source: str) -> None:
        """Trigger a manual refresh for the existing coordinator."""
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
        if coordinator is None:
            _LOGGER.warning("Manual %s refresh requested, but coordinator was not found", source)
            return

        if source == "RCA":
            await coordinator.async_manual_refresh_rca()
            return
        if source == "ITP":
            await coordinator.async_manual_refresh_itp()
            return

        _LOGGER.warning("Unknown manual refresh source: %s", source)

    async def async_step_add_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Add a vehicle from options flow."""
        errors: dict[str, str] = {}
        vehicles = get_vehicles_for_entry(self._config_entry)

        if user_input is not None:
            vehicle = _normalize_vehicle(user_input)
            duplicate_vin = any(existing[CONF_VIN] == vehicle[CONF_VIN] for existing in vehicles)
            if duplicate_vin:
                errors["base"] = "duplicate_vehicle"
            else:
                vehicles.append(vehicle)
                return self.async_create_entry(
                    title="",
                    data={**self._config_entry.options, CONF_VEHICLES: vehicles},
                )

        return self.async_show_form(
            step_id="add_vehicle",
            data_schema=_vehicle_schema(include_add_another=False),
            errors=errors,
        )

    async def async_step_remove_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Remove a vehicle from options flow."""
        vehicles = get_vehicles_for_entry(self._config_entry)
        options = [
            {
                "value": vehicle[CONF_VIN],
                "label": f"{vehicle[CONF_NAME]} ({vehicle[CONF_REGISTRATION_NUMBER]})",
            }
            for vehicle in vehicles
        ]

        if user_input is not None:
            selected_vin = str(user_input[CONF_ACTION])
            new_vehicles = [vehicle for vehicle in vehicles if vehicle[CONF_VIN] != selected_vin]
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, CONF_VEHICLES: new_vehicles},
            )

        return self.async_show_form(
            step_id="remove_vehicle",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACTION): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )
