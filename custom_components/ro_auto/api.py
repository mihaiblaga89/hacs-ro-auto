"""API client for erovinieta."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

API_URL = "https://www.erovinieta.ro/vgncheck/api/findVignettes"


def normalize_vignette_payload(data: Any) -> dict[str, Any]:
    """Normalize API response based on the JS contract.

    JS logic:
    - response.data is a list
    - valid vignette when list is not empty
    - values taken from response.data[0].nrAuto/.serieSasiu/.dataStop
    """
    items = data if isinstance(data, list) else []
    has_vignette = len(items) != 0
    first_item = items[0] if has_vignette and isinstance(items[0], dict) else {}

    nr_auto = first_item.get("nrAuto")
    serie_sasiu = first_item.get("serieSasiu")
    data_stop = first_item.get("dataStop")

    return {
        "vignetteValid": has_vignette,
        "vignetteExpiryDate": str(data_stop).strip() if data_stop is not None else None,
        "nrAuto": str(nr_auto).strip().upper() if nr_auto is not None else None,
        "serieSasiu": str(serie_sasiu).strip().upper() if serie_sasiu is not None else None,
        "dataStop": str(data_stop).strip() if data_stop is not None else None,
        "raw": data,
    }


class ErovinietaApiClient:
    """Thin async client for the public erovinieta endpoint."""

    def __init__(self, session: ClientSession) -> None:
        """Initialize the client."""
        self._session = session

    async def async_fetch_vignette(
        self,
        *,
        plate_number: str,
        vin: str,
    ) -> dict[str, Any]:
        """Fetch vignette details for one car."""
        params = {
            "plateNumber": plate_number.strip().upper(),
            "vin": vin.strip().upper(),
            "cacheBuster": str(int(datetime.now(tz=UTC).timestamp() * 1000)),
        }

        try:
            async with asyncio.timeout(20):
                async with self._session.get(API_URL, params=params) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
        except TimeoutError as err:
            raise RuntimeError("Timed out while calling erovinieta API") from err
        except ClientResponseError as err:
            raise RuntimeError(
                f"Erovinieta API returned {err.status} for {plate_number}/{vin}"
            ) from err
        except (ClientError, ValueError) as err:
            raise RuntimeError("Failed to parse erovinieta API response") from err

        return normalize_vignette_payload(payload)
