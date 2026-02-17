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
from .helpers import (get_itp_settings_for_entry, get_rca_settings_for_entry,
                      get_vehicles_for_entry)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(days=1)
CACHE_TTL = timedelta(hours=24)
CACHE_STORAGE_VERSION = 1
CACHE_STORAGE_KEY = f"{DOMAIN}.cache"
NOTIFICATION_ID_PREFIX = f"{DOMAIN}_api_errors"


class RoAutoCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator that fetches all configured vehicles."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        self.config_entry = entry
        self._store: Store[dict[str, Any]] = Store(hass, CACHE_STORAGE_VERSION, CACHE_STORAGE_KEY)
        self.vehicles = get_vehicles_for_entry(entry)
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

    async def async_prime_missing_data(self) -> bool:
        """Fetch missing data only (per vehicle + per subsystem).

        This is used on startup/reload and after adding vehicles. It keeps the integration
        "smart" by only calling the APIs for vehicles/subsystems that are still unknown.

        Returns True if any API call was attempted.
        """
        attempted_any = False
        now = datetime.now(tz=UTC).isoformat()

        new_data: dict[str, dict[str, Any]] = {**(self.data or {})}

        for vehicle in self.vehicles:
            vin = str(vehicle[CONF_VIN]).upper()
            plate = str(vehicle[CONF_REGISTRATION_NUMBER]).upper()
            vehicle_name = str(vehicle.get(CONF_NAME, vin))

            vehicle_data = {**new_data.get(vin, {})}

            # Ensure at least the vehicle metadata exists in the payload.
            vehicle_data.setdefault(CONF_NAME, vehicle.get(CONF_NAME))
            vehicle_data.setdefault(CONF_MAKE, vehicle.get(CONF_MAKE))
            vehicle_data.setdefault(CONF_MODEL, vehicle.get(CONF_MODEL))
            vehicle_data.setdefault(CONF_YEAR, vehicle.get(CONF_YEAR))
            vehicle_data.setdefault(CONF_VIN, vin)
            vehicle_data.setdefault(CONF_REGISTRATION_NUMBER, plate)

            tasks: list[tuple[str, Any]] = []

            # Vignette missing?
            if vehicle_data.get("vignetteValid") is None and not vehicle_data.get("vignetteError"):
                tasks.append(
                    (
                        "vignette",
                        self._api.async_fetch_vignette(plate_number=plate, vin=vin),
                    )
                )

            # RCA missing?
            if self._rca_client is not None:
                if vehicle_data.get("rcaIsValid") is None and not vehicle_data.get("rcaError"):
                    tasks.append(("rca", self._rca_client.async_check(plate=plate)))

            # ITP missing?
            if self._itp_client is not None:
                if vehicle_data.get("itpIsValid") is None and not vehicle_data.get("itpError"):
                    tasks.append(("itp", self._itp_client.async_check(vin=vin)))

            if not tasks:
                new_data[vin] = vehicle_data
                continue

            attempted_any = True
            results = await asyncio.gather(
                *(task for _, task in tasks),
                return_exceptions=True,
            )
            result_map = dict(zip((key for key, _ in tasks), results, strict=True))

            self._apply_vignette_result(
                vehicle_data,
                result_map.get("vignette"),
                now=now,
                vehicle_name=vehicle_name,
                plate=plate,
                context="Startup",
            )
            self._apply_rca_result(
                vehicle_data,
                result_map.get("rca"),
                now=now,
                vehicle_name=vehicle_name,
                plate=plate,
                context="Startup",
            )
            self._apply_itp_result(
                vehicle_data,
                result_map.get("itp"),
                now=now,
                vehicle_name=vehicle_name,
                vin=vin,
                context="Startup",
            )

            new_data[vin] = vehicle_data

        if attempted_any:
            self.async_set_updated_data(new_data)
            await self._async_handle_failures_notification(new_data)
            await self._async_save_cache(new_data)

        return attempted_any

    def cache_needs_initial_refresh(self) -> bool:
        """Return True if enabled subsystems have no data yet.

        Used to force an initial refresh after enabling RCA/ITP even if the cache is fresh.
        """
        if not isinstance(self.data, dict) or not self.data:
            return True

        for vehicle in self.vehicles:
            vin = str(vehicle[CONF_VIN]).upper()
            vehicle_data = self.data.get(vin, {})
            if not isinstance(vehicle_data, dict):
                return True

            if vehicle_data.get("vignetteValid") is None and not vehicle_data.get("vignetteError"):
                return True
            if self._rca_client is not None and vehicle_data.get("rcaIsValid") is None and not vehicle_data.get("rcaError"):
                return True
            if self._itp_client is not None and vehicle_data.get("itpIsValid") is None and not vehicle_data.get("itpError"):
                return True

        return False

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
        """Fetch data for all configured vehicles."""
        tasks = [self._async_build_vehicle_payload(vehicle) for vehicle in self.vehicles]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        data: dict[str, dict[str, Any]] = {}
        for vehicle, result in zip(self.vehicles, results, strict=True):
            vin = str(vehicle[CONF_VIN]).upper()
            if isinstance(result, Exception):
                _LOGGER.warning("Failed to refresh data for %s (%s): %s", vehicle.get(CONF_NAME, vin), vin, result)
                # Keep previous data if possible; otherwise provide empty fields.
                previous = (self.data or {}).get(vin, {})
                data[vin] = {
                    **vehicle,
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
        for vin, vehicle_data in data.items():
            vignette_error = vehicle_data.get("vignetteError")
            if vignette_error:
                errors.append(f"- {vin}: vignette error: {vignette_error}")

            if self._rca_client is not None:
                rca_error = vehicle_data.get("rcaError")
                if rca_error:
                    errors.append(f"- {vin}: RCA error: {rca_error}")

            if self._itp_client is not None:
                itp_error = vehicle_data.get("itpError")
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

    def _apply_vignette_result(
        self,
        vehicle_data: dict[str, Any],
        result: Any,
        *,
        now: str,
        vehicle_name: str,
        plate: str,
        context: str,
    ) -> None:
        """Apply vignette result to a vehicle payload."""
        if result is None:
            return

        if isinstance(result, Exception):
            _LOGGER.warning(
                "%s vignette refresh failed for %s (%s)",
                context,
                vehicle_name,
                plate,
                exc_info=result,
            )
            vehicle_data["vignetteError"] = str(result)
            return

        vehicle_data.update(
            {
                "vignetteValid": result.get("vignetteValid"),
                "vignetteExpiryDate": result.get("vignetteExpiryDate"),
                "dataStop": result.get("dataStop"),
                "vignetteLastUpdate": now,
                "vignetteError": None,
                "lastUpdate": now,
            }
        )

    def _apply_rca_result(
        self,
        vehicle_data: dict[str, Any],
        result: Any,
        *,
        now: str,
        vehicle_name: str,
        plate: str,
        context: str,
    ) -> None:
        """Apply RCA result to a vehicle payload."""
        if result is None:
            return

        if isinstance(result, Exception):
            _LOGGER.warning(
                "%s RCA refresh failed for %s (%s)",
                context,
                vehicle_name,
                plate,
                exc_info=result,
            )
            vehicle_data["rcaError"] = str(result)
            return

        vehicle_data.update(
            {
                "rcaQueryDate": result.get("query_date"),
                "rcaIsValid": result.get("is_valid"),
                "rcaValidityStartDate": result.get("validity_start_date"),
                "rcaValidityEndDate": result.get("validity_end_date"),
                "rcaLastUpdate": now,
                "rcaError": None,
                "lastUpdate": now,
            }
        )

    def _apply_itp_result(
        self,
        vehicle_data: dict[str, Any],
        result: Any,
        *,
        now: str,
        vehicle_name: str,
        vin: str,
        context: str,
    ) -> None:
        """Apply ITP result to a vehicle payload."""
        if result is None:
            return

        if isinstance(result, Exception):
            _LOGGER.warning(
                "%s ITP refresh failed for %s (%s)",
                context,
                vehicle_name,
                vin,
                exc_info=result,
            )
            vehicle_data["itpError"] = str(result)
            return

        status = result.get("status")
        valid_until_raw = result.get("itp_valid_until_raw")
        is_valid = bool(status == "ok" and valid_until_raw)
        vehicle_data.update(
            {
                "itpStatus": status,
                "itpAttempts": result.get("attempts"),
                "itpResultVin": result.get("result_vin"),
                "itpValidUntilRaw": valid_until_raw,
                "itpIsValid": is_valid,
                "itpLastUpdate": now,
                "itpError": None,
                "lastUpdate": now,
            }
        )

    async def async_manual_refresh_rca(self) -> None:
        """Refresh RCA only (do not trigger vignette/ITP)."""
        if self._rca_client is None:
            _LOGGER.warning("Manual RCA refresh requested but RCA is not enabled/configured")
            return

        now = datetime.now(tz=UTC).isoformat()
        tasks: list[asyncio.Future[Any] | asyncio.Task[Any]] = []
        vehicles: list[tuple[str, str, str]] = []
        for vehicle in self.vehicles:
            vin = str(vehicle[CONF_VIN]).upper()
            plate = str(vehicle[CONF_REGISTRATION_NUMBER]).upper()
            vehicle_name = str(vehicle.get(CONF_NAME, vin))
            vehicles.append((vin, plate, vehicle_name))
            tasks.append(asyncio.create_task(self._rca_client.async_check(plate=plate)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        new_data: dict[str, dict[str, Any]] = {**(self.data or {})}
        for (vin, plate, vehicle_name), result in zip(vehicles, results, strict=True):
            vehicle_data = {**new_data.get(vin, {})}
            self._apply_rca_result(
                vehicle_data,
                result,
                now=now,
                vehicle_name=vehicle_name,
                plate=plate,
                context="Manual",
            )
            new_data[vin] = vehicle_data

        self.async_set_updated_data(new_data)
        await self._async_handle_failures_notification(new_data)
        await self._async_save_cache(new_data)

    async def async_manual_refresh_itp(self) -> None:
        """Refresh ITP only (do not trigger vignette/RCA)."""
        if self._itp_client is None:
            _LOGGER.warning("Manual ITP refresh requested but ITP is not enabled/configured")
            return

        now = datetime.now(tz=UTC).isoformat()
        tasks: list[asyncio.Future[Any] | asyncio.Task[Any]] = []
        vehicles: list[tuple[str, str]] = []
        for vehicle in self.vehicles:
            vin = str(vehicle[CONF_VIN]).upper()
            vehicle_name = str(vehicle.get(CONF_NAME, vin))
            vehicles.append((vin, vehicle_name))
            tasks.append(asyncio.create_task(self._itp_client.async_check(vin=vin)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        new_data: dict[str, dict[str, Any]] = {**(self.data or {})}
        for (vin, vehicle_name), result in zip(vehicles, results, strict=True):
            vehicle_data = {**new_data.get(vin, {})}
            self._apply_itp_result(
                vehicle_data,
                result,
                now=now,
                vehicle_name=vehicle_name,
                vin=vin,
                context="Manual",
            )
            new_data[vin] = vehicle_data

        self.async_set_updated_data(new_data)
        await self._async_handle_failures_notification(new_data)
        await self._async_save_cache(new_data)

    async def _async_build_vehicle_payload(self, vehicle: dict[str, Any]) -> dict[str, Any]:
        """Build one vehicle payload with live vignette/RCA/ITP data.

        Vignette, RCA and ITP are intentionally independent: if any call fails, we keep
        the last known values for that subsystem (or None if we have none yet).
        """
        vin = str(vehicle[CONF_VIN]).upper()
        plate = str(vehicle[CONF_REGISTRATION_NUMBER]).upper()

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
            CONF_NAME: vehicle[CONF_NAME],
            CONF_MAKE: vehicle[CONF_MAKE],
            CONF_MODEL: vehicle[CONF_MODEL],
            CONF_YEAR: vehicle[CONF_YEAR],
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

        vehicle_name = str(vehicle.get(CONF_NAME, vin))
        self._apply_vignette_result(
            payload,
            vignette_result,
            now=now,
            vehicle_name=vehicle_name,
            plate=plate,
            context="Scheduled",
        )
        self._apply_rca_result(
            payload,
            rca_result,
            now=now,
            vehicle_name=vehicle_name,
            plate=plate,
            context="Scheduled",
        )
        self._apply_itp_result(
            payload,
            itp_result,
            now=now,
            vehicle_name=vehicle_name,
            vin=vin,
            context="Scheduled",
        )

        return payload

    @property
    def rca_enabled(self) -> bool:
        """Return if RCA is enabled and configured."""
        return self._rca_client is not None

    @property
    def itp_enabled(self) -> bool:
        """Return if ITP is enabled and configured."""
        return self._itp_client is not None
