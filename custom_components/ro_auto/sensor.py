"""Sensor platform for RO Auto."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import \
    AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (CONF_MAKE, CONF_MODEL, CONF_REGISTRATION_NUMBER, CONF_VIN,
                    CONF_YEAR, DOMAIN)
from .coordinator import RoAutoCoordinator


def _parse_date(value: Any) -> date | None:
    """Parse a date-only value from API payloads."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()

    text = str(value).strip()
    if not text:
        return None

    # Common examples:
    # - RCA API: "23.10.2026"
    # - Vignette data: "2026-07-31 23:59:59"
    for fmt in (
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    # Try ISO parsing (accept " " separator too).
    try:
        return datetime.fromisoformat(text.replace(" ", "T")).date()
    except ValueError:
        return None
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up RO Auto sensors from a config entry."""
    coordinator: RoAutoCoordinator = hass.data[DOMAIN][entry.entry_id]

    # If RCA is disabled/unconfigured, remove any old RCA entities that may have
    # been created when RCA was previously enabled.
    if not coordinator.rca_enabled:
        registry = er.async_get(hass)
        for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            if entity_entry.platform != DOMAIN:
                continue
            unique_id = entity_entry.unique_id or ""
            if unique_id.endswith("_rca") or unique_id.endswith("_rca_expiry_date"):
                registry.async_remove(entity_entry.entity_id)

    entities: list[SensorEntity] = []
    for car in coordinator.cars:
        entities.append(RoAutoCarVignetteStatusSensor(coordinator, entry, car))
        entities.append(RoAutoCarVignetteExpirySensor(coordinator, entry, car))
        if coordinator.rca_enabled:
            entities.append(RoAutoCarRcaStatusSensor(coordinator, entry, car))
            entities.append(RoAutoCarRcaExpirySensor(coordinator, entry, car))
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
            "vignetteLastUpdate": car_data.get("vignetteLastUpdate"),
            "dataStop": car_data.get("dataStop"),
            "rcaQueryDate": car_data.get("rcaQueryDate"),
            "rcaIsValid": car_data.get("rcaIsValid"),
            "rcaValidityStartDate": car_data.get("rcaValidityStartDate"),
            "rcaValidityEndDate": car_data.get("rcaValidityEndDate"),
            "rcaLastUpdate": car_data.get("rcaLastUpdate"),
            "lastUpdate": car_data.get("lastUpdate"),
        }

    def _car_attributes(self) -> dict[str, Any]:
        """Return car metadata attributes."""
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
        }

    def _car_attributes_for_expiry(self) -> dict[str, Any]:
        """Return minimal car attributes for expiry sensors."""
        car_data = self.coordinator.data.get(self._vin, {})
        return {
            CONF_MAKE: car_data.get(CONF_MAKE),
            CONF_MODEL: car_data.get(CONF_MODEL),
            CONF_VIN: car_data.get(CONF_VIN, self._vin),
            CONF_REGISTRATION_NUMBER: car_data.get(
                CONF_REGISTRATION_NUMBER, self._registration_number
            ),
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
        # Display as a known set of values.
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = ["valid", "invalid", "unknown"]

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
        """Return vignette-only attributes."""
        car_data = self.coordinator.data.get(self._vin, {})
        return {
            "vignetteValid": car_data.get("vignetteValid"),
            "vignetteExpiryDate": car_data.get("vignetteExpiryDate"),
            "vignetteLastUpdate": car_data.get("vignetteLastUpdate"),
            "dataStop": car_data.get("dataStop"),
        }


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
        self._attr_device_class = SensorDeviceClass.DATE

    @property
    def native_value(self) -> date | None:
        """Return vignette expiry date (date-only)."""
        car_data = self.coordinator.data.get(self._vin, {})
        return _parse_date(car_data.get("vignetteExpiryDate"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return car + vignette expiry attributes."""
        car_data = self.coordinator.data.get(self._vin, {})
        return {
            **self._car_attributes_for_expiry(),
            "vignetteValid": car_data.get("vignetteValid"),
            "vignetteExpiryDate": car_data.get("vignetteExpiryDate"),
            "vignetteLastUpdate": car_data.get("vignetteLastUpdate"),
            "dataStop": car_data.get("dataStop"),
        }


class RoAutoCarRcaStatusSensor(RoAutoCarBaseSensor):
    """Sensor exposing RCA validity status."""

    def __init__(
        self, coordinator: RoAutoCoordinator, entry: ConfigEntry, car: dict[str, Any]
    ) -> None:
        """Initialize the RCA status sensor."""
        super().__init__(coordinator, entry, car)
        self._attr_unique_id = f"{self._entry_id}_{self._vin}_rca"
        self._attr_name = "rca"
        self._attr_icon = "mdi:shield-car"
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = ["valid", "invalid", "unknown"]

    @property
    def native_value(self) -> str:
        """Return current RCA status."""
        car_data = self.coordinator.data.get(self._vin, {})
        valid = car_data.get("rcaIsValid")
        if valid is True:
            return "valid"
        if valid is False:
            return "invalid"
        return "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return RCA-only attributes."""
        car_data = self.coordinator.data.get(self._vin, {})
        return {
            "rcaQueryDate": car_data.get("rcaQueryDate"),
            "rcaIsValid": car_data.get("rcaIsValid"),
            "rcaValidityStartDate": car_data.get("rcaValidityStartDate"),
            "rcaValidityEndDate": car_data.get("rcaValidityEndDate"),
            "rcaLastUpdate": car_data.get("rcaLastUpdate"),
        }


class RoAutoCarRcaExpirySensor(RoAutoCarBaseSensor):
    """Sensor exposing RCA validity end date."""

    def __init__(
        self, coordinator: RoAutoCoordinator, entry: ConfigEntry, car: dict[str, Any]
    ) -> None:
        """Initialize the RCA expiry sensor."""
        super().__init__(coordinator, entry, car)
        self._attr_unique_id = f"{self._entry_id}_{self._vin}_rca_expiry_date"
        self._attr_name = "rca expiry date"
        self._attr_icon = "mdi:calendar-check"
        self._attr_device_class = SensorDeviceClass.DATE

    @property
    def native_value(self) -> date | None:
        """Return RCA validity end date (date-only)."""
        car_data = self.coordinator.data.get(self._vin, {})
        return _parse_date(car_data.get("rcaValidityEndDate"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return car + RCA expiry attributes."""
        car_data = self.coordinator.data.get(self._vin, {})
        return {
            **self._car_attributes_for_expiry(),
            "rcaQueryDate": car_data.get("rcaQueryDate"),
            "rcaIsValid": car_data.get("rcaIsValid"),
            "rcaValidityStartDate": car_data.get("rcaValidityStartDate"),
            "rcaValidityEndDate": car_data.get("rcaValidityEndDate"),
            "rcaLastUpdate": car_data.get("rcaLastUpdate"),
        }
