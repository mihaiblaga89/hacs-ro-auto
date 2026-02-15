"""Data update coordinator for RO Auto."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import ErovinietaApiClient, RcaApiClient
from .const import (CONF_ENABLE_RCA, CONF_MAKE, CONF_MODEL, CONF_RCA_API_URL,
                    CONF_RCA_PASSWORD, CONF_RCA_USERNAME,
                    CONF_REGISTRATION_NUMBER, CONF_VIN, CONF_YEAR)
from .helpers import get_cars_for_entry, get_rca_settings_for_entry

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(days=1)


class RoAutoCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator that fetches all configured cars."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        self.config_entry = entry
        self.cars = get_cars_for_entry(entry)
        self._api = ErovinietaApiClient(async_get_clientsession(hass))
        self._rca_settings = get_rca_settings_for_entry(entry)
        self._rca_client: RcaApiClient | None = None
        if self._rca_settings.get(CONF_ENABLE_RCA):
            api_url = self._rca_settings.get(CONF_RCA_API_URL) or ""
            username = self._rca_settings.get(CONF_RCA_USERNAME) or ""
            password = self._rca_settings.get(CONF_RCA_PASSWORD) or ""
            if api_url and username and password:
                self._rca_client = RcaApiClient(
                    async_get_clientsession(hass),
                    api_url=api_url,
                    username=username,
                    password=password,
                )

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
                _LOGGER.warning("Failed to refresh data for %s (%s): %s", car.get(CONF_NAME, vin), vin, result)
                # Keep previous data if possible; otherwise provide empty fields.
                previous = (self.data or {}).get(vin, {})
                data[vin] = {
                    **car,
                    **previous,
                    "vignetteValid": previous.get("vignetteValid"),
                    "vignetteExpiryDate": previous.get("vignetteExpiryDate"),
                    "dataStop": previous.get("dataStop"),
                    "rcaQueryDate": previous.get("rcaQueryDate"),
                    "rcaIsValid": previous.get("rcaIsValid"),
                    "rcaValidityStartDate": previous.get("rcaValidityStartDate"),
                    "rcaValidityEndDate": previous.get("rcaValidityEndDate"),
                }
                continue

            data[vin] = result

        return data

    async def _async_build_car_payload(self, car: dict[str, Any]) -> dict[str, Any]:
        """Build one car payload with live vignette/RCA data.

        Vignette and RCA are intentionally independent: if either call fails, we keep
        the last known values for that subsystem (or None if we have none yet).
        """
        vin = str(car[CONF_VIN]).upper()
        plate = str(car[CONF_REGISTRATION_NUMBER]).upper()

        previous = (self.data or {}).get(vin, {})

        vignette_task = self._api.async_fetch_vignette(plate_number=plate, vin=vin)
        rca_task = self._rca_client.async_check(plate=plate) if self._rca_client else None

        vignette_result: Any
        rca_result: Any
        if rca_task is not None:
            vignette_result, rca_result = await asyncio.gather(
                vignette_task,
                rca_task,
                return_exceptions=True,
            )
        else:
            vignette_result = await asyncio.gather(vignette_task, return_exceptions=True)
            vignette_result = vignette_result[0]
            rca_result = None

        now = datetime.now(tz=UTC).isoformat()

        payload: dict[str, Any] = {
            CONF_NAME: car[CONF_NAME],
            CONF_MAKE: car[CONF_MAKE],
            CONF_MODEL: car[CONF_MODEL],
            CONF_YEAR: car[CONF_YEAR],
            # Default identifiers from config, can be overwritten by vignette response.
            CONF_VIN: previous.get(CONF_VIN, vin),
            CONF_REGISTRATION_NUMBER: previous.get(CONF_REGISTRATION_NUMBER, plate),
            "vignetteValid": previous.get("vignetteValid"),
            "vignetteExpiryDate": previous.get("vignetteExpiryDate"),
            "dataStop": previous.get("dataStop"),
            "vignetteLastUpdate": previous.get("vignetteLastUpdate"),
            "rcaQueryDate": previous.get("rcaQueryDate"),
            "rcaIsValid": previous.get("rcaIsValid"),
            "rcaValidityStartDate": previous.get("rcaValidityStartDate"),
            "rcaValidityEndDate": previous.get("rcaValidityEndDate"),
            "rcaLastUpdate": previous.get("rcaLastUpdate"),
            "lastUpdate": previous.get("lastUpdate"),
        }

        if isinstance(vignette_result, Exception):
            _LOGGER.debug(
                "Vignette refresh failed for %s (%s): %s",
                car.get(CONF_NAME, plate),
                plate,
                vignette_result,
            )
        else:
            vignette_data = vignette_result
            payload.update(
                {
                    "vignetteValid": vignette_data.get("vignetteValid"),
                    "vignetteExpiryDate": vignette_data.get("vignetteExpiryDate"),
                    "dataStop": vignette_data.get("dataStop"),
                    "vignetteLastUpdate": now,
                }
            )
            payload["lastUpdate"] = now

        if isinstance(rca_result, Exception):
            _LOGGER.debug(
                "RCA refresh failed for %s (%s): %s",
                car.get(CONF_NAME, plate),
                plate,
                rca_result,
            )
        elif isinstance(rca_result, dict):
            payload.update(
                {
                    "rcaQueryDate": rca_result.get("query_date"),
                    "rcaIsValid": rca_result.get("is_valid"),
                    "rcaValidityStartDate": rca_result.get("validity_start_date"),
                    "rcaValidityEndDate": rca_result.get("validity_end_date"),
                    "rcaLastUpdate": now,
                }
            )
            payload["lastUpdate"] = now

        return payload

    @property
    def rca_enabled(self) -> bool:
        """Return if RCA is enabled and configured."""
        return self._rca_client is not None
