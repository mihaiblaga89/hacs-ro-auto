"""Sensor platform for RO Auto."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_MAKE,
    CONF_MODEL,
    CONF_REGISTRATION_NUMBER,
    CONF_VIN,
    CONF_YEAR,
    DOMAIN,
)
from .coordinator import RoAutoCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up RO Auto sensors from a config entry."""
    coordinator: RoAutoCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    for car in coordinator.cars:
        entities.append(RoAutoCarVignetteStatusSensor(coordinator, entry, car))
        entities.append(RoAutoCarVignetteExpirySensor(coordinator, entry, car))
    async_add_entities(entities)


class RoAutoCarBaseSensor(CoordinatorEntity[RoAutoCoordinator], SensorEntity):
    """Base sensor for a configured car."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: RoAutoCoordinator, entry: ConfigEntry, car: dict[str, Any]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._vin = str(car[CONF_VIN]).upper()
        self._registration_number = str(car[CONF_REGISTRATION_NUMBER]).upper()
        self._entry_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._vin)},
            name=car[CONF_NAME],
            manufacturer=car[CONF_MAKE],
            model=car[CONF_MODEL],
            serial_number=self._vin,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._vin in self.coordinator.data

    def _common_attributes(self) -> dict[str, Any]:
        """Return attributes shared by all car sensors."""
        car_data = self.coordinator.data.get(self._vin, {})
        return {
            CONF_NAME: car_data.get(CONF_NAME),
            CONF_MAKE: car_data.get(CONF_MAKE),
            CONF_MODEL: car_data.get(CONF_MODEL),
            CONF_YEAR: car_data.get(CONF_YEAR),
            CONF_VIN: car_data.get(CONF_VIN, self._vin),
            CONF_REGISTRATION_NUMBER: car_data.get(
                CONF_REGISTRATION_NUMBER, self._registration_number
            ),
            "vignetteValid": car_data.get("vignetteValid"),
            "vignetteExpiryDate": car_data.get("vignetteExpiryDate"),
            "nrAuto": car_data.get(CONF_REGISTRATION_NUMBER, self._registration_number),
            "serieSasiu": car_data.get(CONF_VIN, self._vin),
            "dataStop": car_data.get("dataStop"),
        }


class RoAutoCarVignetteStatusSensor(RoAutoCarBaseSensor):
    """Sensor exposing vignette validity status."""

    def __init__(
        self, coordinator: RoAutoCoordinator, entry: ConfigEntry, car: dict[str, Any]
    ) -> None:
        """Initialize the vignette status sensor."""
        super().__init__(coordinator, entry, car)
        self._attr_unique_id = f"{self._entry_id}_{self._vin}_vignette"
        self._attr_name = "vignette"
        self._attr_icon = "mdi:car-info"

    @property
    def native_value(self) -> str:
        """Return current vignette status."""
        car_data = self.coordinator.data.get(self._vin, {})
        valid = car_data.get("vignetteValid")
        if valid is True:
            return "valid"
        if valid is False:
            return "invalid"
        return "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full car and vignette details."""
        return self._common_attributes()


class RoAutoCarVignetteExpirySensor(RoAutoCarBaseSensor):
    """Sensor exposing vignette expiry date."""

    def __init__(
        self, coordinator: RoAutoCoordinator, entry: ConfigEntry, car: dict[str, Any]
    ) -> None:
        """Initialize the vignette expiry sensor."""
        super().__init__(coordinator, entry, car)
        self._attr_unique_id = f"{self._entry_id}_{self._vin}_vignette_expiry_date"
        self._attr_name = "vignette expiry date"
        self._attr_icon = "mdi:calendar-clock"

    @property
    def native_value(self) -> str | None:
        """Return vignette expiry date as provided by API."""
        car_data = self.coordinator.data.get(self._vin, {})
        expiry_date = car_data.get("vignetteExpiryDate")
        if not expiry_date:
            return None
        return str(expiry_date)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full car and vignette details."""
        return self._common_attributes()
