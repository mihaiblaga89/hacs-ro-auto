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
                    CONF_VIGNETTE_ENABLED, CONF_YEAR, DOMAIN)
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

    vins_vignette_disabled = {
        str(v[CONF_VIN]).upper()
        for v in coordinator.vehicles
        if not v.get(CONF_VIGNETTE_ENABLED, True)
    }
    prefix = f"{entry.entry_id}_"
    registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity_entry.platform != DOMAIN:
            continue
        unique_id = entity_entry.unique_id or ""
        if unique_id.startswith(prefix) and unique_id.endswith("_vignette_expiry_date"):
            vin = unique_id[len(prefix) : -len("_vignette_expiry_date")]
            if vin.upper() in vins_vignette_disabled:
                registry.async_remove(entity_entry.entity_id)
        elif unique_id.startswith(prefix) and unique_id.endswith("_vignette"):
            vin = unique_id[len(prefix) : -len("_vignette")]
            if vin.upper() in vins_vignette_disabled:
                registry.async_remove(entity_entry.entity_id)
        if not coordinator.rca_enabled and (
            unique_id.endswith("_rca") or unique_id.endswith("_rca_expiry_date")
        ):
            registry.async_remove(entity_entry.entity_id)
        if not coordinator.itp_enabled and (
            unique_id.endswith("_itp") or unique_id.endswith("_itp_expiry_date")
        ):
            registry.async_remove(entity_entry.entity_id)

    entities: list[SensorEntity] = []
    for vehicle in coordinator.vehicles:
        if vehicle.get(CONF_VIGNETTE_ENABLED, True):
            entities.append(RoAutoVehicleVignetteStatusSensor(coordinator, entry, vehicle))
            entities.append(RoAutoVehicleVignetteExpirySensor(coordinator, entry, vehicle))
        if coordinator.rca_enabled:
            entities.append(RoAutoVehicleRcaStatusSensor(coordinator, entry, vehicle))
            entities.append(RoAutoVehicleRcaExpirySensor(coordinator, entry, vehicle))
        if coordinator.itp_enabled:
            entities.append(RoAutoVehicleItpStatusSensor(coordinator, entry, vehicle))
            entities.append(RoAutoVehicleItpExpirySensor(coordinator, entry, vehicle))
    async_add_entities(entities)


class RoAutoVehicleBaseSensor(CoordinatorEntity[RoAutoCoordinator], SensorEntity):
    """Base sensor for a configured vehicle."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: RoAutoCoordinator, entry: ConfigEntry, vehicle: dict[str, Any]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._vin = str(vehicle[CONF_VIN]).upper()
        self._registration_number = str(vehicle[CONF_REGISTRATION_NUMBER]).upper()
        self._entry_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._vin)},
            name=vehicle[CONF_NAME],
            manufacturer=vehicle[CONF_MAKE],
            model=vehicle[CONF_MODEL],
            serial_number=self._vin,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._vin in self.coordinator.data

    def _vehicle_attributes_for_expiry(self) -> dict[str, Any]:
        """Return minimal vehicle attributes for expiry sensors."""
        vehicle_data = self.coordinator.data.get(self._vin, {})
        return {
            CONF_MAKE: vehicle_data.get(CONF_MAKE),
            CONF_MODEL: vehicle_data.get(CONF_MODEL),
            CONF_VIN: vehicle_data.get(CONF_VIN, self._vin),
            CONF_REGISTRATION_NUMBER: vehicle_data.get(
                CONF_REGISTRATION_NUMBER, self._registration_number
            ),
        }


class RoAutoVehicleVignetteStatusSensor(RoAutoVehicleBaseSensor):
    """Sensor exposing vignette validity status."""

    def __init__(
        self, coordinator: RoAutoCoordinator, entry: ConfigEntry, vehicle: dict[str, Any]
    ) -> None:
        """Initialize the vignette status sensor."""
        super().__init__(coordinator, entry, vehicle)
        self._attr_unique_id = f"{self._entry_id}_{self._vin}_vignette"
        self._attr_name = "vignette"
        self._attr_icon = "mdi:car-info"
        # Display as a known set of values.
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = ["valid", "invalid", "unknown"]

    @property
    def native_value(self) -> str:
        """Return current vignette status."""
        vehicle_data = self.coordinator.data.get(self._vin, {})
        valid = vehicle_data.get("vignetteValid")
        if valid is True:
            return "valid"
        if valid is False:
            return "invalid"
        return "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return vignette-only attributes."""
        vehicle_data = self.coordinator.data.get(self._vin, {})
        return {
            "vignetteValid": vehicle_data.get("vignetteValid"),
            "vignetteExpiryDate": vehicle_data.get("vignetteExpiryDate"),
            "vignetteLastUpdate": vehicle_data.get("vignetteLastUpdate"),
            "dataStop": vehicle_data.get("dataStop"),
        }


class RoAutoVehicleVignetteExpirySensor(RoAutoVehicleBaseSensor):
    """Sensor exposing vignette expiry date."""

    def __init__(
        self, coordinator: RoAutoCoordinator, entry: ConfigEntry, vehicle: dict[str, Any]
    ) -> None:
        """Initialize the vignette expiry sensor."""
        super().__init__(coordinator, entry, vehicle)
        self._attr_unique_id = f"{self._entry_id}_{self._vin}_vignette_expiry_date"
        self._attr_name = "vignette expiry date"
        self._attr_icon = "mdi:calendar-clock"
        self._attr_device_class = SensorDeviceClass.DATE

    @property
    def native_value(self) -> date | None:
        """Return vignette expiry date (date-only)."""
        vehicle_data = self.coordinator.data.get(self._vin, {})
        return _parse_date(vehicle_data.get("vignetteExpiryDate"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return vehicle + vignette expiry attributes."""
        vehicle_data = self.coordinator.data.get(self._vin, {})
        return {
            **self._vehicle_attributes_for_expiry(),
            "vignetteValid": vehicle_data.get("vignetteValid"),
            "vignetteExpiryDate": vehicle_data.get("vignetteExpiryDate"),
            "vignetteLastUpdate": vehicle_data.get("vignetteLastUpdate"),
            "dataStop": vehicle_data.get("dataStop"),
        }


class RoAutoVehicleRcaStatusSensor(RoAutoVehicleBaseSensor):
    """Sensor exposing RCA validity status."""

    def __init__(
        self, coordinator: RoAutoCoordinator, entry: ConfigEntry, vehicle: dict[str, Any]
    ) -> None:
        """Initialize the RCA status sensor."""
        super().__init__(coordinator, entry, vehicle)
        self._attr_unique_id = f"{self._entry_id}_{self._vin}_rca"
        self._attr_name = "rca"
        self._attr_icon = "mdi:shield-car"
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = ["valid", "invalid", "unknown"]

    @property
    def native_value(self) -> str:
        """Return current RCA status."""
        vehicle_data = self.coordinator.data.get(self._vin, {})
        valid = vehicle_data.get("rcaIsValid")
        if valid is True:
            return "valid"
        if valid is False:
            return "invalid"
        return "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return RCA-only attributes."""
        vehicle_data = self.coordinator.data.get(self._vin, {})
        return {
            "rcaQueryDate": vehicle_data.get("rcaQueryDate"),
            "rcaIsValid": vehicle_data.get("rcaIsValid"),
            "rcaValidityStartDate": vehicle_data.get("rcaValidityStartDate"),
            "rcaValidityEndDate": vehicle_data.get("rcaValidityEndDate"),
            "rcaLastUpdate": vehicle_data.get("rcaLastUpdate"),
        }


class RoAutoVehicleRcaExpirySensor(RoAutoVehicleBaseSensor):
    """Sensor exposing RCA validity end date."""

    def __init__(
        self, coordinator: RoAutoCoordinator, entry: ConfigEntry, vehicle: dict[str, Any]
    ) -> None:
        """Initialize the RCA expiry sensor."""
        super().__init__(coordinator, entry, vehicle)
        self._attr_unique_id = f"{self._entry_id}_{self._vin}_rca_expiry_date"
        self._attr_name = "rca expiry date"
        self._attr_icon = "mdi:calendar-clock"
        self._attr_device_class = SensorDeviceClass.DATE

    @property
    def native_value(self) -> date | None:
        """Return RCA validity end date (date-only)."""
        vehicle_data = self.coordinator.data.get(self._vin, {})
        return _parse_date(vehicle_data.get("rcaValidityEndDate"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return vehicle + RCA expiry attributes."""
        vehicle_data = self.coordinator.data.get(self._vin, {})
        return {
            **self._vehicle_attributes_for_expiry(),
            "rcaQueryDate": vehicle_data.get("rcaQueryDate"),
            "rcaIsValid": vehicle_data.get("rcaIsValid"),
            "rcaValidityStartDate": vehicle_data.get("rcaValidityStartDate"),
            "rcaValidityEndDate": vehicle_data.get("rcaValidityEndDate"),
            "rcaLastUpdate": vehicle_data.get("rcaLastUpdate"),
        }


class RoAutoVehicleItpStatusSensor(RoAutoVehicleBaseSensor):
    """Sensor exposing ITP validity status."""

    def __init__(
        self, coordinator: RoAutoCoordinator, entry: ConfigEntry, vehicle: dict[str, Any]
    ) -> None:
        """Initialize the ITP status sensor."""
        super().__init__(coordinator, entry, vehicle)
        self._attr_unique_id = f"{self._entry_id}_{self._vin}_itp"
        self._attr_name = "itp"
        self._attr_icon = "mdi:wrench-check"
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = ["valid", "invalid", "unknown"]

    @property
    def native_value(self) -> str:
        """Return current ITP status."""
        vehicle_data = self.coordinator.data.get(self._vin, {})
        valid = vehicle_data.get("itpIsValid")
        if valid is True:
            return "valid"
        if valid is False:
            return "invalid"
        return "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return ITP-only attributes."""
        vehicle_data = self.coordinator.data.get(self._vin, {})
        return {
            "itpStatus": vehicle_data.get("itpStatus"),
            "itpAttempts": vehicle_data.get("itpAttempts"),
            "itpValidUntilRaw": vehicle_data.get("itpValidUntilRaw"),
            "itpIsValid": vehicle_data.get("itpIsValid"),
            "itpLastUpdate": vehicle_data.get("itpLastUpdate"),
        }


class RoAutoVehicleItpExpirySensor(RoAutoVehicleBaseSensor):
    """Sensor exposing ITP validity end date."""

    def __init__(
        self, coordinator: RoAutoCoordinator, entry: ConfigEntry, vehicle: dict[str, Any]
    ) -> None:
        """Initialize the ITP expiry sensor."""
        super().__init__(coordinator, entry, vehicle)
        self._attr_unique_id = f"{self._entry_id}_{self._vin}_itp_expiry_date"
        self._attr_name = "itp expiry date"
        self._attr_icon = "mdi:calendar-clock"
        self._attr_device_class = SensorDeviceClass.DATE

    @property
    def native_value(self) -> date | None:
        """Return ITP validity end date (date-only)."""
        vehicle_data = self.coordinator.data.get(self._vin, {})
        return _parse_date(vehicle_data.get("itpValidUntilRaw"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return vehicle + ITP expiry attributes."""
        vehicle_data = self.coordinator.data.get(self._vin, {})
        return {
            **self._vehicle_attributes_for_expiry(),
            "itpStatus": vehicle_data.get("itpStatus"),
            "itpAttempts": vehicle_data.get("itpAttempts"),
            "itpValidUntilRaw": vehicle_data.get("itpValidUntilRaw"),
            "itpIsValid": vehicle_data.get("itpIsValid"),
            "itpLastUpdate": vehicle_data.get("itpLastUpdate"),
        }
