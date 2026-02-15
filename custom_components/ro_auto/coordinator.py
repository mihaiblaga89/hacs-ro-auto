"""Data update coordinator for RO Auto."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import ErovinietaApiClient, ItpApiClient, RcaApiClient
from .const import (CONF_ENABLE_ITP, CONF_ENABLE_RCA, CONF_ITP_API_URL,
                    CONF_ITP_PASSWORD, CONF_ITP_USERNAME, CONF_MAKE,
                    CONF_MODEL, CONF_RCA_API_URL, CONF_RCA_PASSWORD,
                    CONF_RCA_USERNAME, CONF_REGISTRATION_NUMBER, CONF_VIN,
                    CONF_YEAR, DOMAIN)
from .helpers import (get_cars_for_entry, get_itp_settings_for_entry,
                      get_rca_settings_for_entry)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(days=1)
CACHE_TTL = timedelta(hours=24)
CACHE_STORAGE_VERSION = 1
CACHE_STORAGE_KEY = f"{DOMAIN}.cache"
NOTIFICATION_ID_PREFIX = f"{DOMAIN}_api_errors"


class RoAutoCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator that fetches all configured cars."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        self.config_entry = entry
        self._store: Store[dict[str, Any]] = Store(hass, CACHE_STORAGE_VERSION, CACHE_STORAGE_KEY)
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

        self._itp_settings = get_itp_settings_for_entry(entry)
        self._itp_client: ItpApiClient | None = None
        if self._itp_settings.get(CONF_ENABLE_ITP):
            api_url = self._itp_settings.get(CONF_ITP_API_URL) or ""
            username = self._itp_settings.get(CONF_ITP_USERNAME) or ""
            password = self._itp_settings.get(CONF_ITP_PASSWORD) or ""
            if api_url and username and password:
                self._itp_client = ItpApiClient(
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

    async def async_load_cache(self) -> bool:
        """Load cached data and set it if it is still fresh.

        This prevents a forced API refresh on every Home Assistant restart.
        """
        try:
            cache = await self._store.async_load()
        except Exception as err:  # pragma: no cover
            _LOGGER.debug("Failed to load cache: %s", err)
            return False

        if not isinstance(cache, dict):
            return False

        entry_cache = cache.get(self.config_entry.entry_id)
        if not isinstance(entry_cache, dict):
            return False

        saved_at = entry_cache.get("saved_at")
        cached_data = entry_cache.get("data")
        if not isinstance(saved_at, str) or not isinstance(cached_data, dict):
            return False

        try:
            saved_dt = datetime.fromisoformat(saved_at)
        except ValueError:
            return False

        now = datetime.now(tz=UTC)
        if saved_dt.tzinfo is None:
            saved_dt = saved_dt.replace(tzinfo=UTC)

        if now - saved_dt > CACHE_TTL:
            return False

        # Use cached data; polling will resume normally once entities subscribe.
        self.async_set_updated_data(cached_data)
        return True

    async def _async_save_cache(self, data: dict[str, dict[str, Any]]) -> None:
        """Persist cached data to Home Assistant storage."""
        try:
            cache = await self._store.async_load()
        except Exception:
            cache = None

        if not isinstance(cache, dict):
            cache = {}

        cache[self.config_entry.entry_id] = {
            "saved_at": datetime.now(tz=UTC).isoformat(),
            "data": data,
        }

        try:
            await self._store.async_save(cache)
        except Exception as err:  # pragma: no cover
            _LOGGER.debug("Failed to save cache: %s", err)

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
                    "vignetteError": previous.get("vignetteError"),
                    "rcaError": previous.get("rcaError"),
                    "itpError": previous.get("itpError"),
                    "itpStatus": previous.get("itpStatus"),
                    "itpAttempts": previous.get("itpAttempts"),
                    "itpValidUntilRaw": previous.get("itpValidUntilRaw"),
                    "itpIsValid": previous.get("itpIsValid"),
                    "itpLastUpdate": previous.get("itpLastUpdate"),
                }
                continue

            data[vin] = result

        await self._async_handle_failures_notification(data)
        await self._async_save_cache(data)
        return data

    async def _async_handle_failures_notification(
        self, data: dict[str, dict[str, Any]]
    ) -> None:
        """Create/update a persistent notification when API calls fail."""
        errors: list[str] = []
        for vin, car_data in data.items():
            vignette_error = car_data.get("vignetteError")
            if vignette_error:
                errors.append(f"- {vin}: vignette error: {vignette_error}")

            if self._rca_client is not None:
                rca_error = car_data.get("rcaError")
                if rca_error:
                    errors.append(f"- {vin}: RCA error: {rca_error}")

            if self._itp_client is not None:
                itp_error = car_data.get("itpError")
                if itp_error:
                    errors.append(f"- {vin}: ITP error: {itp_error}")

        notification_id = f"{NOTIFICATION_ID_PREFIX}_{self.config_entry.entry_id}"

        if not errors:
            persistent_notification.async_dismiss(self.hass, notification_id)
            return

        message = (
            "RO Auto has one or more API errors:\n\n"
            + "\n".join(errors)
            + "\n\nCheck Home Assistant logs for full details."
        )
        persistent_notification.async_create(
            self.hass,
            message,
            title="RO Auto API error",
            notification_id=notification_id,
        )

    async def _async_build_car_payload(self, car: dict[str, Any]) -> dict[str, Any]:
        """Build one car payload with live vignette/RCA/ITP data.

        Vignette, RCA and ITP are intentionally independent: if any call fails, we keep
        the last known values for that subsystem (or None if we have none yet).
        """
        vin = str(car[CONF_VIN]).upper()
        plate = str(car[CONF_REGISTRATION_NUMBER]).upper()

        previous = (self.data or {}).get(vin, {})

        vignette_task = self._api.async_fetch_vignette(plate_number=plate, vin=vin)
        rca_task = self._rca_client.async_check(plate=plate) if self._rca_client else None
        itp_task = self._itp_client.async_check(vin=vin) if self._itp_client else None

        results = await asyncio.gather(
            vignette_task,
            rca_task if rca_task is not None else asyncio.sleep(0, result=None),
            itp_task if itp_task is not None else asyncio.sleep(0, result=None),
            return_exceptions=True,
        )
        vignette_result, rca_result, itp_result = results

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
            "vignetteError": previous.get("vignetteError"),
            "rcaQueryDate": previous.get("rcaQueryDate"),
            "rcaIsValid": previous.get("rcaIsValid"),
            "rcaValidityStartDate": previous.get("rcaValidityStartDate"),
            "rcaValidityEndDate": previous.get("rcaValidityEndDate"),
            "rcaLastUpdate": previous.get("rcaLastUpdate"),
            "rcaError": previous.get("rcaError"),
            "itpStatus": previous.get("itpStatus"),
            "itpAttempts": previous.get("itpAttempts"),
            "itpValidUntilRaw": previous.get("itpValidUntilRaw"),
            "itpIsValid": previous.get("itpIsValid"),
            "itpLastUpdate": previous.get("itpLastUpdate"),
            "itpError": previous.get("itpError"),
            "lastUpdate": previous.get("lastUpdate"),
        }

        if isinstance(vignette_result, Exception):
            _LOGGER.warning(
                "Vignette refresh failed for %s (%s)",
                car.get(CONF_NAME, plate),
                plate,
                exc_info=vignette_result,
            )
            payload["vignetteError"] = str(vignette_result)
        else:
            vignette_data = vignette_result
            payload.update(
                {
                    "vignetteValid": vignette_data.get("vignetteValid"),
                    "vignetteExpiryDate": vignette_data.get("vignetteExpiryDate"),
                    "dataStop": vignette_data.get("dataStop"),
                    "vignetteLastUpdate": now,
                    "vignetteError": None,
                }
            )
            payload["lastUpdate"] = now

        if isinstance(rca_result, Exception):
            _LOGGER.warning(
                "RCA refresh failed for %s (%s)",
                car.get(CONF_NAME, plate),
                plate,
                exc_info=rca_result,
            )
            payload["rcaError"] = str(rca_result)
        elif isinstance(rca_result, dict):
            payload.update(
                {
                    "rcaQueryDate": rca_result.get("query_date"),
                    "rcaIsValid": rca_result.get("is_valid"),
                    "rcaValidityStartDate": rca_result.get("validity_start_date"),
                    "rcaValidityEndDate": rca_result.get("validity_end_date"),
                    "rcaLastUpdate": now,
                    "rcaError": None,
                }
            )
            payload["lastUpdate"] = now

        if isinstance(itp_result, Exception):
            _LOGGER.warning(
                "ITP refresh failed for %s (%s)",
                car.get(CONF_NAME, vin),
                vin,
                exc_info=itp_result,
            )
            payload["itpError"] = str(itp_result)
        elif isinstance(itp_result, dict):
            status = itp_result.get("status")
            valid_until_raw = itp_result.get("itp_valid_until_raw")
            is_valid = bool(status == "ok" and valid_until_raw)
            payload.update(
                {
                    "itpStatus": status,
                    "itpAttempts": itp_result.get("attempts"),
                    "itpValidUntilRaw": valid_until_raw,
                    "itpIsValid": is_valid,
                    "itpLastUpdate": now,
                    "itpError": None,
                }
            )
            payload["lastUpdate"] = now

        return payload

    @property
    def rca_enabled(self) -> bool:
        """Return if RCA is enabled and configured."""
        return self._rca_client is not None

    @property
    def itp_enabled(self) -> bool:
        """Return if ITP is enabled and configured."""
        return self._itp_client is not None
