"""Config flow for RO Auto."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_MAKE, CONF_MODEL, CONF_NAME, CONF_VIN, CONF_YEAR
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

from . import get_cars_for_entry
from .const import (
    CONF_ACTION,
    CONF_ADD_ANOTHER,
    CONF_CARS,
    CONF_FLEET_NAME,
    DEFAULT_NAME,
    DOMAIN,
)

CONF_REGISTRATION_NUMBER = "registrationNumber"

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
        )
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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the first step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._fleet_name = str(user_input.pop(CONF_FLEET_NAME, DEFAULT_NAME)).strip()
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
        return self.async_create_entry(title=title, data={CONF_CARS: self._cars})

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

        return self.async_show_menu(step_id="init", menu_options=menu_options)

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
