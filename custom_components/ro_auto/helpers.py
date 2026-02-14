"""Helper utilities for RO Auto."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import CONF_CARS


def get_cars_for_entry(entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return configured cars, preferring options over data."""
    options_cars = entry.options.get(CONF_CARS)
    if isinstance(options_cars, list):
        return options_cars

    data_cars = entry.data.get(CONF_CARS)
    if isinstance(data_cars, list):
        return data_cars

    return []
