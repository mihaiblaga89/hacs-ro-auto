"""Helper utilities for RO Auto."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_CARS,
    CONF_ENABLE_RCA,
    CONF_RCA_API_URL,
    CONF_RCA_PASSWORD,
    CONF_RCA_USERNAME,
)


def get_cars_for_entry(entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return configured cars, preferring options over data."""
    options_cars = entry.options.get(CONF_CARS)
    if isinstance(options_cars, list):
        return options_cars

    data_cars = entry.data.get(CONF_CARS)
    if isinstance(data_cars, list):
        return data_cars

    return []


def get_rca_settings_for_entry(entry: ConfigEntry) -> dict[str, Any]:
    """Return RCA settings, preferring options over data."""
    keys = (CONF_ENABLE_RCA, CONF_RCA_API_URL, CONF_RCA_USERNAME, CONF_RCA_PASSWORD)

    options = {k: entry.options.get(k) for k in keys if k in entry.options}
    data = {k: entry.data.get(k) for k in keys if k in entry.data}

    # Options override data for reconfiguration via the gear menu.
    return {**data, **options}
