"""Helper utilities for RO Auto."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (CONF_ENABLE_ITP, CONF_ENABLE_RCA, CONF_ITP_API_URL,
                    CONF_ITP_PASSWORD, CONF_ITP_USERNAME, CONF_RCA_API_URL,
                    CONF_RCA_PASSWORD, CONF_RCA_USERNAME, CONF_VEHICLES,
                    LEGACY_CONF_CARS)


def get_vehicles_for_entry(entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return configured vehicles, preferring options over data."""
    options_vehicles = entry.options.get(CONF_VEHICLES)
    if isinstance(options_vehicles, list):
        return options_vehicles
    legacy_options_cars = entry.options.get(LEGACY_CONF_CARS)
    if isinstance(legacy_options_cars, list):
        return legacy_options_cars

    data_vehicles = entry.data.get(CONF_VEHICLES)
    if isinstance(data_vehicles, list):
        return data_vehicles
    legacy_data_cars = entry.data.get(LEGACY_CONF_CARS)
    if isinstance(legacy_data_cars, list):
        return legacy_data_cars

    return []


def get_rca_settings_for_entry(entry: ConfigEntry) -> dict[str, Any]:
    """Return RCA settings, preferring options over data."""
    keys = (CONF_ENABLE_RCA, CONF_RCA_API_URL, CONF_RCA_USERNAME, CONF_RCA_PASSWORD)

    options = {k: entry.options.get(k) for k in keys if k in entry.options}
    data = {k: entry.data.get(k) for k in keys if k in entry.data}

    # Options override data for reconfiguration via the gear menu.
    return {**data, **options}


def get_itp_settings_for_entry(entry: ConfigEntry) -> dict[str, Any]:
    """Return ITP settings, preferring options over data."""
    keys = (CONF_ENABLE_ITP, CONF_ITP_API_URL, CONF_ITP_USERNAME, CONF_ITP_PASSWORD)

    options = {k: entry.options.get(k) for k in keys if k in entry.options}
    data = {k: entry.data.get(k) for k in keys if k in entry.data}

    return {**data, **options}
