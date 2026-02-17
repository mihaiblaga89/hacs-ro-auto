"""The RO Auto integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import CONF_VEHICLES, DOMAIN, LEGACY_CONF_CARS
from .coordinator import RoAutoCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the RO Auto integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up RO Auto from a config entry."""
    # Migrate legacy key "cars" -> "vehicles" to keep existing entities provided.
    if CONF_VEHICLES not in entry.data and LEGACY_CONF_CARS in entry.data:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_VEHICLES: entry.data[LEGACY_CONF_CARS]},
        )
    if CONF_VEHICLES not in entry.options and LEGACY_CONF_CARS in entry.options:
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_VEHICLES: entry.options[LEGACY_CONF_CARS]},
        )

    coordinator = RoAutoCoordinator(hass, entry)
    await coordinator.async_load_cache()
    await coordinator.async_prime_missing_data()
    if coordinator.cache_needs_initial_refresh():
        # Fallback: ensure we never leave entities unknown at startup.
        await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry after options update."""
    await hass.config_entries.async_reload(entry.entry_id)
