"""Data update coordinator for RO Auto."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAKE, CONF_MODEL, CONF_NAME, CONF_VIN, CONF_YEAR
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import get_cars_for_entry
from .api import ErovinietaApiClient

CONF_REGISTRATION_NUMBER = "registrationNumber"

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(hours=12)


class RoAutoCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator that fetches all configured cars."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        self.config_entry = entry
        self.cars = get_cars_for_entry(entry)
        self._api = ErovinietaApiClient(async_get_clientsession(hass))

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="RO Auto",
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch data for all configured cars."""
        tasks = [self._async_build_car_payload(car) for car in self.cars]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        data: dict[str, dict[str, Any]] = {}
        for car, result in zip(self.cars, results, strict=True):
            vin = str(car[CONF_VIN]).upper()
            if isinstance(result, Exception):
                _LOGGER.warning(
                    "Failed to refresh vignette data for %s (%s): %s",
                    car.get(CONF_NAME, vin),
                    vin,
                    result,
                )
                data[vin] = {
                    **car,
                    "vignetteValid": None,
                    "vignetteExpiryDate": None,
                }
                continue

            data[vin] = result

        return data

    async def _async_build_car_payload(self, car: dict[str, Any]) -> dict[str, Any]:
        """Build one car payload with live vignette data."""
        vin = str(car[CONF_VIN]).upper()
        plate = str(car[CONF_REGISTRATION_NUMBER]).upper()

        vignette_data = await self._api.async_fetch_vignette(plate_number=plate, vin=vin)

        return {
            CONF_NAME: car[CONF_NAME],
            CONF_MAKE: car[CONF_MAKE],
            CONF_MODEL: car[CONF_MODEL],
            CONF_YEAR: car[CONF_YEAR],
            CONF_VIN: vignette_data.get("serieSasiu") or vin,
            CONF_REGISTRATION_NUMBER: vignette_data.get("nrAuto") or plate,
            "vignetteValid": vignette_data["vignetteValid"],
            "vignetteExpiryDate": vignette_data["vignetteExpiryDate"],
            "dataStop": vignette_data.get("dataStop"),
        }
