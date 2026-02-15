"""Config flow for RO Auto."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_ACTION,
    CONF_ADD_ANOTHER,
    CONF_CARS,
    CONF_ENABLE_RCA,
    CONF_FLEET_NAME,
    CONF_MAKE,
    CONF_MODEL,
    CONF_RCA_API_URL,
    CONF_RCA_PASSWORD,
    CONF_RCA_USERNAME,
    CONF_REGISTRATION_NUMBER,
    CONF_VIN,
    CONF_YEAR,
    DEFAULT_NAME,
    DOMAIN,
)
from .helpers import get_cars_for_entry

ACTIONS_ADD_CAR = "add_car"
ACTIONS_REMOVE_CAR = "remove_car"


def _year_max() -> int:
    """Return a reasonable max year."""
    return datetime.now(tz=UTC).year + 1


def _car_schema(*, include_add_another: bool) -> vol.Schema:
    """Create a schema for collecting one car."""
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
    }
    schema.update(_car_schema(include_add_another=True).schema)
    return vol.Schema(schema)


def _normalize_car(car: dict[str, Any]) -> dict[str, Any]:
    """Normalize one car payload."""
    normalized = {
        CONF_NAME: str(car[CONF_NAME]).strip(),
        CONF_MAKE: str(car[CONF_MAKE]).strip(),
        CONF_MODEL: str(car[CONF_MODEL]).strip(),
        CONF_YEAR: int(car[CONF_YEAR]),
        CONF_VIN: str(car[CONF_VIN]).strip().upper(),
        CONF_REGISTRATION_NUMBER: str(car[CONF_REGISTRATION_NUMBER]).strip().upper(),
    }
    return normalized


class RoAutoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for RO Auto."""

    VERSION = 1
    MINOR_VERSION = 0

    def __init__(self) -> None:
        """Initialize flow."""
        self._cars: list[dict[str, Any]] = []
        self._fleet_name = DEFAULT_NAME
        self._rca_settings: dict[str, Any] = {}

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

            if enable_rca and (not rca_api_url or not rca_username or not rca_password):
                errors["base"] = "missing_rca_settings"
            else:
                self._rca_settings = {
                    CONF_ENABLE_RCA: enable_rca,
                    CONF_RCA_API_URL: rca_api_url,
                    CONF_RCA_USERNAME: rca_username,
                    CONF_RCA_PASSWORD: rca_password,
                }
            car = _normalize_car(user_input)
            duplicate_vin = any(existing[CONF_VIN] == car[CONF_VIN] for existing in self._cars)

            if errors:
                pass
            elif duplicate_vin:
                errors["base"] = "duplicate_car"
            else:
                self._cars.append(car)
                if user_input.get(CONF_ADD_ANOTHER):
                    return await self.async_step_add_car()
                return self._async_create_entry()

        return self.async_show_form(
            step_id="user",
            data_schema=_initial_schema(),
            errors=errors,
        )

    async def async_step_add_car(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle adding additional cars."""
        errors: dict[str, str] = {}

        if user_input is not None:
            car = _normalize_car(user_input)
            duplicate_vin = any(existing[CONF_VIN] == car[CONF_VIN] for existing in self._cars)

            if duplicate_vin:
                errors["base"] = "duplicate_car"
            else:
                self._cars.append(car)
                if user_input.get(CONF_ADD_ANOTHER):
                    return await self.async_step_add_car()
                return self._async_create_entry()

        return self.async_show_form(
            step_id="add_car",
            data_schema=_car_schema(include_add_another=True),
            errors=errors,
        )

    def _async_create_entry(self) -> config_entries.ConfigFlowResult:
        """Create the config entry."""
        title = self._fleet_name or (self._cars[0][CONF_NAME] if self._cars else DEFAULT_NAME)
        return self.async_create_entry(
            title=title,
            data={
                CONF_CARS: self._cars,
                **self._rca_settings,
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
        """Manage car actions."""
        cars = get_cars_for_entry(self._config_entry)
        menu_options = [ACTIONS_ADD_CAR]
        if cars:
            menu_options.append(ACTIONS_REMOVE_CAR)
        menu_options.append("rca_settings")

        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_rca_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure RCA settings from options flow."""
        if user_input is not None:
            current = self._config_entry.options | self._config_entry.data
            enable_rca = bool(user_input.get(CONF_ENABLE_RCA, current.get(CONF_ENABLE_RCA, False)))
            api_url = str(user_input.get(CONF_RCA_API_URL, current.get(CONF_RCA_API_URL, "")) or "").strip()
            username = str(user_input.get(CONF_RCA_USERNAME, current.get(CONF_RCA_USERNAME, "")) or "").strip()
            # If empty, keep the existing password.
            password = str(user_input.get(CONF_RCA_PASSWORD, "") or "").strip() or str(
                current.get(CONF_RCA_PASSWORD, "") or ""
            )

            errors: dict[str, str] = {}
            if enable_rca and (not api_url or not username or not password):
                errors["base"] = "missing_rca_settings"
            if errors:
                return self.async_show_form(
                    step_id="rca_settings",
                    data_schema=self._rca_schema(),
                    errors=errors,
                )

            return self.async_create_entry(
                title="",
                data={
                    CONF_ENABLE_RCA: enable_rca,
                    CONF_RCA_API_URL: api_url,
                    CONF_RCA_USERNAME: username,
                    CONF_RCA_PASSWORD: password,
                },
            )

        return self.async_show_form(
            step_id="rca_settings",
            data_schema=self._rca_schema(),
        )

    def _rca_schema(self) -> vol.Schema:
        """RCA settings schema."""
        current = self._config_entry.options | self._config_entry.data
        return vol.Schema(
            {
                vol.Optional(CONF_ENABLE_RCA, default=bool(current.get(CONF_ENABLE_RCA, False))): BooleanSelector(),
                vol.Optional(CONF_RCA_API_URL, default=str(current.get(CONF_RCA_API_URL, "") or "")): TextSelector(
                    TextSelectorConfig(type="text")
                ),
                vol.Optional(CONF_RCA_USERNAME, default=str(current.get(CONF_RCA_USERNAME, "") or "")): TextSelector(
                    TextSelectorConfig(type="text")
                ),
                # We cannot safely show the existing password; user can re-enter to change it.
                vol.Optional(CONF_RCA_PASSWORD): TextSelector(TextSelectorConfig(type="password")),
            }
        )

    async def async_step_add_car(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Add a car from options flow."""
        errors: dict[str, str] = {}
        cars = get_cars_for_entry(self._config_entry)

        if user_input is not None:
            car = _normalize_car(user_input)
            duplicate_vin = any(existing[CONF_VIN] == car[CONF_VIN] for existing in cars)
            if duplicate_vin:
                errors["base"] = "duplicate_car"
            else:
                cars.append(car)
                return self.async_create_entry(title="", data={CONF_CARS: cars})

        return self.async_show_form(
            step_id="add_car",
            data_schema=_car_schema(include_add_another=False),
            errors=errors,
        )

    async def async_step_remove_car(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Remove a car from options flow."""
        cars = get_cars_for_entry(self._config_entry)
        options = [
            {
                "value": car[CONF_VIN],
                "label": f"{car[CONF_NAME]} ({car[CONF_REGISTRATION_NUMBER]})",
            }
            for car in cars
        ]

        if user_input is not None:
            selected_vin = str(user_input[CONF_ACTION])
            new_cars = [car for car in cars if car[CONF_VIN] != selected_vin]
            return self.async_create_entry(title="", data={CONF_CARS: new_cars})

        return self.async_show_form(
            step_id="remove_car",
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
